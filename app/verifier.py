"""Deterministic source-quote verification and profile conflict checks."""

from __future__ import annotations

import difflib
import re
from typing import Dict, List, Optional, Tuple

from app.schemas import (
    ConflictAuditItem,
    CrossAuditResult,
    GroundingAuditItem,
    GroundingReport,
    PageIndexedText,
    StudentProfile,
    StructuredNoticeExtraction,
)


def normalize_text_for_matching(text: str) -> str:
    text = (text or "").replace("“", '"').replace("”", '"').replace("’", "'")
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def verify_quote_against_page(
    quote: str, page_number: int, pages_dict: Dict[int, str]
) -> Tuple[bool, float, str, Optional[str]]:
    normalized_quote = normalize_text_for_matching(quote)
    if not normalized_quote:
        return False, 0.0, "FAILED", "No source quote was provided."
    page_text = pages_dict.get(page_number)
    if page_text is None:
        return False, 0.0, "FAILED", f"Page {page_number} does not exist in this document."
    normalized_page = normalize_text_for_matching(page_text)
    if normalized_quote in normalized_page:
        return True, 1.0, "EXACT", None
    ratio = difflib.SequenceMatcher(None, normalized_quote, normalized_page).ratio()
    if ratio >= 0.92:
        return True, round(ratio, 3), "FUZZY_HIGH", None
    return (
        False,
        round(ratio, 3),
        "FUZZY_PARTIAL" if ratio >= 0.65 else "FAILED",
        "Quote did not match its cited source page; review the original document.",
    )


def audit_extraction_grounding(
    extraction: StructuredNoticeExtraction,
    pages: List[PageIndexedText],
) -> GroundingReport:
    page_map = {page.page_number: page.text_content for page in pages}
    claims = []
    for kind, prefix, items, describe in (
        ("DEADLINE", "DEADLINE", extraction.deadlines, lambda item: f"{item.title}: {item.date_str}"),
        ("ELIGIBILITY", "ELIGIBILITY", extraction.eligibility_criteria, lambda item: f"{item.criterion_name}: {item.condition} {item.threshold_value}"),
        ("DOCUMENT", "DOC", extraction.required_documents, lambda item: f"{item.document_name} ({'mandatory' if item.is_mandatory else 'optional'})"),
    ):
        for index, item in enumerate(items, start=1):
            claims.append((f"{prefix}-{index}", kind, describe(item), item.verbatim_quote, item.page_number))
    fee = extraction.fee_details
    if fee and fee.verbatim_quote and fee.page_number:
        claims.append(("FEE-1", "FEE", f"Application fee: {fee.amount_inr}", fee.verbatim_quote, fee.page_number))
    audited = []
    for item_id, kind, claim, quote, page_number in claims:
        verified, score, match_type, reason = verify_quote_against_page(quote, page_number, page_map)
        audited.append(
            GroundingAuditItem(
                item_id=item_id,
                item_type=kind,
                claim_text=claim,
                verbatim_quote=quote,
                page_number=page_number,
                is_verified=verified,
                match_score=score,
                match_type=match_type,
                quarantined=not verified,
                quarantine_reason=reason,
            )
        )
    count = len(audited)
    verified_count = sum(item.is_verified for item in audited)
    return GroundingReport(
        total_claims=count,
        verified_claims=verified_count,
        quarantined_claims=count - verified_count,
        grounding_accuracy_score=round(verified_count / count * 100, 1) if count else 100.0,
        audited_items=audited,
    )


def _numeric_value(value: str) -> Optional[float]:
    match = re.search(r"[\d,]+(?:\.\d+)?", value or "")
    if not match:
        return None
    number = float(match.group(0).replace(",", ""))
    if re.search(r"\b(lakh|lac)s?\b", value, re.I):
        number *= 100_000
    return number


def audit_student_cross_conflicts(
    extraction: StructuredNoticeExtraction,
    student: StudentProfile,
    grounded_item_ids: Optional[set[str]] = None,
) -> CrossAuditResult:
    grounded = grounded_item_ids
    conflicts: List[ConflictAuditItem] = []
    checked = 0
    for index, criterion in enumerate(extraction.eligibility_criteria, start=1):
        if grounded is not None and f"ELIGIBILITY-{index}" not in grounded:
            continue
        name = criterion.criterion_name.casefold()
        actual = student.cgpa if "cgpa" in name or "gpa" in name else (
            student.percentage if "percentage" in name else
            student.annual_income_inr if "income" in name else None
        )
        if actual is None:
            continue
        threshold = _numeric_value(criterion.threshold_value)
        if threshold is None:
            continue
        checked += 1
        below_minimum = criterion.condition.strip() in {">=", ">", "min"} and actual < threshold
        above_maximum = criterion.condition.strip() in {"<=", "<", "max"} and actual > threshold
        if not (below_minimum or above_maximum):
            continue
        conflicts.append(
            ConflictAuditItem(
                field=criterion.criterion_name,
                rule_text=f"{criterion.condition} {criterion.threshold_value}",
                student_value=str(actual),
                threshold_value=criterion.threshold_value,
                has_conflict=True,
                severity="CRITICAL",
                rejection_risk="The profile value does not meet the quoted eligibility threshold.",
                evidence_quote=criterion.verbatim_quote,
                recommended_remedy="Confirm the criterion and any category-specific exceptions with the issuing authority.",
            )
        )
    verified = grounded if grounded is not None else set()
    for index, document in enumerate(extraction.required_documents, start=1):
        if grounded is not None and f"DOC-{index}" not in verified:
            continue
        if not document.is_mandatory:
            continue
        present = any(
            document.document_name.casefold() in available.casefold()
            or available.casefold() in document.document_name.casefold()
            for available in student.available_documents
        )
        if present:
            continue
        conflicts.append(
            ConflictAuditItem(
                field=f"Missing document: {document.document_name}",
                rule_text="Required document",
                student_value="Not listed as available",
                threshold_value="Provide the document",
                has_conflict=True,
                severity="MEDIUM",
                rejection_risk="The notice lists this document as mandatory.",
                evidence_quote=document.verbatim_quote,
                recommended_remedy="Request the document from its issuing authority and verify the notice's format requirements.",
            )
        )
    critical_count = sum(conflict.severity == "CRITICAL" for conflict in conflicts)
    status = "INELIGIBLE" if critical_count else "CONDITIONALLY ELIGIBLE" if conflicts else "ELIGIBLE"
    risk = min(100, critical_count * 35 + (len(conflicts) - critical_count) * 12)
    if not checked and not extraction.required_documents:
        summary = "No grounded profile criteria or mandatory documents could be compared; verify requirements against the notice."
        status = "CONDITIONALLY ELIGIBLE"
    elif conflicts:
        summary = f"Found {len(conflicts)} potential conflict(s). Review each quoted rule with the issuing authority before applying."
    else:
        summary = "No conflicts were found among the grounded criteria that could be compared with the supplied profile."
    return CrossAuditResult(
        eligibility_status=status,
        risk_score=risk,
        summary=summary,
        conflicts=conflicts,
        eligible_reasons=["No conflict found for the grounded criteria that could be compared."] if not conflicts else [],
    )
