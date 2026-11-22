"""Local five-stage PDF-to-action pipeline with source-linked claims."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import List

import pymupdf

from app.actions import (
    generate_action_items,
    generate_bilingual_summary,
    generate_clarification_email,
    generate_rfc5545_ics,
)
from app.extractor import run_fallback_extractor
from app.schemas import (
    Notice2ActionResponse,
    PageIndexedText,
    PipelineTelemetry,
    SecurityShieldReport,
    StudentProfile,
)
from app.security import MAX_ALLOWED_PAGES, sanitize_text, scan_for_prompt_injection, validate_pdf_bytes
from app.verifier import audit_extraction_grounding, audit_student_cross_conflicts


class Notice2ActionPipeline:
    """Run isolated, deterministic analysis stages against an uploaded PDF."""

    def run_pipeline(
        self, pdf_bytes: bytes, student_profile: StudentProfile
    ) -> Notice2ActionResponse:
        started = time.perf_counter()
        latencies = {}

        stage = time.perf_counter()
        valid, reason = validate_pdf_bytes(pdf_bytes)
        if not valid:
            raise ValueError(f"Document rejected: {reason}")
        try:
            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as error:
            raise ValueError("The uploaded file could not be opened as a PDF.") from error
        try:
            if not len(document):
                raise ValueError("The PDF contains no pages.")
            if len(document) > MAX_ALLOWED_PAGES:
                raise ValueError(f"The PDF exceeds the {MAX_ALLOWED_PAGES}-page limit.")
            pages: List[PageIndexedText] = []
            sanitized_count = 0
            for index, page in enumerate(document, start=1):
                clean_text, count = sanitize_text(page.get_text("text") or "")
                sanitized_count += count
                pages.append(
                    PageIndexedText(
                        page_number=index,
                        text_content=clean_text,
                        char_count=len(clean_text),
                    )
                )
        finally:
            document.close()
        if not any(page.text_content.strip() for page in pages):
            raise ValueError("The PDF contains no selectable text. OCR is not available in this build.")
        combined_text = "\n".join(page.text_content for page in pages)
        injection_detected, threat, snippets = scan_for_prompt_injection(combined_text)
        security = SecurityShieldReport(
            magic_bytes_valid=True,
            file_size_bytes=len(pdf_bytes),
            total_pages=len(pages),
            sanitization_applied=sanitized_count > 0,
            sanitized_chars_count=sanitized_count,
            prompt_injection_detected=injection_detected,
            injection_threat_level=threat,
            quarantined_snippets=snippets,
            security_verdict="SUSPICIOUS" if injection_detected else "CLEAN",
        )
        latencies["step_1_ingestion_and_security_ms"] = round(
            (time.perf_counter() - stage) * 1000, 2
        )

        stage = time.perf_counter()
        extraction = run_fallback_extractor(pages)
        latencies["step_2_structured_extraction_ms"] = round(
            (time.perf_counter() - stage) * 1000, 2
        )

        stage = time.perf_counter()
        grounding = audit_extraction_grounding(extraction, pages)
        grounded_ids = {
            item.item_id for item in grounding.audited_items if item.is_verified
        }
        latencies["step_3_grounding_audit_ms"] = round(
            (time.perf_counter() - stage) * 1000, 2
        )

        stage = time.perf_counter()
        audit = audit_student_cross_conflicts(extraction, student_profile, grounded_ids)
        latencies["step_4_cross_conflict_audit_ms"] = round(
            (time.perf_counter() - stage) * 1000, 2
        )

        stage = time.perf_counter()
        actions = generate_action_items(extraction, audit, student_profile)
        calendar = generate_rfc5545_ics(extraction, student_profile.name)
        email = generate_clarification_email(extraction, audit, student_profile)
        summaries = generate_bilingual_summary(extraction, audit, student_profile)
        latencies["step_5_action_executor_ms"] = round(
            (time.perf_counter() - stage) * 1000, 2
        )

        return Notice2ActionResponse(
            notice_id=f"N2A-{uuid.uuid4().hex[:8].upper()}",
            telemetry=PipelineTelemetry(
                step_latencies_ms=latencies,
                total_latency_ms=round((time.perf_counter() - started) * 1000, 2),
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            security_shield=security,
            extraction=extraction,
            grounding_report=grounding,
            cross_audit=audit,
            action_items=actions,
            bilingual_summary=summaries,
            calendar_ics=calendar,
            clarification_email_draft=email,
            raw_document_pages=len(pages),
        )
