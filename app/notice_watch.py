"""Deterministic, evidence-linked comparison of saved notice versions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from app.schemas import (
    NoticeChangeItem,
    NoticeVersionComparisonRequest,
    NoticeVersionComparisonResponse,
    StructuredNoticeExtraction,
)


@dataclass(frozen=True)
class _Rule:
    label: str
    values: Dict[str, str]
    quote: Optional[str]
    page_number: Optional[int]


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _optional(value: Optional[str]) -> str:
    return (value or "").strip()


def _deadline_rules(
    extraction: StructuredNoticeExtraction, grounded_ids: set[str]
) -> Dict[str, _Rule]:
    result: Dict[str, _Rule] = {}
    seen: Dict[str, int] = {}
    for index, item in enumerate(extraction.deadlines, start=1):
        if f"DEADLINE-{index}" not in grounded_ids:
            continue
        identity = _key(item.title)
        occurrence = seen.get(identity, 0)
        seen[identity] = occurrence + 1
        result[f"{identity}::{occurrence}"] = _Rule(
            label=item.title,
            values={
                "Date": item.iso_date or item.date_str,
                "Required action": item.action_required,
                "Urgency": item.urgency,
            },
            quote=item.verbatim_quote,
            page_number=item.page_number,
        )
    return result


def _eligibility_rules(
    extraction: StructuredNoticeExtraction, grounded_ids: set[str]
) -> Dict[str, _Rule]:
    result: Dict[str, _Rule] = {}
    for index, item in enumerate(extraction.eligibility_criteria, start=1):
        if f"ELIGIBILITY-{index}" not in grounded_ids:
            continue
        label = item.criterion_name
        category = _optional(item.applicable_category) or "ALL"
        result[f"{_key(label)}::{_key(category)}"] = _Rule(
            label=f"{label} ({category})",
            values={
                "Condition": item.condition,
                "Threshold": item.threshold_value,
            },
            quote=item.verbatim_quote,
            page_number=item.page_number,
        )
    return result


def _document_rules(
    extraction: StructuredNoticeExtraction, grounded_ids: set[str]
) -> Dict[str, _Rule]:
    result: Dict[str, _Rule] = {}
    for index, item in enumerate(extraction.required_documents, start=1):
        if f"DOC-{index}" not in grounded_ids:
            continue
        result[_key(item.document_name)] = _Rule(
            label=item.document_name,
            values={
                "Issuing authority": _optional(item.issuing_authority),
                "Validity": _optional(item.validity_rule),
                "Mandatory": "Yes" if item.is_mandatory else "No",
            },
            quote=item.verbatim_quote,
            page_number=item.page_number,
        )
    return result


def _fee_rules(
    extraction: StructuredNoticeExtraction, grounded_ids: set[str]
) -> Dict[str, _Rule]:
    fee = extraction.fee_details
    if fee is None or "FEE-1" not in grounded_ids:
        return {}
    values = {}
    if fee.amount_inr is not None:
        values["Amount (INR)"] = str(fee.amount_inr)
    if fee.payment_mode:
        values["Payment mode"] = fee.payment_mode
    if fee.exemption_categories:
        values["Exempt categories"] = ", ".join(sorted(fee.exemption_categories, key=str.casefold))
    if not values:
        return {}
    return {
        "application fee": _Rule(
            label="Application fee",
            values=values,
            quote=fee.verbatim_quote,
            page_number=fee.page_number,
        )
    }


def _same_value(left: str, right: str) -> bool:
    return _key(left) == _key(right)


def _summary(rule: _Rule) -> str:
    return "; ".join(f"{name}: {value}" for name, value in rule.values.items() if value)


def _change(
    section: str,
    change_type: str,
    label: str,
    field_name: Optional[str],
    before: Optional[str],
    after: Optional[str],
    older: Optional[_Rule],
    newer: Optional[_Rule],
) -> NoticeChangeItem:
    return NoticeChangeItem(
        section=section,
        change_type=change_type,
        label=label,
        field_name=field_name,
        before_value=before,
        after_value=after,
        before_quote=older.quote if older else None,
        after_quote=newer.quote if newer else None,
        before_page_number=older.page_number if older else None,
        after_page_number=newer.page_number if newer else None,
    )


def _compare_section(
    section: str,
    older_rules: Dict[str, _Rule],
    newer_rules: Dict[str, _Rule],
) -> Iterable[NoticeChangeItem]:
    for identity in older_rules.keys() - newer_rules.keys():
        rule = older_rules[identity]
        yield _change(
            section, "REMOVED", rule.label, None, _summary(rule), None, rule, None
        )

    for identity in newer_rules.keys() - older_rules.keys():
        rule = newer_rules[identity]
        yield _change(
            section, "ADDED", rule.label, None, None, _summary(rule), None, rule
        )

    for identity in older_rules.keys() & newer_rules.keys():
        old_rule = older_rules[identity]
        new_rule = newer_rules[identity]
        for field_name in old_rule.values.keys() | new_rule.values.keys():
            before = old_rule.values.get(field_name, "")
            after = new_rule.values.get(field_name, "")
            if not _same_value(before, after):
                yield _change(
                    section,
                    "CHANGED",
                    new_rule.label,
                    field_name,
                    before or None,
                    after or None,
                    old_rule,
                    new_rule,
                )


def compare_notice_versions(
    request: NoticeVersionComparisonRequest,
) -> NoticeVersionComparisonResponse:
    """Compare requirements without an LLM and retain both versions' evidence."""
    older_ids = set(request.older.grounded_item_ids)
    newer_ids = set(request.newer.grounded_item_ids)
    sections = (
        (
            "DEADLINE",
            _deadline_rules(request.older.extraction, older_ids),
            _deadline_rules(request.newer.extraction, newer_ids),
        ),
        (
            "ELIGIBILITY",
            _eligibility_rules(request.older.extraction, older_ids),
            _eligibility_rules(request.newer.extraction, newer_ids),
        ),
        (
            "DOCUMENT",
            _document_rules(request.older.extraction, older_ids),
            _document_rules(request.newer.extraction, newer_ids),
        ),
        (
            "FEE",
            _fee_rules(request.older.extraction, older_ids),
            _fee_rules(request.newer.extraction, newer_ids),
        ),
    )
    changes = []
    for section, older_rules, newer_rules in sections:
        changes.extend(_compare_section(section, older_rules, newer_rules))
    changes.sort(
        key=lambda item: (
            item.section,
            item.label.casefold(),
            item.field_name or "",
            item.change_type,
        )
    )
    return NoticeVersionComparisonResponse(
        older_version_id=request.older.version_id,
        newer_version_id=request.newer.version_id,
        total_changes=len(changes),
        changes=changes,
    )
