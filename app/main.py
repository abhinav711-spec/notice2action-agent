"""FastAPI application for Notice2Action's local document workflow."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.notice_watch import compare_notice_versions
from app.pipeline import Notice2ActionPipeline
from app.schemas import (
    Notice2ActionResponse,
    NoticeVersionComparisonRequest,
    NoticeVersionComparisonResponse,
    StudentProfile,
)
from app.security import MAX_FILE_SIZE_BYTES

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("notice2action")

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = ROOT / "samples" / "sample_notice.pdf"
STATIC_PATH = ROOT / "static"

app = FastAPI(
    title="Notice2Action",
    version="2.0.0",
    description="Local, evidence-linked analysis for academic and public notices.",
    docs_url="/docs",
    redoc_url="/redoc",
)
pipeline = Notice2ActionPipeline()
calendar_cache: dict[str, str] = {}
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_index() -> FileResponse:
    return FileResponse(STATIC_PATH / "index.html", media_type="text/html")


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "HEALTHY",
        "service": "Notice2Action",
        "version": "2.0.0",
        "extraction_engine": "Deterministic local rules",
        "external_model_required": False,
        "pdf_page_limit": 25,
    }


@app.post("/api/process", response_model=Notice2ActionResponse)
async def process_document(
    file: UploadFile = File(...),
    student_profile: Optional[str] = Form(None),
) -> Notice2ActionResponse:
    raw_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    profile = StudentProfile()
    if student_profile:
        try:
            profile = StudentProfile.model_validate_json(student_profile)
        except (ValidationError, ValueError) as error:
            raise HTTPException(status_code=422, detail="Invalid applicant profile JSON.") from error
    try:
        result = pipeline.run_pipeline(raw_bytes, profile)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Notice analysis failed")
        raise HTTPException(status_code=500, detail="Notice analysis failed.") from error
    calendar_cache[result.notice_id] = result.calendar_ics
    return result


@app.get("/api/demo-conflict", response_model=Notice2ActionResponse)
def run_demo_conflict() -> Notice2ActionResponse:
    if not SAMPLE_PATH.is_file():
        from app.generate_sample import create_sample_pdf

        create_sample_pdf(str(SAMPLE_PATH))
    sample_profile = StudentProfile(
        name="Aarav Sharma",
        email="aarav.sharma@example.edu",
        category="OBC-NCL",
        annual_income_inr=650000,
        cgpa=7.4,
        certificate_issue_date="2023-01-15",
        available_documents=["10th Marksheet", "12th Marksheet", "College ID Card"],
    )
    try:
        result = pipeline.run_pipeline(SAMPLE_PATH.read_bytes(), sample_profile)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    calendar_cache[result.notice_id] = result.calendar_ics
    return result


@app.post("/api/watch/compare", response_model=NoticeVersionComparisonResponse)
def compare_saved_notice_versions(
    request: NoticeVersionComparisonRequest,
) -> NoticeVersionComparisonResponse:
    return compare_notice_versions(request)


@app.get("/api/calendar/ics/{notice_id}")
def download_calendar_ics(notice_id: str) -> Response:
    calendar = calendar_cache.get(notice_id)
    if calendar is None:
        raise HTTPException(status_code=404, detail="Calendar file not found or expired.")
    return Response(
        content=calendar,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="Notice2Action_{notice_id}.ics"'},
    )


@app.get("/api/sample/download-pdf")
def download_sample_pdf() -> FileResponse:
    if not SAMPLE_PATH.is_file():
        from app.generate_sample import create_sample_pdf

        create_sample_pdf(str(SAMPLE_PATH))
    return FileResponse(
        SAMPLE_PATH,
        media_type="application/pdf",
        filename="Notice2Action_sample.pdf",
    )
