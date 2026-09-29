"""
Generates a single-page inspection report PDF from the report_data dict
produced by app.py's _build_report_group().

Uses ReportLab only - pure Python, no system-level libraries required
(unlike WeasyPrint, which needs GTK/Pango/Cairo installed on the machine).

Public entry point (signature matches the existing call in app.py):

    generate_inspection_pdf(report_data, output_path, app_root)
"""

import os
from datetime import datetime
from urllib.parse import urlparse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage,
)

# ---------------------------------------------------------------- palette --
INK = colors.HexColor("#1c2128")
INK_SOFT = colors.HexColor("#4b5259")
PAPER_2 = colors.HexColor("#eee8d9")
HAIRLINE = colors.HexColor("#d8cfb8")
BLUEPRINT = colors.HexColor("#2856a3")
BLUEPRINT_SOFT = colors.HexColor("#eef2f8")
PASS = colors.HexColor("#2f6f4e")
PASS_SOFT = colors.HexColor("#e5f0e8")
FAIL = colors.HexColor("#a53d30")
FAIL_SOFT = colors.HexColor("#f7e7e3")
AMBER = colors.HexColor("#b4790c")
AMBER_SOFT = colors.HexColor("#fbf1de")

_EMPTY_VALUES = {None, "", "-", "None"}

PAGE_W, PAGE_H = A4
MARGIN = 12 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


# --------------------------------------------------------------- helpers --
def _clean(value):
    return None if value in _EMPTY_VALUES else value


def _text(value):
    v = _clean(value)
    return str(v) if v is not None else "-"


def _resolve_image_path(image_url, app_root):
    """Convert a served image URL (e.g. '/uploads/<folder>/foo.jpg', as
    produced by url_for('serve_upload', filename=...)) into a local
    filesystem path ReportLab can embed directly.
    """
    if not image_url:
        return None
    try:
        path = urlparse(str(image_url)).path
    except Exception:
        path = str(image_url)

    marker = "/uploads/"
    if marker not in path:
        return None

    rel_path = path.split(marker, 1)[1]
    abs_path = os.path.join(app_root, "static", "uploads", *rel_path.split("/"))
    return abs_path if os.path.isfile(abs_path) else None


def _status_color(defect):
    if defect.get("isError"):
        return AMBER, AMBER_SOFT
    status = str(defect.get("status") or "").strip().upper()
    if status in {"OK", "ACCEPTED", "PASS"}:
        return PASS, PASS_SOFT
    return FAIL, FAIL_SOFT


def _stamp_color(final_decision):
    decision = str(final_decision or "").strip().lower()
    if decision == "accepted":
        return PASS
    if decision == "error":
        return AMBER
    return FAIL


# --------------------------------------------------------------- styles --
_styles = {
    "eyebrow": ParagraphStyle("eyebrow", fontName="Helvetica-Bold", fontSize=8,
                               textColor=BLUEPRINT, leading=10, spaceAfter=1),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=19,
                             textColor=INK, leading=22),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8,
                            textColor=INK_SOFT, leading=12, alignment=2),
    "meta_strong": ParagraphStyle("meta_strong", fontName="Helvetica-Bold", fontSize=9,
                                   textColor=INK, leading=12, alignment=2),
    "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=8.5,
                               textColor=INK, leading=11),
    "lbl": ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=6.8,
                           textColor=INK_SOFT, leading=9),
    "val": ParagraphStyle("val", fontName="Helvetica-Bold", fontSize=8.5,
                           textColor=INK, leading=11),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8,
                            textColor=INK, leading=10),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7,
                          textColor=colors.white, leading=9),
    "num": ParagraphStyle("num", fontName="Helvetica-Bold", fontSize=15,
                           alignment=1, leading=17),
    "sumlbl": ParagraphStyle("sumlbl", fontName="Helvetica-Bold", fontSize=6.8,
                              alignment=1, leading=9),
    "footer": ParagraphStyle("footer", fontName="Helvetica", fontSize=6.5,
                              textColor=INK_SOFT, alignment=1),
    "empty": ParagraphStyle("empty", fontName="Helvetica", fontSize=8,
                             textColor=INK_SOFT, alignment=1),
}


def _p(text, style_key="cell"):
    return Paragraph(_text(text), _styles[style_key])


# --------------------------------------------------------------- pieces --
def _build_header(report):
    stamp_color = _stamp_color(report.get("finalDecision"))
    left = [
        Paragraph("QC INSPECTION TRAVELER", _styles["eyebrow"]),
        Paragraph("Inspection Report", _styles["title"]),
    ]

    meta_lines = (
        f'RECORD ID: <b>{_text(report.get("reportId"))}</b><br/>'
        f'Generated: {report.get("generatedAt")}'
    )
    right_meta = Paragraph(meta_lines, _styles["meta"])

    stamp_style = ParagraphStyle(
        "stamp", fontName="Helvetica-Bold", fontSize=11,
        textColor=stamp_color, alignment=2,
    )
    stamp_text = _text(report.get("finalDecision")).upper()
    stamp_table = Table([[Paragraph(stamp_text, stamp_style)]], colWidths=[45 * mm])
    stamp_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, stamp_color),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))

    right_col = [right_meta, Spacer(1, 3), stamp_table]

    header_table = Table(
        [[left, right_col]],
        colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 2.2, BLUEPRINT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return header_table


def _section_title(text):
    t = Table([[Paragraph(text.upper(), _styles["section"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER_2),
        ("LINEBEFORE", (0, 0), (0, -1), 3, BLUEPRINT),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _info_grid(rows):
    """rows: list of (label, value, label, value) tuples."""
    data = []
    for l1, v1, l2, v2 in rows:
        data.append([_p(l1, "lbl"), _p(v1, "val"), _p(l2, "lbl"), _p(v2, "val")])
    col_w = [CONTENT_W * 0.15, CONTENT_W * 0.35, CONTENT_W * 0.15, CONTENT_W * 0.35]
    t = Table(data, colWidths=col_w)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, HAIRLINE),
        ("BACKGROUND", (0, 0), (0, -1), PAPER_2),
        ("BACKGROUND", (2, 0), (2, -1), PAPER_2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(style))
    return t


def _defects_table(defects):
    header = [
        Paragraph("SL.NO", _styles["th"]), Paragraph("DEFECT TYPE", _styles["th"]),
        Paragraph("LOCATION", _styles["th"]), Paragraph("CAMERA / REF", _styles["th"]),
        Paragraph("IMAGE", _styles["th"]), Paragraph("STATUS", _styles["th"]),
    ]
    data = [header]

    if not defects:
        row = [Paragraph("No defects found", _styles["empty"]), "", "", "", "", ""]
        data.append(row)
    else:
        for i, d in enumerate(defects, start=1):
            img_cell = "-"
            if d.get("imageResolved"):
                try:
                    img_cell = RLImage(d["imageResolved"], width=13 * mm, height=9 * mm)
                except Exception:
                    img_cell = "-"
            status_color, _ = _status_color(d)
            status_style = ParagraphStyle(
                f"status{i}", fontName="Helvetica-Bold", fontSize=7.5, textColor=status_color,
            )
            data.append([
                _p(i, "cell"),
                _p(d.get("type"), "cell"),
                _p(d.get("location"), "cell"),
                _p(d.get("camera"), "cell"),
                img_cell,
                Paragraph(_text(d.get("status")).upper(), status_style),
            ])

    col_w = [CONTENT_W * 0.07, CONTENT_W * 0.20, CONTENT_W * 0.15,
              CONTENT_W * 0.28, CONTENT_W * 0.15, CONTENT_W * 0.15]
    t = Table(data, colWidths=col_w, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, HAIRLINE),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if not defects:
        style.append(("SPAN", (0, 1), (-1, 1)))
    for row_i in range(1, len(data)):
        if row_i % 2 == 0:
            style.append(("BACKGROUND", (0, row_i), (-1, row_i), colors.HexColor("#f7f4ec")))
    t.setStyle(TableStyle(style))
    return t


def _summary_strip(report):
    cells = [
        (report.get("qtyInspected"), "INSPECTED", BLUEPRINT_SOFT, BLUEPRINT),
        (report.get("qtyRejected"), "REJECTED", FAIL_SOFT, FAIL),
        (report.get("qtyErrors"), "ERRORS", AMBER_SOFT, AMBER),
        (report.get("qtyAccepted"), "ACCEPTED", PASS_SOFT, PASS),
    ]
    row = []
    for value, label, bg, fg in cells:
        num_style = ParagraphStyle("num_c", parent=_styles["num"], textColor=fg)
        lbl_style = ParagraphStyle("lbl_c", parent=_styles["sumlbl"], textColor=fg)
        cell_content = [
            Paragraph(str(value if value is not None else 0), num_style),
            Paragraph(label, lbl_style),
        ]
        row.append(cell_content)

    t = Table([row], colWidths=[CONTENT_W / 4] * 4)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, (_, _, bg, _) in enumerate(cells):
        style.append(("BACKGROUND", (i, 0), (i, 0), bg))
    t.setStyle(TableStyle(style))
    return t


# --------------------------------------------------------------- build --
def _build_view_model(report_data, app_root):
    report = dict(report_data or {})
    report["generatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    resolved_defects = []
    for d in report.get("defects") or []:
        d = dict(d)
        d["imageResolved"] = _resolve_image_path(d.get("image"), app_root)
        resolved_defects.append(d)
    report["defects"] = resolved_defects

    corrective_fields = ["rootCause", "immediateAction", "preventiveAction",
                          "responsibleDept", "targetDate"]
    report["hasCorrectiveInfo"] = any(_clean(report.get(f)) for f in corrective_fields)

    return report


def generate_inspection_pdf(report_data, output_path, app_root):
    """Render report_data into a single-page PDF at output_path.

    Args:
        report_data: dict produced by _build_report_group() in app.py
        output_path: absolute path to write the .pdf file to
        app_root: Flask app.root_path, used to resolve served image URLs
                  (e.g. /uploads/xxx.jpg) back to files on disk
    """
    report = _build_view_model(report_data, app_root)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
    )

    story = [_build_header(report), Spacer(1, 6)]

    story.append(_section_title("Inspection &amp; Component Details"))
    story.append(_info_grid([
        ("Customer", report.get("customer"), "Part No.", report.get("partNo")),
        ("Part Name", report.get("partName"), "Batch / Lot", report.get("batch")),
        ("Inspection Date", report.get("date"), "Inspector", report.get("inspector")),
        ("Component / Material",
         f'{_text(report.get("componentType"))} / {_text(report.get("material"))}',
         "Size / Finish",
         f'{_text(report.get("size"))} / {_text(report.get("surfaceFinish"))}'),
    ]))
    story.append(Spacer(1, 6))

    defect_count = len(report.get("defects") or [])
    story.append(_section_title(f"Defect Details ({defect_count})" if defect_count else "Defect Details"))
    story.append(_defects_table(report.get("defects") or []))
    story.append(_summary_strip(report))
    story.append(Spacer(1, 6))

    if report.get("hasCorrectiveInfo"):
        story.append(_section_title("Root Cause &amp; Corrective Action"))
        story.append(_info_grid([
            ("Root Cause", report.get("rootCause"), "Responsible Dept", report.get("responsibleDept")),
            ("Immediate Action", report.get("immediateAction"), "Target Date", report.get("targetDate")),
        ]))
        story.append(Spacer(1, 6))

    story.append(_section_title("Final Status"))
    story.append(_info_grid([
        ("Final Decision", report.get("finalDecision"), "Rework Required",
         "YES" if report.get("reworkRequired") else "NO"),
        ("Scrap", "YES" if report.get("scrap") else "NO", "Approved By", report.get("approvedBy")),
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Generated from the current inspection record by Valve Final Inspection System.",
        _styles["footer"],
    ))

    doc.build(story)
    return output_path