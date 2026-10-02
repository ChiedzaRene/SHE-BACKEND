"""Render a report document (see services.reports) to CSV or PDF."""
import csv
import io
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "glow-logo.jpg")
BRAND = colors.HexColor("#003B8E")
HEADER_BG = colors.HexColor("#EEF2F7")
GRID = colors.HexColor("#D5DCE6")


_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+$")


def csv_safe(value):
    """Prepare one CSV cell.

    * Spreadsheets run cells starting with = + - @ as formulas, so neutralise text that does.
    * "100,400" becomes 100400 so Excel reads a number rather than text.
    """
    if isinstance(value, str):
        if _THOUSANDS.match(value):
            return value.replace(",", "")
        if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + value
    return value


def to_csv(doc: dict) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([csv_safe(doc["title"])])
    w.writerow([csv_safe(doc["subtitle"])])
    w.writerow(["Generated", doc["generated_at"]])
    if len(doc["tables"]) == 1:
        # A single table (the incident register, the leaderboard) stays a clean importable sheet
        w.writerow([])
        for k in doc["kpis"]:
            w.writerow([csv_safe(k["label"]), csv_safe(k["value"])])
    else:
        w.writerow([])
        w.writerow(["Summary"])
        for k in doc["kpis"]:
            w.writerow([csv_safe(k["label"]), csv_safe(k["value"])])
    for table in doc["tables"]:
        w.writerow([])
        w.writerow([csv_safe(table["title"])])
        w.writerow([csv_safe(c) for c in table["columns"]])
        for row in table["rows"]:
            w.writerow([csv_safe(c) for c in row])
    for note in doc["notes"]:
        w.writerow([])
        w.writerow([csv_safe(note)])
    # BOM so Excel reads UTF-8 correctly
    return ("﻿" + out.getvalue()).encode("utf-8")


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def to_pdf(doc: dict) -> bytes:
    wide = max((len(t["columns"]) for t in doc["tables"]), default=0) > 6
    page = landscape(A4) if wide else A4
    margin = 15 * mm
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=page, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=18 * mm, title=doc["title"],
                            author="Glow Petroleum SHE")
    width = page[0] - 2 * margin

    base = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=base["Title"], textColor=BRAND, alignment=0, fontSize=20, leading=24)
    sub = ParagraphStyle("s", parent=base["Normal"], textColor=colors.HexColor("#475569"), fontSize=11)
    h2 = ParagraphStyle("h2", parent=base["Heading3"], textColor=BRAND, spaceBefore=10, spaceAfter=4)
    cell = ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=10)
    head = ParagraphStyle("hd", parent=cell, fontName="Helvetica-Bold")
    kpi_v = ParagraphStyle("kv", parent=base["Normal"], fontSize=15, leading=18, fontName="Helvetica-Bold", textColor=BRAND)
    kpi_l = ParagraphStyle("kl", parent=base["Normal"], fontSize=7.5, leading=9, textColor=colors.HexColor("#64748b"))
    note = ParagraphStyle("n", parent=base["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"))

    story = []
    heading = [[_p(doc["title"], title)], [_p(doc["subtitle"], sub)],
               [_p("Generated " + doc["generated_at"], note)]]
    if os.path.isfile(LOGO_PATH):
        logo = Image(LOGO_PATH, width=22 * mm, height=22 * mm, kind="proportional")
        top = Table([[logo, Table(heading, colWidths=[width - 30 * mm])]], colWidths=[28 * mm, width - 28 * mm])
    else:
        top = Table([[Table(heading, colWidths=[width])]], colWidths=[width])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [top, Spacer(1, 6 * mm)]

    if doc["kpis"]:
        per_row = 4
        cells = [[_p(k["value"], kpi_v), _p(k["label"], kpi_l)] for k in doc["kpis"]]
        rows = []
        for i in range(0, len(cells), per_row):
            chunk = cells[i:i + per_row]
            chunk += [["", ""]] * (per_row - len(chunk))
            rows.append([Table([[c[0]], [c[1]]], colWidths=[width / per_row - 4]) if c[0] != "" else "" for c in chunk])
        grid = Table(rows, colWidths=[width / per_row] * per_row)
        grid.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.5, GRID),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [grid, Spacer(1, 4 * mm)]

    for t in doc["tables"]:
        story.append(Paragraph(escape(t["title"]), h2))
        if not t["rows"]:
            story.append(_p("No records.", note))
            continue
        data = [[_p(c, head) for c in t["columns"]]] + [[_p(c, cell) for c in row] for row in t["rows"]]
        # Give long text columns more room than short ones
        longest = [max(len(str(c)) for c in col) for col in zip(t["columns"], *t["rows"])]
        weights = [min(max(n, 4), 60) for n in longest]
        widths = [width * w / sum(weights) for w in weights]
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG), ("GRID", (0, 0), (-1, -1), 0.4, GRID),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFBFD")]),
        ]))
        story += [table, Spacer(1, 3 * mm)]

    for n in doc["notes"]:
        story += [Spacer(1, 2 * mm), _p(n, note)]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(margin, 10 * mm, "Glow Petroleum · Safety, Health & Environment · Confidential")
        canvas.drawRightString(page[0] - margin, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
