"""Generates academic-style College Lab Report PDFs from executed student code."""
import json
import os
import re
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, PageTemplate, Paragraph, Spacer,
)
from groq import Groq

from config import GROQ_API_KEY

_LANG_LABELS = {"python": "Python", "nlp": "Python (NLP)", "matlab": "MATLAB"}

_ACCENT = colors.HexColor("#6c63ff")
_INK = colors.HexColor("#1a1d27")
_MUTED = colors.HexColor("#6b7280")
_CODE_BG = colors.HexColor("#f4f4f4")
_CODE_BORDER = colors.HexColor("#dddddd")
_OUTPUT_BG = colors.HexColor("#0f1117")
_OUTPUT_FG = colors.HexColor("#e2e8f0")


class _NumberedCanvas(canvas.Canvas):
    """Defers footer drawing until save(), so 'Page X of Y' can show the true total."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total_pages)
            super().showPage()
        super().save()

    def _draw_footer(self, total_pages):
        page_width, _ = A4
        self.saveState()
        self.setStrokeColor(_CODE_BORDER)
        self.setLineWidth(0.6)
        self.line(0.75 * inch, 0.6 * inch, page_width - 0.75 * inch, 0.6 * inch)
        self.setFont("Helvetica", 8)
        self.setFillColor(_MUTED)
        self.drawCentredString(page_width / 2, 0.42 * inch, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def _draw_header(canvas_obj, _doc):
    page_width, page_height = A4
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(_INK)
    canvas_obj.drawString(0.75 * inch, page_height - 0.65 * inch, "AI Code Reviewer — College Lab Report")
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(_MUTED)
    canvas_obj.drawRightString(page_width - 0.75 * inch, page_height - 0.65 * inch,
                                datetime.now().strftime("%Y-%m-%d"))
    canvas_obj.setStrokeColor(_ACCENT)
    canvas_obj.setLineWidth(1.2)
    canvas_obj.line(0.75 * inch, page_height - 0.78 * inch, page_width - 0.75 * inch, page_height - 0.78 * inch)
    canvas_obj.restoreState()


def _build_styles() -> dict:
    """Fresh ParagraphStyle objects per call — never mutates a shared stylesheet,
    so repeated calls can never collide with a name that 'already exists'."""
    return {
        "LRTitle": ParagraphStyle(
            "LRTitle", fontName="Helvetica-Bold", fontSize=16,
            textColor=_INK, spaceAfter=6, leading=20),
        "LRMeta": ParagraphStyle(
            "LRMeta", fontName="Helvetica", fontSize=9,
            textColor=_MUTED, spaceAfter=14),
        "LRHeading": ParagraphStyle(
            "LRHeading", fontName="Helvetica-Bold", fontSize=12,
            textColor=_ACCENT, spaceBefore=16, spaceAfter=14),
        "LRBody": ParagraphStyle(
            "LRBody", fontName="Helvetica", fontSize=10, leading=15,
            alignment=TA_JUSTIFY, textColor=_INK),
        "LRAlgoStep": ParagraphStyle(
            "LRAlgoStep", fontName="Helvetica", fontSize=10, leading=14,
            leftIndent=14, spaceAfter=4, textColor=_INK),
        "LRCode": ParagraphStyle(
            "LRCode", fontName="Courier", fontSize=8.5, leading=12,
            backColor=_CODE_BG, borderColor=_CODE_BORDER, borderWidth=0.6,
            borderPadding=10, leftIndent=2, rightIndent=2, spaceAfter=4),
        "LROutput": ParagraphStyle(
            "LROutput", fontName="Courier", fontSize=8.5, leading=12,
            backColor=_OUTPUT_BG, textColor=_OUTPUT_FG,
            borderPadding=10, leftIndent=2, rightIndent=2, spaceAfter=4),
    }


def _monospace_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Escapes XML-sensitive chars and preserves leading indentation with &nbsp;,
    while leaving inner spaces breakable so long lines still wrap inside the box."""
    lines = text.splitlines() or [""]
    rendered = []
    for line in lines:
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        rendered.append("&nbsp;" * indent + escape(stripped))
    return Paragraph("<br/>".join(rendered), style)


def _heuristic_content(code_type: str, source_code: str) -> dict:
    """Offline fallback used when Groq is unavailable or returns something unusable."""
    lang_label = _LANG_LABELS.get(code_type, "Python")
    if re.search(r"plot3|surf\(|mesh\(", source_code):
        subject = "a 3D surface/mesh plot"
    elif re.search(r"\bplot\(|matplotlib", source_code):
        subject = "a 2D data visualization"
    elif re.search(r"nltk|spacy|textblob|sentiment", source_code, re.I):
        subject = "a natural language processing pipeline"
    else:
        subject = "the given computation"

    return {
        "title": f"Experiment: {subject.capitalize()} using {lang_label}",
        "aim": f"To write and execute a {lang_label} program that implements {subject} "
               "and to verify that its output matches the expected result.",
        "algorithm": [
            "Start the program.",
            f"Import/load the required {lang_label} libraries and modules.",
            "Initialize the input parameters and data structures needed for the computation.",
            "Compute the required values using the defined mathematical/logical operations.",
            "Store the intermediate results in appropriate variables.",
            "Configure the visualization or output settings, if applicable.",
            "Generate the output — display text results or render the plot/figure.",
            "Label and style the output for readability (titles, axes, legends).",
            "Verify the output matches the expected result of the experiment.",
            "Terminate the program.",
        ],
    }


def _normalize_algorithm(steps, fallback_steps) -> list:
    steps = [str(s).strip() for s in (steps or []) if str(s).strip()][:10]
    i = 0
    while len(steps) < 10:
        steps.append(fallback_steps[i] if i < len(fallback_steps) else "Terminate the program.")
        i += 1
    return steps


def _generate_report_content(code_type: str, source_code: str) -> dict:
    fallback = _heuristic_content(code_type, source_code)
    if not GROQ_API_KEY:
        return fallback

    lang_label = _LANG_LABELS.get(code_type, "Python")
    prompt = (
        f"You are writing a formal college lab report for a {lang_label} programming exercise.\n"
        "Read the source code below and respond with STRICT JSON only (no markdown fences, "
        "no commentary) using exactly these keys:\n"
        '  "title": a short experiment title, e.g. "Experiment: Sine Wave Visualization using Matplotlib"\n'
        '  "aim": one or two formal academic sentences stating what the experiment achieves\n'
        '  "algorithm": an array of exactly 10 short procedural steps describing the program logic '
        'from start to finish, lab-manual style (e.g. "Import the required libraries.")\n\n'
        f"Source code:\n```{code_type}\n{source_code[:4000]}\n```\n\n"
        "JSON:"
    )
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return {
            "title": str(data.get("title") or fallback["title"]).strip(),
            "aim": str(data.get("aim") or fallback["aim"]).strip(),
            "algorithm": _normalize_algorithm(data.get("algorithm"), fallback["algorithm"]),
        }
    except Exception:  # pylint: disable=broad-exception-caught
        return fallback


def generate_lab_report(
    code_type: str,
    source_code: str,
    text_output: str,
    image_path: str | None = None,
    output_path: str = "reports/lab_report.pdf",
) -> str:
    """Builds a formal Lab Report PDF (Title/Aim/Algorithm/Source/Output) and returns its path."""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    content = _generate_report_content(code_type, source_code)
    styles = _build_styles()
    lang_label = _LANG_LABELS.get(code_type, code_type.upper())

    algorithm_steps = [
        Paragraph(f"{i}. {escape(step)}", styles["LRAlgoStep"])
        for i, step in enumerate(content["algorithm"], start=1)
    ]

    output_flowables = []
    has_text_output = bool(text_output and text_output.strip())
    if has_text_output:
        output_flowables.append(_monospace_paragraph(text_output, styles["LROutput"]))
    if image_path and os.path.exists(image_path):
        image = Image(image_path, width=400, height=300)
        image.hAlign = "CENTER"
        output_flowables.append(Spacer(1, 8))
        output_flowables.append(image)
    elif not has_text_output:
        output_flowables.append(Paragraph("(No output was produced.)", styles["LRBody"]))

    story = [
        Paragraph(escape(content["title"]), styles["LRTitle"]),
        Paragraph(f"Language: {lang_label} &nbsp;&nbsp;|&nbsp;&nbsp; "
                  f"Generated: {datetime.now():%Y-%m-%d %H:%M}", styles["LRMeta"]),
        # Each heading is bundled with (at least the start of) its own content via
        # KeepTogether, so a heading can never get stranded alone at the very
        # bottom of a page — Platypus pushes the whole pair to the next page
        # instead. The content itself can still flow across further pages once
        # it has started (e.g. a long code/output box), only the heading's
        # orphaning is what this prevents.
        KeepTogether([Paragraph("AIM", styles["LRHeading"]), Paragraph(escape(content["aim"]), styles["LRBody"])]),
        KeepTogether([Paragraph("ALGORITHM", styles["LRHeading"]), *algorithm_steps[:1]]),
        *algorithm_steps[1:],
        KeepTogether([Paragraph("SOURCE CODE", styles["LRHeading"]), _monospace_paragraph(source_code, styles["LRCode"])]),
        KeepTogether([Paragraph("EXPECTED OUTPUT", styles["LRHeading"]), *output_flowables]),
    ]

    doc = BaseDocTemplate(
        output_path, pagesize=A4,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=1.0 * inch, bottomMargin=0.85 * inch,
        title=content["title"],
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="lab_report_frame")
    doc.addPageTemplates([PageTemplate(id="lab_report", frames=[frame], onPage=_draw_header)])
    doc.build(story, canvasmaker=_NumberedCanvas)
    return output_path
