"""PDF input limits, extracted-text sanitization, and injection-risk indicators."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
MAX_ALLOWED_PAGES = 25
PDF_MAGIC_BYTES = b"%PDF-"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\u202A-\u202E\u2066-\u2069]")
_INJECTION_PATTERNS = (
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts)", re.I), "CRITICAL"),
    (re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts)", re.I), "CRITICAL"),
    (re.compile(r"system\s+override|developer\s+mode|jailbreak", re.I), "CRITICAL"),
    (re.compile(r"reveal\s+(the\s+)?(system prompt|api key|secret key)", re.I), "HIGH"),
    (re.compile(r"<\/?(system|instruction|prompt)>", re.I), "HIGH"),
)
_THREAT_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def validate_pdf_bytes(raw_bytes: bytes) -> Tuple[bool, Optional[str]]:
    if not raw_bytes:
        return False, "File is empty (0 bytes)."
    if len(raw_bytes) > MAX_FILE_SIZE_BYTES:
        return False, f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit."
    if not raw_bytes.startswith(PDF_MAGIC_BYTES):
        return False, "Invalid PDF signature: missing %PDF- header."
    return True, None


def sanitize_text(text: str) -> Tuple[str, int]:
    return _CONTROL_CHARS.subn("", text)


def scan_for_prompt_injection(text: str) -> Tuple[bool, str, List[str]]:
    threat = "NONE"
    snippets: List[str] = []
    for pattern, level in _INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            if _THREAT_RANK[level] > _THREAT_RANK[threat]:
                threat = level
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            snippets.append(text[start:end].strip())
            if len(snippets) >= 5:
                break
        if len(snippets) >= 5:
            break
    return threat != "NONE", threat, snippets
