"""Privacy-first Microsoft Graph OAuth and Outlook metadata access."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlencode
from uuid import UUID

import httpx

from app.desktop_secrets import DesktopJsonSecretStore
from app.email_sync import EmailMessageMetadata


MICROSOFT_AUTHORIZATION_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_GRAPH_URL = "https://graph.microsoft.com/v1.0"
MICROSOFT_SCOPES = "openid profile offline_access User.Read Mail.ReadBasic"
AUTHORIZATION_TTL_SECONDS = 600


class OutlookProviderError(RuntimeError):
    pass


class OutlookAuthorizationError(OutlookProviderError):
    pass


@dataclass(frozen=True)
class PendingAuthorization:
    user_id: int
    client_id: str
    code_verifier: str
    redirect_uri: str
    expires_at: float


_pending_authorizations: dict[str, PendingAuthorization] = {}
_pending_lock = Lock()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _validate_client_id(client_id: str) -> str:
    cleaned = client_id.strip()
    try:
        parsed = UUID(cleaned)
    except (ValueError, AttributeError):
        raise ValueError("Enter a Microsoft Application (client) ID") from None
    if str(parsed) != cleaned.lower():
        raise ValueError("Enter a Microsoft Application (client) ID")
    return str(parsed)


def create_authorization_url(
    user_id: int,
    client_id: str,
    redirect_uri: str,
    login_hint: str | None = None,
) -> tuple[str, datetime]:
    cleaned_client_id = _validate_client_id(client_id)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _base64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = f"microsoft.{secrets.token_urlsafe(32)}"
    expires_at = time.time() + AUTHORIZATION_TTL_SECONDS
    pending = PendingAuthorization(
        user_id=user_id,
        client_id=cleaned_client_id,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        expires_at=expires_at,
    )
    with _pending_lock:
        now = time.time()
        expired = [key for key, value in _pending_authorizations.items() if value.expires_at <= now]
        for key in expired:
            _pending_authorizations.pop(key, None)
        _pending_authorizations[state] = pending

    parameters = {
        "client_id": cleaned_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": MICROSOFT_SCOPES,
        "prompt": "select_account",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        parameters["login_hint"] = login_hint
    return (
        f"{MICROSOFT_AUTHORIZATION_URL}?{urlencode(parameters)}",
        datetime.fromtimestamp(expires_at, tz=timezone.utc),
    )


def consume_authorization(state: str) -> PendingAuthorization:
    with _pending_lock:
        pending = _pending_authorizations.pop(state, None)
    if pending is None or pending.expires_at <= time.time():
        raise OutlookAuthorizationError("This Microsoft connection request expired. Start again.")
    return pending


def _response_json(response: httpx.Response, message: str) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.is_error:
        error_code = payload.get("error") if isinstance(payload, dict) else None
        if response.status_code == 401 or error_code in {
            "invalid_grant",
            "invalid_client",
            "unauthorized_client",
            "interaction_required",
        }:
            raise OutlookAuthorizationError("Microsoft authorization is no longer valid")
        raise OutlookProviderError(message)
    if not isinstance(payload, dict):
        raise OutlookProviderError(message)
    return payload


def exchange_authorization_code(pending: PendingAuthorization, code: str) -> dict:
    try:
        response = httpx.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": pending.client_id,
                "code": code,
                "code_verifier": pending.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": pending.redirect_uri,
                "scope": MICROSOFT_SCOPES,
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise OutlookProviderError("Could not reach Microsoft authorization") from exc
    payload = _response_json(response, "Microsoft could not complete authorization")
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        raise OutlookProviderError("Microsoft did not return an access token")
    return {
        "client_id": pending.client_id,
        "access_token": access_token,
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", MICROSOFT_SCOPES),
        "token_type": payload.get("token_type", "Bearer"),
    }


def fetch_profile_email(access_token: str) -> str:
    try:
        response = httpx.get(
            f"{MICROSOFT_GRAPH_URL}/me",
            params={"$select": "mail,userPrincipalName"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise OutlookProviderError("Could not read the Microsoft account profile") from exc
    payload = _response_json(response, "Could not read the Microsoft account profile")
    email_address = payload.get("mail") or payload.get("userPrincipalName")
    if not isinstance(email_address, str):
        raise OutlookProviderError("Microsoft did not return an account email")
    return email_address


def _refresh_access_token(tokens: dict) -> dict:
    client_id = tokens.get("client_id")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(client_id, str) or not isinstance(refresh_token, str):
        raise OutlookAuthorizationError("Reconnect Microsoft Outlook to continue syncing")
    try:
        response = httpx.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": MICROSOFT_SCOPES,
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise OutlookProviderError("Could not refresh Microsoft authorization") from exc
    payload = _response_json(response, "Could not refresh Microsoft authorization")
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        raise OutlookAuthorizationError("Reconnect Microsoft Outlook to continue syncing")
    updated = dict(tokens)
    updated.update(
        access_token=access_token,
        refresh_token=payload.get("refresh_token", refresh_token),
        expires_at=time.time() + int(payload.get("expires_in", 3600)),
        scope=payload.get("scope", updated.get("scope", MICROSOFT_SCOPES)),
        token_type=payload.get("token_type", updated.get("token_type", "Bearer")),
    )
    return updated


def ensure_access_token(tokens: dict, store: DesktopJsonSecretStore) -> tuple[str, dict]:
    access_token = tokens.get("access_token")
    expires_at = float(tokens.get("expires_at", 0))
    if isinstance(access_token, str) and expires_at > time.time() + 60:
        return access_token, tokens
    updated = _refresh_access_token(tokens)
    store.save(updated)
    return str(updated["access_token"]), updated


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def list_recent_metadata(
    access_token: str,
    max_results: int = 25,
) -> list[EmailMessageMetadata]:
    try:
        response = httpx.get(
            f"{MICROSOFT_GRAPH_URL}/me/mailFolders/inbox/messages",
            params={
                "$select": "id,subject,from,receivedDateTime",
                "$top": max_results,
                "$orderby": "receivedDateTime desc",
            },
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise OutlookProviderError("Could not reach Microsoft Outlook") from exc
    payload = _response_json(response, "Could not sync Microsoft Outlook")
    messages: list[EmailMessageMetadata] = []
    message_items = payload.get("value", [])
    if not isinstance(message_items, list):
        raise OutlookProviderError("Microsoft returned an invalid message list")
    for item in message_items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        from_value = item.get("from")
        sender = from_value.get("emailAddress", {}) if isinstance(from_value, dict) else {}
        if not isinstance(sender, dict):
            sender = {}
        sender_name = str(sender.get("name", "")).strip()
        sender_address = str(sender.get("address", "")).strip()
        sender_label = (
            f"{sender_name} <{sender_address}>"
            if sender_name and sender_address
            else sender_address or sender_name
        )
        messages.append(
            EmailMessageMetadata(
                message_id=str(item["id"]),
                subject=str(item.get("subject") or ""),
                sender=sender_label,
                received_at=_parse_datetime(item.get("receivedDateTime")),
            )
        )
    return messages
