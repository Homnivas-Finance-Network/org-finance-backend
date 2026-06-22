"""
Generates a filled-in infosheet PDF for a case, using the same section/field
layout defined in schemas.py. Missing fields are left blank (printed as a
dotted line) so a broker can hand-write them in if needed.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)

from schemas import FIELD_SCHEMAS, VERTICAL_NAMES

GOLD = colors.HexColor("#9c7a1f")
DARK = colors.HexColor("#0a192f")
LIGHT_GREY = colors.HexColor("#f4f4f4")
BORDER_GREY = colors.HexColor("#d9d9d9")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleHFN", parent=base["Heading1"], fontSize=16, textColor=DARK,
            spaceAfter=2, fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "SubtitleHFN", parent=base["Normal"], fontSize=9, textColor=colors.grey,
            spaceAfter=8,
        ),
        "section": ParagraphStyle(
            "SectionHFN", parent=base["Heading2"], fontSize=11, textColor=GOLD,
            spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold",
        ),
        "label": ParagraphStyle(
            "LabelHFN", parent=base["Normal"], fontSize=8.5, textColor=colors.HexColor("#555555"),
        ),
        "value": ParagraphStyle(
            "ValueHFN", parent=base["Normal"], fontSize=9.5, textColor=DARK,
            fontName="Helvetica-Bold",
        ),
        "footer": ParagraphStyle(
            "FooterHFN", parent=base["Normal"], fontSize=7.5, textColor=colors.grey,
        ),
    }


def generate_infosheet_pdf(vertical: str, case_id: str, broker_name: str, client_label: str, data: dict) -> bytes:
    schema = FIELD_SCHEMAS.get(vertical)
    if not schema:
        raise ValueError(f"Unknown vertical: {vertical}")

    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"{VERTICAL_NAMES.get(vertical, vertical)} Infosheet - {client_label}",
    )

    story = []

    # Header
    story.append(Paragraph("HOMNIVAS FINANCE NETWORK", styles["title"]))
    story.append(Paragraph(
        f"{VERTICAL_NAMES.get(vertical, vertical)} ({vertical}) &mdash; Client Infosheet",
        styles["subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=1.2, color=GOLD, spaceAfter=8))

    meta_table = Table(
        [[
            Paragraph(f"<b>Case ID:</b> {case_id}", styles["label"]),
            Paragraph(f"<b>Broker:</b> {broker_name or '-'}", styles["label"]),
            Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%d %b %Y, %I:%M %p')}", styles["label"]),
        ]],
        colWidths=["33%", "33%", "34%"],
    )
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(meta_table)

    # Sections
    for section_title, fields in schema:
        story.append(Paragraph(section_title.upper(), styles["section"]))

        rows = []
        for key, label in fields:
            raw = data.get(key, "")
            value = str(raw).strip() if raw else "_" * 38
            rows.append([
                Paragraph(label, styles["label"]),
                Paragraph(value, styles["value"]),
            ])

        t = Table(rows, colWidths=["42%", "58%"])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER_GREY),
            ("LEFTPADDING", (0, 0), (0, -1), 4),
            ("BACKGROUND", (0, 0), (0, -1), LIGHT_GREY),
        ]))
        story.append(t)
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER_GREY))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Generated automatically by the Homnivas AI Mitra intake assistant. "
        "Please verify all details with the client before submitting to the lender.",
        styles["footer"],
    ))

    doc.build(story)
    return buffer.getvalue()
