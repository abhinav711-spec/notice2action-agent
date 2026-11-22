from app.main import app
from app.schemas import (
    DeadlineItem,
    EligibilityCriteriaItem,
    NoticeMetadata,
    NoticeVersionComparisonRequest,
    NoticeVersionSnapshot,
    RequiredDocumentItem,
    StructuredNoticeExtraction,
)
from app.notice_watch import compare_notice_versions
from fastapi.testclient import TestClient


def _extraction(
    *,
    deadline: str = "30 January 2027",
    threshold: str = "7.5",
    documents: tuple[str, ...] = ("Income Certificate",),
    page_number: int = 2,
) -> StructuredNoticeExtraction:
    return StructuredNoticeExtraction(
        metadata=NoticeMetadata(
            title="Merit Scholarship",
            issuing_organization="Education Council",
        ),
        deadlines=[
            DeadlineItem(
                title="Application closes",
                date_str=deadline,
                iso_date=None,
                verbatim_quote=f"Applications close on {deadline}.",
                page_number=page_number,
                urgency="HIGH",
                action_required="Submit the online application",
            )
        ],
        eligibility_criteria=[
            EligibilityCriteriaItem(
                criterion_name="Minimum CGPA",
                condition=f">= {threshold}",
                threshold_value=threshold,
                applicable_category="ALL",
                verbatim_quote=f"Applicants need a minimum CGPA of {threshold}.",
                page_number=1,
            )
        ],
        required_documents=[
            RequiredDocumentItem(
                document_name=name,
                validity_rule="Issued during the current financial year",
                is_mandatory=True,
                verbatim_quote=f"Submit a valid {name}.",
                page_number=page_number,
            )
            for name in documents
        ],
        official_summary="Scholarship requirements.",
    )


def _request(older: StructuredNoticeExtraction, newer: StructuredNoticeExtraction):
    return NoticeVersionComparisonRequest(
        older=NoticeVersionSnapshot(
            version_id="v1",
            saved_at="2026-01-01T10:00:00Z",
            extraction=older,
            grounded_item_ids=["DEADLINE-1", "ELIGIBILITY-1"]
            + [f"DOC-{index}" for index in range(1, len(older.required_documents) + 1)],
        ),
        newer=NoticeVersionSnapshot(
            version_id="v2",
            saved_at="2026-02-01T10:00:00Z",
            extraction=newer,
            grounded_item_ids=["DEADLINE-1", "ELIGIBILITY-1"]
            + [f"DOC-{index}" for index in range(1, len(newer.required_documents) + 1)],
        ),
    )


def test_notice_watch_reports_requirement_changes_with_both_sources():
    result = compare_notice_versions(
        _request(
            _extraction(),
            _extraction(
                deadline="15 February 2027",
                threshold="8.0",
                documents=("Bonafide Certificate",),
            ),
        )
    )

    date_change = next(
        change
        for change in result.changes
        if change.section == "DEADLINE" and change.field_name == "Date"
    )
    threshold_change = next(
        change
        for change in result.changes
        if change.section == "ELIGIBILITY" and change.field_name == "Threshold"
    )
    added_document = next(
        change
        for change in result.changes
        if change.section == "DOCUMENT" and change.change_type == "ADDED"
    )

    assert date_change.before_value == "30 January 2027"
    assert date_change.after_value == "15 February 2027"
    assert date_change.before_page_number == 2
    assert date_change.after_page_number == 2
    assert "30 January 2027" in date_change.before_quote
    assert "15 February 2027" in date_change.after_quote
    assert threshold_change.before_value == "7.5"
    assert threshold_change.after_value == "8.0"
    assert added_document.label == "Bonafide Certificate"
    assert added_document.after_quote == "Submit a valid Bonafide Certificate."
    assert result.total_changes == len(result.changes)


def test_notice_watch_ignores_quote_and_page_reflow_when_rules_are_unchanged():
    result = compare_notice_versions(
        _request(
            _extraction(page_number=2),
            _extraction(page_number=3),
        )
    )

    assert result.total_changes == 0
    assert result.changes == []


def test_notice_watch_excludes_unverified_claims():
    request = _request(
        _extraction(),
        _extraction(deadline="15 February 2027", threshold="8.0"),
    )
    request.older.grounded_item_ids = []
    request.newer.grounded_item_ids = []

    result = compare_notice_versions(request)

    assert result.total_changes == 0


def test_notice_watch_compare_endpoint_returns_evidence_linked_changes():
    client = TestClient(app)
    request = _request(_extraction(), _extraction(deadline="15 February 2027"))

    response = client.post(
        "/api/watch/compare",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["older_version_id"] == "v1"
    assert body["newer_version_id"] == "v2"
    assert body["total_changes"] > 0
    assert all(
        change["before_page_number"] and change["after_page_number"]
        for change in body["changes"]
        if change["change_type"] == "CHANGED"
    )
