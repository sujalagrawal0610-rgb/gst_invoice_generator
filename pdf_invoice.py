"""SME TAX INVOICE - original layout (navy header band, Billed To, light table header, totals, italic footer),
extended to multiple items with automatic wrapping and page breaks. Built in memory per request."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether

import config

NAVY, SOFT, LINE, GREY, INK = (colors.HexColor(x) for x in ("#1e293b", "#f1f5f9", "#cbd5e1", "#64748b", "#0f172a"))
_UNI, _GLYPHS = None, set()


def _init_fonts():
    """Helvetica for normal text (like the original); a bundled Unicode font only for characters
    Helvetica cannot draw (accents, Hindi if a Devanagari font is added to /fonts)."""
    global _UNI, _GLYPHS
    try:
        f = config.BASE_DIR / "fonts" / "DejaVuSans.ttf"
        if f.exists():
            pdfmetrics.registerFont(TTFont("AppUni", str(f)))
            _UNI, _GLYPHS = "AppUni", set(pdfmetrics.getFont("AppUni").face.charToGlyph.keys())
    except Exception:
        _UNI, _GLYPHS = None, set()


_init_fonts()


def safe(text):
    """Escape for Paragraph; swap unsupported characters so nothing crashes or turns into boxes."""
    out, run = [], False
    for ch in str(text or ""):
        if ch == "\n":
            out.append("<br/>")
            continue
        if ord(ch) < 256:
            if run:
                out.append("</font>")
                run = False
            out.append(escape(ch))
        elif _UNI and ord(ch) in _GLYPHS:
            if not run:
                out.append(f'<font name="{_UNI}">')
                run = True
            out.append(escape(ch))
        else:
            if run:
                out.append("</font>")
                run = False
            out.append("?")
    if run:
        out.append("</font>")
    return "".join(out)


def _num(v):
    f = float(v)
    return f"{f:g}"


def build_pdf(inv, items, _seller=None):
    buf = io.BytesIO()
    width, height = letter
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=50, rightMargin=50, topMargin=135, bottomMargin=75,
                            title=f"Invoice {inv['invoice_no']}", author="SME Tax Invoice")
    W = width - 100

    def st(name, **kw):
        base = dict(fontName="Helvetica", fontSize=11, leading=15, textColor=colors.black)
        base.update(kw)
        return ParagraphStyle(name, **base)

    body, bold12 = st("b"), st("b12", fontName="Helvetica-Bold", fontSize=12, leading=18)
    cell, cellb = st("c", fontSize=10, leading=13), st("cb", fontName="Helvetica-Bold", fontSize=10, leading=13)
    cell_r = st("cr", fontSize=10, leading=13, alignment=TA_RIGHT)
    cellb_r = st("cbr", fontName="Helvetica-Bold", fontSize=10, leading=13, alignment=TA_RIGHT)
    small_grey = st("sg", fontSize=9, leading=12, textColor=GREY)

    story = []
    # Billed To (left)  |  Invoice no / date (right)
    left = [Paragraph("Billed To:", bold12), Paragraph(f"Name: {safe(inv['buyer_name'])}", body),
            Paragraph(f"Address: {safe(inv['buyer_address'])}", body)]
    if inv["buyer_email"]:
        left.append(Paragraph(f"Email: {safe(inv['buyer_email'])}", body))
    right = [Paragraph("&nbsp;", bold12), Paragraph(f"Invoice No: {safe(inv['invoice_no'])}", st("r1", alignment=TA_RIGHT)),
             Paragraph(f"Date: {safe(str(inv['created_at'])[:10])}", st("r2", alignment=TA_RIGHT))]
    head = Table([[left, right]], colWidths=[W * 0.62, W * 0.38])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 26)]

    cols = ["Item Description", "Category", "Qty", "Rate (Rs.)", "Disc %", "GST %", "Amount (Rs.)"]
    data = [[Paragraph(c, cellb_r if i >= 2 else cellb) for i, c in enumerate(cols)]]
    for it in items:
        data.append([Paragraph(safe(it["name"]), cell), Paragraph(safe(it["category"] or ""), cell),
                     Paragraph(_num(it["qty"]), cell_r), Paragraph(f"{it['rate']:.2f}", cell_r),
                     Paragraph(_num(it["discount_pct"]), cell_r), Paragraph(f"{_num(it['gst_rate'])}%", cell_r),
                     Paragraph(f"{it['line_total']:.2f}", cell_r)])
    cw = [W - (62 + 32 + 78 + 38 + 38 + 82), 62, 32, 78, 38, 38, 82]
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), SOFT), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                           ("TOPPADDING", (0, 1), (-1, -1), 9), ("BOTTOMPADDING", (0, 1), (-1, -1), 9),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("LINEBELOW", (0, -1), (-1, -1), 0.8, LINE)]))
    story += [t, Spacer(1, 18)]

    gst_rates = {float(i["gst_rate"]) for i in items}
    gst_label = f"GST Amount ({_num(gst_rates.copy().pop())}%):" if len(gst_rates) == 1 else "GST Amount:"
    lab = st("lab", alignment=TA_RIGHT)
    rows = [[Paragraph("Subtotal:", lab), Paragraph(f"Rs. {inv['subtotal']:.2f}", body)]]
    if inv["discount_total"]:
        rows.append([Paragraph("Discount:", lab), Paragraph(f"- Rs. {inv['discount_total']:.2f}", body)])
    rows.append([Paragraph(gst_label, lab), Paragraph(f"Rs. {inv['gst_total']:.2f}", body)])
    rows.append([Paragraph("Grand Total:", st("gl", fontName="Helvetica-Bold", fontSize=12, alignment=TA_RIGHT, textColor=INK)),
                 Paragraph(f"Rs. {inv['total']:.2f}", st("gv", fontName="Helvetica-Bold", fontSize=12, textColor=INK))])
    tot = Table(rows, colWidths=[W - 130, 130])
    tot.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                             ("RIGHTPADDING", (0, 0), (0, -1), 20), ("LEFTPADDING", (1, 0), (1, -1), 0)]))
    story.append(KeepTogether(tot))
    if inv["notes"]:
        story += [Spacer(1, 22), Paragraph("Notes:", st("nt", fontName="Helvetica-Bold", fontSize=10)),
                  Paragraph(safe(inv["notes"]), st("nt2", fontSize=10, leading=13))]

    def first(canvas, _d):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 100, width, 100, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 22)
        canvas.drawString(50, height - 50, "SME TAX INVOICE")
        canvas.setFont("Helvetica", 10)
        canvas.drawString(50, height - 70, "GST Compliant Billing System")
        canvas.drawRightString(width - 50, height - 50, "ORIGINAL FOR RECIPIENT")
        canvas.restoreState()
        footer(canvas, _d)

    def footer(canvas, _d):
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 9)
        canvas.setFillColor(GREY)
        canvas.drawString(50, 50, "This is a computer-generated GST invoice and is legally valid without physical signature.")
        canvas.drawRightString(width - 50, 36, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    def later(canvas, _d):
        footer(canvas, _d)

    doc.build(story, onFirstPage=first, onLaterPages=later)
    buf.seek(0)
    return buf
