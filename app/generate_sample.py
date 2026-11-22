"""Generate a small, clearly labeled fictional scholarship notice for demos."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def create_sample_pdf(output_path: str) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(destination), pagesize=letter)
    pdf.setTitle("Fictional Notice2Action Sample Notice")
    pdf.setFont("Helvetica-Bold", 17)
    pdf.drawString(55, 745, "SAMPLE ONLY - FICTIONAL UNIVERSITY")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(55, 713, "Merit Support Scholarship - Demonstration Notice")
    pdf.setFont("Helvetica", 10)
    first_page = [
        "Notice No: DEMO/SS/2026/01",
        "Issued by: Example University Student Support Office",
        "For demonstration only. This is not a real government or university notice.",
        "",
        "ELIGIBILITY",
        "Applicants must have a minimum CGPA of 7.5 out of 10.",
        "Annual family income must not exceed Rs. 6,00,000 per year.",
        "Applicants must be enrolled as full-time undergraduate students.",
        "",
        "APPLICATION FEE",
        "No application fee is payable for this demonstration scholarship.",
        "",
        "APPLICATION DEADLINE",
        "Submit the online application by 30 November 2026.",
        "",
        "Apply through the Example University student support office.",
    ]
    y = 677
    for line in first_page:
        pdf.drawString(55, y, line)
        y -= 22 if line else 12
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(55, 745, "SUPPORTING DOCUMENTS AND UPDATES")
    pdf.setFont("Helvetica", 10)
    second_page = [
        "Applicants must submit a current Income Certificate.",
        "Submit a Bonafide Student Certificate signed by the institution.",
        "Academic marksheets must be included with the application.",
        "The correction window remains open until 10 December 2026.",
        "",
        "Questions: support@example.edu",
        "",
        "This fictional notice is provided to demonstrate evidence citations",
        "and version comparison. Always consult the actual issuing authority.",
    ]
    y = 710
    for line in second_page:
        pdf.drawString(55, y, line)
        y -= 24 if line else 14
    pdf.save()


if __name__ == "__main__":
    create_sample_pdf("samples/sample_notice.pdf")
