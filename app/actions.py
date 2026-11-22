"""Reviewable, source-conscious action plans, calendar files, and briefings."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from app.schemas import (
    ActionItem,
    BilingualSummary,
    CrossAuditResult,
    StudentProfile,
    StructuredNoticeExtraction,
)


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def generate_action_items(
    extraction: StructuredNoticeExtraction,
    audit: CrossAuditResult,
    student: StudentProfile,
) -> List[ActionItem]:
    result: List[ActionItem] = []
    for index, conflict in enumerate(audit.conflicts, start=1):
        urgent = conflict.severity == "CRITICAL"
        result.append(
            ActionItem(
                id=f"ACT-{index:02d}",
                priority="P1 - IMMEDIATE" if urgent else "P2 - HIGH",
                action=f"Review {conflict.field}: {conflict.recommended_remedy}",
                deadline="Before submitting",
                assigned_to=student.name,
                category="CORRECTION" if urgent else "DOCUMENT_PROCUREMENT",
            )
        )
    for deadline in extraction.deadlines:
        priority = "P1 - IMMEDIATE" if deadline.urgency == "CRITICAL" else (
            "P2 - HIGH" if deadline.urgency == "HIGH" else "P3 - NORMAL"
        )
        result.append(
            ActionItem(
                id=f"ACT-{len(result) + 1:02d}",
                priority=priority,
                action=f"{deadline.title}: {deadline.action_required}",
                deadline=deadline.date_str,
                assigned_to=student.name,
                category="PORTAL_SUBMISSION",
            )
        )
    if not result:
        result.append(
            ActionItem(
                id="ACT-01",
                priority="P3 - NORMAL",
                action="Review the notice and confirm requirements with the issuing authority.",
                deadline="Before taking action",
                assigned_to=student.name,
                category="VERIFICATION",
            )
        )
    return result


def generate_rfc5545_ics(extraction: StructuredNoticeExtraction, student_name: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Notice2Action//Evidence Workspace//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_ics_escape(extraction.metadata.title[:50])} deadlines",
    ]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for deadline in extraction.deadlines:
        if not deadline.iso_date:
            continue
        try:
            event_date = datetime.strptime(deadline.iso_date, "%Y-%m-%d").strftime("%Y%m%d")
        except ValueError:
            continue
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uuid.uuid4()}@notice2action",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{event_date}",
                f"SUMMARY:{_ics_escape(deadline.title)}",
                f"DESCRIPTION:{_ics_escape(deadline.action_required)}\\nEvidence: {_ics_escape(deadline.verbatim_quote)}\\nPage: {deadline.page_number}\\nApplicant: {_ics_escape(student_name)}",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_ics_escape(deadline.title)} deadline tomorrow",
                "TRIGGER:-P1D",
                "END:VALARM",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def generate_clarification_email(
    extraction: StructuredNoticeExtraction,
    audit: CrossAuditResult,
    student: StudentProfile,
) -> str:
    recipient = extraction.contact_email or "[Official contact email from notice]"
    questions = [
        f"- {conflict.field}: {conflict.rejection_risk} Evidence: “{conflict.evidence_quote}”"
        for conflict in audit.conflicts
    ] or ["- Please confirm the current eligibility, document, and submission requirements."]
    return (
        f"To: {recipient}\n"
        f"Subject: Clarification request — {extraction.metadata.title}\n\n"
        f"Dear {extraction.metadata.issuing_organization},\n\n"
        f"I am reviewing the notice “{extraction.metadata.title}”"
        f"{f' (reference {extraction.metadata.notice_number})' if extraction.metadata.notice_number else ''}.\n"
        "Could you please clarify the following before I submit an application?\n\n"
        + "\n".join(questions)
        + f"\n\nThank you for your guidance.\n\n{student.name}\n{student.email}"
    )


def generate_bilingual_summary(
    extraction: StructuredNoticeExtraction,
    audit: CrossAuditResult,
    student: StudentProfile,
) -> BilingualSummary:
    deadlines = "\n".join(
        f"- {item.title}: {item.date_str} (page {item.page_number})"
        for item in extraction.deadlines
    ) or "- No deadline with a supporting date was identified."
    english = (
        f"Notice: {extraction.metadata.title}\n"
        f"Issuer: {extraction.metadata.issuing_organization}\n"
        f"Profile review: {audit.eligibility_status} — {audit.summary}\n\n"
        f"Important dates:\n{deadlines}\n\n"
        "Confirm each cited requirement against the original notice."
    )
    hinglish = (
        f"Notice: {extraction.metadata.title}\n"
        f"Issuing authority: {extraction.metadata.issuing_organization}\n"
        f"Aapki profile review: {audit.eligibility_status}. {audit.summary}\n\n"
        f"Important dates:\n{deadlines}\n\n"
        "Action lene se pehle original notice ke cited page par requirement confirm karein."
    )
    return BilingualSummary(english=english, hindi_hinglish=hinglish)
