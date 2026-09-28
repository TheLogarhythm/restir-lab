"""Draw the proposal pipeline as an editable vector PDF.

Run: python pipeline.py
Requires reportlab. Uses local Maple Mono fonts when available, otherwise Courier.
The three middle cards are alternative spatial reuse methods, not a serial chain.
"""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parent
FONT_DIR = Path.home() / 'Library/Fonts'
REG, BOLD = 'Courier', 'Courier-Bold'
if all((FONT_DIR / f'MapleMono-{w}.ttf').is_file() for w in ('Regular', 'Bold')):
    for name, weight in [('Maple', 'Regular'), ('Maple-Bold', 'Bold')]:
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / f'MapleMono-{weight}.ttf')))
    REG, BOLD = 'Maple', 'Maple-Bold'

INK = HexColor('#252535')
LINE = HexColor('#9497A0')
GRAY = HexColor('#EEF0F4')
BLUE = HexColor('#AEB8E6')
SAND = HexColor('#E9CDA8')
PAGE_W, PAGE_H = 1200, 348
pdf = canvas.Canvas(str(ROOT / 'pipeline.pdf'), pagesize=(PAGE_W, PAGE_H))
pdf.setTitle('ReSTIR spatial reuse: implementation and evaluation pipeline')
pdf.setAuthor('Luoyi Zhang and Zelin Gao')


def text(x, y, content, size=19, bold=False, color=INK):
    pdf.setFillColor(color)
    pdf.setFont(BOLD if bold else REG, size)
    pdf.drawCentredString(x, y, content)


def box(x, y, w, h, fill=GRAY, stroke=LINE, radius=9):
    pdf.setFillColor(fill)
    pdf.setStrokeColor(stroke)
    pdf.setLineWidth(1.2)
    pdf.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def arrow(points, dashed=False, head=True):
    pdf.setStrokeColor(LINE)
    pdf.setFillColor(LINE)
    pdf.setLineWidth(1.7)
    pdf.setDash([5, 4] if dashed else [])
    path = pdf.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    pdf.drawPath(path)
    pdf.setDash([])
    if head:
        import math
        x, y = points[-1]
        dx, dy = x-points[-2][0], y-points[-2][1]
        length = math.hypot(dx, dy)
        ux, uy = dx/length, dy/length
        a = pdf.beginPath()
        a.moveTo(x, y)
        a.lineTo(x-7*ux+3*uy, y-7*uy-3*ux)
        a.lineTo(x-7*ux-3*uy, y-7*uy+3*ux)
        a.close()
        pdf.drawPath(a, fill=1, stroke=0)


# Common inputs and DI preparation, used in every method configuration.
box(12, 88, 160, 158)
text(92, 216, 'Inputs', size=20, bold=True)
for y, label in zip((183, 160, 137, 114), ('Scenes', 'Cameras', 'Materials', 'Lights')):
    text(92, y, label)

box(210, 88, 185, 158)
text(302.5, 216, 'Shared DI', size=20, bold=True)
text(302.5, 181, 'Initial sampling', size=17.5)
arrow([(302.5, 166), (302.5, 150)])
text(302.5, 128, 'Temporal reuse', size=18.5)

# Three interchangeable spatial reuse configurations.
box(430, 34, 282, 299, fill=white, stroke=HexColor('#C9CBD0'), radius=12)
text(571, 307, 'Spatial reuse', size=22, bold=True)
text(571, 283, 'Select one per run', size=17)
cards = [
    (210, 'ReSTIR DI', 'Standard reuse', GRAY),
    (136, 'PDF Similarity', 'PDF-based rejection', SAND),
    (62, 'CGNS', 'Weighted sampling', BLUE),
]
for y, title, description, color in cards:
    box(453, y, 236, 62, fill=color)
    text(571, y+37, title, size=21, bold=True)
    text(571, y+14, description, size=18)

# Shading produces a separate image and timing record for each selected method.
box(770, 88, 170, 158)
text(855, 216, 'Render + log', size=20, bold=True)
text(855, 180, 'Linear HDR', size=19)
text(855, 157, 'frames', size=19)
text(855, 120, 'GPU timings', size=19)

box(986, 88, 202, 158)
text(1087, 216, 'Evaluation', size=20, bold=True)
for y, label in zip((180, 157, 129, 106), ('Image error', 'GPU cost', 'Temporal', 'behavior')):
    text(1087, y, label)

box(1004, 284, 166, 49, fill=white, stroke=LINE, radius=6)
text(1087, 314, 'Converged DI', size=17)
text(1087, 293, 'references', size=17)
arrow([(1087, 284), (1087, 246)], dashed=True)

arrow([(172, 167), (210, 167)])
arrow([(395, 167), (417, 167)], head=False)
arrow([(417, 93), (417, 241)], head=False)
for y, *_ in cards:
    center = y+31
    arrow([(417, center), (453, center)])
    arrow([(689, center), (745, center)], head=False)
arrow([(745, 93), (745, 241)], head=False)
arrow([(745, 167), (770, 167)])
arrow([(940, 167), (986, 167)])

text(600, 10, 'Matched scenes, cameras, resolution, and GPU time budgets; repeated independent seeds.', size=16.5)
pdf.showPage()
pdf.save()
print(ROOT / 'pipeline.pdf')
