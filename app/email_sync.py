"""Shared metadata matching for local email providers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.models import ApplicationStatus, InternshipApplication


@dataclass(frozen=True)
class EmailMessageMetadata:
    message_id: str
    subject: str
    sender: str
    received_at: datetime | None


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
    messages: list[EmailMessageMetadata],
    applications: list[InternshipApplication],
) -> list[dict]:
    """Return forward-only suggestions; callers decide whether to apply them."""
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
