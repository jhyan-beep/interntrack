"""Create a portable iCalendar snapshot without calendar-provider credentials."""

from collections.abc import Iterable
from datetime import date, datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from app.models import InternshipApplication


def _escape_text(value: str) -> str:
    # Newlines are data, never new calendar properties or components.
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(
        char for char in value if char in "\t\n" or (ord(char) >= 32 and ord(char) != 127)
    )
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold_line(line: str) -> str:
    """RFC 5545 lines fit 75 UTF-8 octets, including the continuation space."""
    segments = []
    segment = ""
    size = 0
    for char in line:
        char_size = len(char.encode("utf-8"))
        if size + char_size > 75:
            segments.append(segment)
            segment, size = " ", 1
        segment += char
        size += char_size
    segments.append(segment)
    return "\r\n".join(segments)


def _utc(value: datetime) -> datetime:
    # SQLite returns naive timestamps; the application stores those in UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event(application: InternshipApplication, kind: str, day: date, summary: str) -> list[str]:
    identity = (
        f"interntrack:{application.user_id}:{application.id}:"
        f"{_utc(application.created_at).isoformat()}:{kind}"
    )
    updated = _utc(application.updated_at).strftime("%Y%m%dT%H%M%SZ")
    return [
        "BEGIN:VEVENT",
        f"UID:{uuid5(NAMESPACE_URL, identity)}@interntrack.local",
        f"DTSTAMP:{updated}",
        f"LAST-MODIFIED:{updated}",
        f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
        "DURATION:P1D",
        f"SUMMARY:{_escape_text(summary)}",
        f"DESCRIPTION:{_escape_text(f'{application.company} · {application.role}')}",
        "CLASS:PRIVATE",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def build_calendar(applications: Iterable[InternshipApplication]) -> str:
    """Export all dated deadlines/actions from the caller's selected records."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//InternTrack//Application Calendar//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:InternTrack",
    ]
    for application in applications:
        if application.deadline is not None:
            lines.extend(_event(
                application, "deadline", application.deadline,
                f"Deadline: {application.company} · {application.role}",
            ))
        if application.next_step_date is not None and application.next_step:
            lines.extend(_event(
                application, "next-step", application.next_step_date,
                f"{application.next_step} · {application.company}",
            ))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_line(line) for line in lines) + "\r\n"

