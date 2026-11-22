"""Typed contracts for Notice2Action's deterministic analysis workflow."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class SecurityShieldReport(BaseModel):
    magic_bytes_valid: bool
    detected_mime_type: str = "application/pdf"
    file_size_bytes: int
    total_pages: int
    sanitization_applied: bool = False
    sanitized_chars_count: int = 0
    prompt_injection_detected: bool = False
    injection_threat_level: Literal["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "NONE"
    quarantined_snippets: List[str] = Field(default_factory=list)
    security_verdict: Literal["CLEAN", "SUSPICIOUS", "BLOCKED"] = "CLEAN"


class PageIndexedText(BaseModel):
    page_number: int
    text_content: str
    char_count: int


class DeadlineItem(BaseModel):
    title: str
    date_str: str
    iso_date: Optional[str] = None
    verbatim_quote: str
    page_number: int
    urgency: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "HIGH"
    action_required: str


class EligibilityCriteriaItem(BaseModel):
    criterion_name: str
    condition: str
    threshold_value: str
    applicable_category: Optional[str] = "ALL"
    verbatim_quote: str
    page_number: int


class RequiredDocumentItem(BaseModel):
    document_name: str
    issuing_authority: Optional[str] = None
    validity_rule: Optional[str] = None
    is_mandatory: bool = True
    verbatim_quote: str
    page_number: int


class FeeDetails(BaseModel):
    amount_inr: Optional[float] = None
    payment_mode: Optional[str] = None
    exemption_categories: List[str] = Field(default_factory=list)
    verbatim_quote: Optional[str] = None
    page_number: Optional[int] = None


class NoticeMetadata(BaseModel):
    title: str
    issuing_organization: str
    notice_number: Optional[str] = None
    issue_date: Optional[str] = None
    scheme_category: str = "Academic / public notice"


class StructuredNoticeExtraction(BaseModel):
    metadata: NoticeMetadata
    deadlines: List[DeadlineItem] = Field(default_factory=list)
    eligibility_criteria: List[EligibilityCriteriaItem] = Field(default_factory=list)
    required_documents: List[RequiredDocumentItem] = Field(default_factory=list)
    fee_details: Optional[FeeDetails] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    portal_url: Optional[str] = None
    official_summary: str


class GroundingAuditItem(BaseModel):
    item_id: str
    item_type: Literal["DEADLINE", "ELIGIBILITY", "DOCUMENT", "FEE"]
    claim_text: str
    verbatim_quote: str
    page_number: int
    is_verified: bool
    match_score: float
    match_type: Literal["EXACT", "FUZZY_HIGH", "FUZZY_PARTIAL", "FAILED"]
    quarantined: bool
    quarantine_reason: Optional[str] = None


class GroundingReport(BaseModel):
    total_claims: int
    verified_claims: int
    quarantined_claims: int
    grounding_accuracy_score: float
    audited_items: List[GroundingAuditItem] = Field(default_factory=list)


class StudentProfile(BaseModel):
    name: str = "Applicant"
    email: str = "applicant@example.edu"
    category: str = "GENERAL"
    annual_income_inr: Optional[float] = Field(default=None, ge=0)
    cgpa: Optional[float] = Field(default=None, ge=0, le=10)
    percentage: Optional[float] = Field(default=None, ge=0, le=100)
    degree: str = "Not provided"
    year_of_study: Optional[int] = None
    certificate_issue_date: Optional[str] = None
    available_documents: List[str] = Field(default_factory=list)


class ConflictAuditItem(BaseModel):
    field: str
    rule_text: str
    student_value: str
    threshold_value: str
    has_conflict: bool
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "INFO"]
    rejection_risk: str
    evidence_quote: str
    recommended_remedy: str


class CrossAuditResult(BaseModel):
    eligibility_status: Literal["ELIGIBLE", "CONDITIONALLY ELIGIBLE", "INELIGIBLE"]
    risk_score: int = Field(ge=0, le=100)
    summary: str
    conflicts: List[ConflictAuditItem] = Field(default_factory=list)
    eligible_reasons: List[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    id: str
    priority: Literal["P1 - IMMEDIATE", "P2 - HIGH", "P3 - NORMAL"]
    action: str
    deadline: str
    assigned_to: str
    category: Literal["DOCUMENT_PROCUREMENT", "CORRECTION", "PORTAL_SUBMISSION", "VERIFICATION"]
    status: Literal["PENDING", "IN_PROGRESS", "READY"] = "PENDING"


class BilingualSummary(BaseModel):
    english: str
    hindi_hinglish: str


class PipelineTelemetry(BaseModel):
    step_latencies_ms: Dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    extraction_engine: str = "Deterministic local rules"
    timestamp: str = ""


class Notice2ActionResponse(BaseModel):
    success: bool = True
    notice_id: str
    telemetry: PipelineTelemetry
    security_shield: SecurityShieldReport
    extraction: StructuredNoticeExtraction
    grounding_report: GroundingReport
    cross_audit: CrossAuditResult
    action_items: List[ActionItem]
    bilingual_summary: BilingualSummary
    calendar_ics: str
    clarification_email_draft: str
    raw_document_pages: int


class NoticeVersionSnapshot(BaseModel):
    version_id: str = Field(..., min_length=1, max_length=80)
    saved_at: str
    extraction: StructuredNoticeExtraction
    grounded_item_ids: List[str] = Field(default_factory=list)


class NoticeVersionComparisonRequest(BaseModel):
    older: NoticeVersionSnapshot
    newer: NoticeVersionSnapshot


class NoticeChangeItem(BaseModel):
    section: Literal["DEADLINE", "ELIGIBILITY", "DOCUMENT", "FEE"]
    change_type: Literal["ADDED", "REMOVED", "CHANGED"]
    label: str
    field_name: Optional[str] = None
    before_value: Optional[str] = None
    after_value: Optional[str] = None
    before_quote: Optional[str] = None
    after_quote: Optional[str] = None
    before_page_number: Optional[int] = None
    after_page_number: Optional[int] = None


class NoticeVersionComparisonResponse(BaseModel):
    older_version_id: str
    newer_version_id: str
    total_changes: int
    changes: List[NoticeChangeItem] = Field(default_factory=list)
