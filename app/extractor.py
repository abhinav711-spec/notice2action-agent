"""Conservative, evidence-first extraction rules; no external model is used."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from app.schemas import (
    DeadlineItem,
    EligibilityCriteriaItem,
    FeeDetails,
    NoticeMetadata,
    PageIndexedText,
    RequiredDocumentItem,
    StructuredNoticeExtraction,
)
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
)
_DATE = re.compile(
    rf"\b(?:\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}|\d{{1,2}}\s+(?:{_MONTHS})\.?,?\s+\d{{4}})\b",
    re.I,
)
_DOCUMENTS = (
    ("Bonafide Student Certificate", re.compile(r"bonafide(?:\s+student)?\s+certificate", re.I)),
    ("Income Certificate", re.compile(r"income\s+certificate", re.I)),
    ("Category Certificate", re.compile(r"(?:category|caste)\s+certificate|OBC-NCL\s+certificate", re.I)),
    ("Academic Marksheet", re.compile(r"(?:marksheet|mark\s*sheet|academic transcript|grade card)s?", re.I)),
    ("Bank Account Proof", re.compile(r"bank\s+(?:account\s+)?(?:passbook|statement|proof)", re.I)),
    ("Identity Proof", re.compile(r"(?:Aadhaar|identity)\s+(?:card|proof)", re.I)),
)


def _sentences(text: str):
    for line in text.splitlines():
        value = line.strip()
        if value:
            yield value


def _date_iso(date_text: str) -> Optional[str]:
    formats = ("%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y")
    normalized = date_text.replace(",", "").replace(".", " ").strip()
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).date().isoformat()
        except ValueError:
            continue
    for fmt in ("%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _first_match(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, re.I | re.M)
    return match.group(1).strip(" \t:,-") if match else None


def _metadata(pages: List[PageIndexedText]) -> NoticeMetadata:
    first_page = pages[0].text_content if pages else ""
    nonempty_lines = [line.strip() for line in first_page.splitlines() if line.strip()]
    title = next(
        (
            line[:160]
            for line in nonempty_lines
            if re.search(r"notice|notification|circular|scheme|scholarship|grant|fellowship", line, re.I)
        ),
        nonempty_lines[0][:160] if nonempty_lines else "Untitled notice",
    )
    organization = _first_match(r"(?:issued by|issuing authority)\s*:\s*([^\n]{2,160})", first_page)
    if not organization:
        organization = next(
            (
                line[:160]
                for line in nonempty_lines[:8]
                if re.search(r"ministry|council|university|department|authority|government|board", line, re.I)
                and not re.search(r"sample only|fictional", line, re.I)
            ),
            "Issuing authority not identified",
        )
    notice_number = _first_match(
        r"(?:notice|notification|memo|reference|ref)\s*(?:no\.?|number|#)\s*[:.-]?\s*([A-Z0-9./_-]+)",
        first_page,
    )
    issue_date_match = re.search(r"(?:date\s+of\s+issue|issued\s+on|dated)\s*[:,-]?\s*([^\n]{3,30})", first_page, re.I)
    return NoticeMetadata(
        title=title,
        issuing_organization=organization,
        notice_number=notice_number,
        issue_date=issue_date_match.group(1).strip() if issue_date_match else None,
    )


def _extract_deadlines(pages: List[PageIndexedText]) -> List[DeadlineItem]:
    results = []
    seen = set()
    keywords = re.compile(
        r"deadline|last date|closing date|closes on|close on|submit(?:\s+\w+){0,4}\s+by|submission by|"
        r"verification.{0,30}by|correction.{0,30}until|grievance.{0,30}until|due date",
        re.I,
    )
    for page in pages:
        for sentence in _sentences(page.text_content):
            date_match = _DATE.search(sentence)
            if not date_match or not keywords.search(sentence):
                continue
            key = re.sub(r"\W+", "", sentence.casefold())
            if key in seen:
                continue
            seen.add(key)
            lower = sentence.casefold()
            if "correction" in lower or "grievance" in lower:
                title, urgency = "Correction / grievance window", "MEDIUM"
            elif "verification" in lower:
                title, urgency = "Verification deadline", "HIGH"
            else:
                title, urgency = "Application deadline", "CRITICAL"
            raw_date = date_match.group(0)
            results.append(
                DeadlineItem(
                    title=title,
                    date_str=raw_date,
                    iso_date=_date_iso(raw_date),
                    verbatim_quote=sentence,
                    page_number=page.page_number,
                    urgency=urgency,
                    action_required=f"Complete the required submission before {raw_date}.",
                )
            )
    return results


def _extract_criteria(pages: List[PageIndexedText]) -> List[EligibilityCriteriaItem]:
    results = []
    seen = set()
    rules = (
        (
            re.compile(r"(?:minimum|at\s+least|not\s+less\s+than)[^\n]{0,100}(?:CGPA|GPA)[^\n]{0,50}", re.I),
            "Minimum CGPA",
            re.compile(r"(?:CGPA|GPA)\s*(?:of|is|:)?\s*(\d{1,2}(?:\.\d+)?)", re.I),
            ">=",
        ),
        (
            re.compile(r"(?:annual|family|household)\s+(?:family\s+)?income[^\n]{0,150}", re.I),
            "Annual household income ceiling",
            re.compile(r"(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?)?", re.I),
            "<=",
        ),
        (
            re.compile(r"(?:minimum|at\s+least|not\s+less\s+than)[^\n]{0,50}percentage[^\n]{0,35}", re.I),
            "Minimum percentage",
            re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%", re.I),
            ">=",
        ),
    )
    for page in pages:
        for pattern, name, value_pattern, operator in rules:
            for match in pattern.finditer(page.text_content):
                quote = match.group(0).strip()
                value_match = value_pattern.search(quote)
                if not value_match:
                    continue
                raw_value = value_match.group(1).replace(",", "")
                unit = value_match.group(2) if value_match.lastindex and value_match.lastindex > 1 else None
                threshold = f"{raw_value} {unit}".strip() if unit else raw_value
                identity = (name, threshold.casefold())
                if identity in seen:
                    continue
                seen.add(identity)
                results.append(
                    EligibilityCriteriaItem(
                        criterion_name=name,
                        condition=operator,
                        threshold_value=threshold,
                        applicable_category="ALL",
                        verbatim_quote=quote,
                        page_number=page.page_number,
                    )
                )
    return results


def _extract_documents(pages: List[PageIndexedText]) -> List[RequiredDocumentItem]:
    results = []
    seen = set()
    for page in pages:
        for sentence in _sentences(page.text_content):
            for name, pattern in _DOCUMENTS:
                match = pattern.search(sentence)
                if not match:
                    continue
                identity = name.casefold()
                if identity in seen:
                    continue
                seen.add(identity)
                results.append(
                    RequiredDocumentItem(
                        document_name=name,
                        validity_rule=(
                            sentence[match.start():].strip()
                            if re.search(r"valid|issued|current|within|before|after", sentence[match.end():], re.I)
                            else None
                        ),
                        is_mandatory=bool(re.search(r"must|required|mandatory|shall|upload|submit", sentence, re.I)),
                        verbatim_quote=sentence,
                        page_number=page.page_number,
                    )
                )
    return results


def run_fallback_extractor(pages: List[PageIndexedText]) -> StructuredNoticeExtraction:
    """Extract only requirements with literal supporting text on a source page."""
    full_text = "\n".join(page.text_content for page in pages)
    metadata = _metadata(pages)
    deadlines = _extract_deadlines(pages)
    criteria = _extract_criteria(pages)
    documents = _extract_documents(pages)
    fee_details = None
    for page in pages:
        for sentence in _sentences(page.text_content):
            fee_match = re.search(
                r"(?:application|registration)\s+fee[^\n]{0,100}",
                sentence,
                re.I,
            )
            if not fee_match or not re.search(
                r"no\s+fee|free\s+of\s+charge|zero\s+fee|not\s+payable|(?:Rs\.?|INR|₹)\s*[\d,]+",
                sentence,
                re.I,
            ):
                continue
            quote = fee_match.group(0).strip()
            amount_match = re.search(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)", quote, re.I)
            free = bool(re.search(r"no\s+fee|free\s+of\s+charge|zero\s+fee|not\s+payable", quote, re.I))
            fee_details = FeeDetails(
                amount_inr=0 if free else float(amount_match.group(1).replace(",", "")) if amount_match else None,
                payment_mode="No fee" if free else None,
                verbatim_quote=quote,
                page_number=page.page_number,
            )
            break
        if fee_details:
            break
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", full_text)
    phone_match = re.search(r"\b(?:\+?91[-\s]?)?[6-9]\d{9}\b", full_text)
    portal_match = re.search(r"https?://[^\s<>]+", full_text, re.I)
    return StructuredNoticeExtraction(
        metadata=metadata,
        deadlines=deadlines,
        eligibility_criteria=criteria,
        required_documents=documents,
        fee_details=fee_details,
        contact_email=email_match.group(0) if email_match else None,
        contact_phone=phone_match.group(0) if phone_match else None,
        portal_url=portal_match.group(0).rstrip(".,)") if portal_match else None,
        official_summary=(
            f'The document titled "{metadata.title}" is issued by '
            f"{metadata.issuing_organization}. Requirements shown here were extracted "
            "only when matching text could be quoted from a page."
        ),
    )
