"""Privacy-first Gmail OAuth and metadata-based status suggestions."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from urllib.parse import urlencode

import httpx

from app.desktop_secrets import DesktopJsonSecretStore
from app.models import ApplicationStatus, InternshipApplication


GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1"
GMAIL_METADATA_SCOPE = "https://www.googleapis.com/auth/gmail.metadata"
AUTHORIZATION_TTL_SECONDS = 600


class GmailProviderError(RuntimeError):
    pass


class GmailAuthorizationError(GmailProviderError):
    pass


@dataclass(frozen=True)
class PendingAuthorization:
    user_id: int
    client_id: str
    code_verifier: str
    redirect_uri: str
    expires_at: float


@dataclass(frozen=True)
class GmailMessageMetadata:
    message_id: str
    subject: str
    sender: str
    received_at: datetime | None


_pending_authorizations: dict[str, PendingAuthorization] = {}
_pending_lock = Lock()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _validate_client_id(client_id: str) -> str:
    cleaned = client_id.strip()
    if len(cleaned) > 300 or not cleaned.endswith(".apps.googleusercontent.com"):
        raise ValueError("Enter a Google Desktop OAuth client ID")
    return cleaned


def create_authorization_url(
    user_id: int,
    client_id: str,
    redirect_uri: str,
    login_hint: str | None = None,
) -> tuple[str, datetime]:
    cleaned_client_id = _validate_client_id(client_id)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _base64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(32)
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
        "scope": GMAIL_METADATA_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        parameters["login_hint"] = login_hint
    return (
        f"{GOOGLE_AUTHORIZATION_URL}?{urlencode(parameters)}",
        datetime.fromtimestamp(expires_at, tz=timezone.utc),
    )


def consume_authorization(state: str) -> PendingAuthorization:
    with _pending_lock:
        pending = _pending_authorizations.pop(state, None)
    if pending is None or pending.expires_at <= time.time():
        raise GmailAuthorizationError("This Gmail connection request expired. Start again.")
    return pending


def _response_json(response: httpx.Response, message: str) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.is_error:
        error_code = payload.get("error") if isinstance(payload, dict) else None
        if response.status_code == 401 or (
            response.status_code == 400
            and error_code in {"invalid_grant", "invalid_client", "unauthorized_client"}
        ):
            raise GmailAuthorizationError("Gmail authorization is no longer valid")
        raise GmailProviderError(message)
    if not isinstance(payload, dict):
        raise GmailProviderError(message)
    return payload


def exchange_authorization_code(
    pending: PendingAuthorization,
    code: str,
) -> dict:
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": pending.client_id,
                "code": code,
                "code_verifier": pending.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": pending.redirect_uri,
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise GmailProviderError("Could not reach Google authorization") from exc
    payload = _response_json(response, "Google could not complete authorization")
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        raise GmailProviderError("Google did not return an access token")
    return {
        "client_id": pending.client_id,
        "access_token": access_token,
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", GMAIL_METADATA_SCOPE),
        "token_type": payload.get("token_type", "Bearer"),
    }


def fetch_profile_email(access_token: str) -> str:
    try:
        response = httpx.get(
            f"{GMAIL_API_URL}/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise GmailProviderError("Could not read the Gmail account profile") from exc
    payload = _response_json(response, "Could not read the Gmail account profile")
    email_address = payload.get("emailAddress")
    if not isinstance(email_address, str):
        raise GmailProviderError("Google did not return an account email")
    return email_address


def _refresh_access_token(tokens: dict) -> dict:
    client_id = tokens.get("client_id")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(client_id, str) or not isinstance(refresh_token, str):
        raise GmailAuthorizationError("Reconnect Gmail to continue syncing")
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise GmailProviderError("Could not refresh Gmail authorization") from exc
    payload = _response_json(response, "Could not refresh Gmail authorization")
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        raise GmailAuthorizationError("Reconnect Gmail to continue syncing")
    updated = dict(tokens)
    updated.update(
        access_token=access_token,
        expires_at=time.time() + int(payload.get("expires_in", 3600)),
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


def revoke_tokens(tokens: dict) -> None:
    token = tokens.get("refresh_token") or tokens.get("access_token")
    if not isinstance(token, str):
        return
    try:
        httpx.post(GOOGLE_REVOKE_URL, data={"token": token}, timeout=10)
    except httpx.HTTPError:
        # Local deletion still disconnects InternTrack if Google is temporarily unavailable.
        return


def _header_value(message: dict, name: str) -> str:
    headers = message.get("payload", {}).get("headers", [])
    for header in headers:
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value", "")).strip()
    return ""


def _parse_message_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def list_recent_metadata(access_token: str, max_results: int = 25) -> list[GmailMessageMetadata]:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        with httpx.Client(timeout=20, headers=headers) as client:
            response = client.get(
                f"{GMAIL_API_URL}/users/me/messages",
                params={"maxResults": max_results, "labelIds": "INBOX"},
            )
            payload = _response_json(response, "Could not list Gmail messages")
            messages: list[GmailMessageMetadata] = []
            for item in payload.get("messages", []):
                message_id = item.get("id")
                if not isinstance(message_id, str):
                    continue
                detail_response = client.get(
                    f"{GMAIL_API_URL}/users/me/messages/{message_id}",
                    params=[
                        ("format", "metadata"),
                        ("metadataHeaders", "Subject"),
                        ("metadataHeaders", "From"),
                        ("metadataHeaders", "Date"),
                    ],
                )
                detail = _response_json(detail_response, "Could not read Gmail message metadata")
                messages.append(
                    GmailMessageMetadata(
                        message_id=message_id,
                        subject=_header_value(detail, "Subject"),
                        sender=_header_value(detail, "From"),
                        received_at=_parse_message_date(_header_value(detail, "Date")),
                    )
                )
            return messages
    except httpx.HTTPStatusError as exc:
        raise GmailProviderError("Could not sync Gmail") from exc
    except httpx.HTTPError as exc:
        raise GmailProviderError("Could not reach Gmail") from exc


_COMPANY_STOP_WORDS = {
    "inc",
    "llc",
    "corp",
    "corporation",
    "company",
    "co",
    "group",
    "systems",
    "solutions",
    "technology",
    "technologies",
}
_STATUS_PATTERNS: tuple[tuple[ApplicationStatus, tuple[str, ...]], ...] = (
    (
        ApplicationStatus.REJECTED,
        ("not moving forward", "not selected", "other candidates", "we regret", "unfortunately"),
    ),
    (
        ApplicationStatus.OFFER,
        ("offer letter", "job offer", "internship offer", "pleased to offer"),
    ),
    (
        ApplicationStatus.INTERVIEW,
        ("interview", "schedule a call", "next steps", "technical assessment", "coding assessment"),
    ),
    (
        ApplicationStatus.APPLIED,
        ("application received", "received your application", "application confirmation", "thank you for applying"),
    ),
)
_ALLOWED_TRANSITIONS = {
    ApplicationStatus.SAVED: {
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.APPLIED: {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.INTERVIEW: {ApplicationStatus.OFFER, ApplicationStatus.REJECTED},
}


def _normalized_words(value: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", value.lower()) if word]


def _matches_company(company: str, message_text: str) -> bool:
    company_words = [
        word for word in _normalized_words(company) if word not in _COMPANY_STOP_WORDS
    ]
    if not company_words:
        return False
    message_words = set(_normalized_words(message_text))
    acronym = "".join(word[0] for word in company_words)
    return all(word in message_words for word in company_words) or (
        len(acronym) >= 2 and acronym in message_words
    )


def suggest_status_updates(
    messages: list[GmailMessageMetadata],
    applications: list[InternshipApplication],
) -> list[dict]:
    suggestions: list[dict] = []
    suggested_applications: set[int] = set()
    for message in messages:
        text = f"{message.subject} {message.sender}".lower()
        detected: tuple[ApplicationStatus, str] | None = None
        for next_status, phrases in _STATUS_PATTERNS:
            matched_phrase = next((phrase for phrase in phrases if phrase in text), None)
            if matched_phrase:
                detected = (next_status, matched_phrase)
                break
        if detected is None:
            continue

        next_status, matched_phrase = detected
        for application in applications:
            if application.id in suggested_applications:
                continue
            if next_status not in _ALLOWED_TRANSITIONS.get(application.status, set()):
                continue
            if not _matches_company(application.company, text):
                continue
            suggestions.append(
                {
                    "message_id": message.message_id,
                    "application_id": application.id,
                    "company": application.company,
                    "role": application.role,
                    "current_status": application.status,
                    "suggested_status": next_status,
                    "subject": message.subject or "(No subject)",
                    "sender": message.sender,
                    "received_at": message.received_at,
                    "reason": f'Email matched "{matched_phrase}" and {application.company}.',
                }
            )
            suggested_applications.add(application.id)
            break
    return suggestions
