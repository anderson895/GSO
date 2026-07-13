"""PDF report generation styled with the official Bulacan State University
(GSO) letterhead used across the university's formal documents."""

from io import BytesIO

from django.contrib.staticfiles import finders

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Table, TableStyle,
    Paragraph, Spacer,
)


# BSU brand colors
BSU_MAROON = colors.HexColor('#7a1420')
BSU_GOLD = colors.HexColor('#f2a900')

LEVEL_COLORS = {
    'Low': colors.HexColor('#16a34a'),
    'Moderate': colors.HexColor('#d97706'),
    'High': colors.HexColor('#ea580c'),
    'Critical': colors.HexColor('#991b1b'),
}


def _letterhead_path():
    return finders.find('images/gso_letterhead.png')


def _draw_letterhead(canvas, doc):
    """Draw the full-page BSU letterhead (header seals + Alab BUVSU footer)."""
    path = _letterhead_path()
    if path:
        canvas.drawImage(
            path, 0, 0,
            width=A4[0], height=A4[1],
            mask='auto', preserveAspectRatio=False,
        )


def build_waste_report_pdf(records, report_type, period_label):
    buffer = BytesIO()

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=1.9 * inch,
        bottomMargin=1.95 * inch,
        title='GSO Waste Management Report',
    )

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id='body',
    )
    doc.addPageTemplates([
        PageTemplate(id='letterhead', frames=[frame], onPage=_draw_letterhead),
    ])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReportTitle', parent=styles['Title'],
        fontSize=16, textColor=BSU_MAROON, spaceAfter=2, alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        'ReportSubtitle', parent=styles['Normal'],
        fontSize=10.5, textColor=colors.HexColor('#334155'),
        alignment=TA_CENTER, spaceAfter=2,
    )
    office_style = ParagraphStyle(
        'Office', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#64748b'),
        alignment=TA_CENTER, spaceAfter=14,
    )
    cell_style = ParagraphStyle(
        'Cell', parent=styles['Normal'], fontSize=6.5, leading=8,
    )
    head_style = ParagraphStyle(
        'Head', parent=styles['Normal'], fontSize=7, leading=8.5,
        textColor=colors.white, fontName='Helvetica-Bold',
    )

    story = []
    story.append(Paragraph('General Services Office', subtitle_style))
    story.append(Paragraph('Waste Management Summary Report', title_style))

    report_word = 'Monthly Report' if report_type == 'monthly' else 'Yearly Report'
    story.append(Paragraph(f'{report_word} &mdash; {period_label}', office_style))

    records = list(records)
    total_amount = sum(r.amount or 0 for r in records)

    # Summary line
    summary_style = ParagraphStyle(
        'Summary', parent=styles['Normal'], fontSize=9.5,
        textColor=colors.HexColor('#0f172a'), spaceAfter=12, alignment=TA_CENTER,
    )
    story.append(Paragraph(
        f'<b>Total Records:</b> {len(records)} &nbsp;&nbsp;|&nbsp;&nbsp; '
        f'<b>Total Waste:</b> {total_amount:.2f} kg',
        summary_style,
    ))

    # Table
    header = ['Area', 'Waste Type', 'Amount (kg)', 'Alert Level',
              'Janitor', 'Date', 'Time', 'Rating', 'Remarks']
    data = [[Paragraph(h, head_style) for h in header]]

    level_cmds = []
    for i, r in enumerate(records, start=1):
        level = r.alert_level or '-'
        row = [
            Paragraph(str(r.area), cell_style),
            Paragraph(str(r.waste_type), cell_style),
            Paragraph(f'{r.amount:.2f}' if r.amount is not None else '-', cell_style),
            Paragraph(level, ParagraphStyle(
                'lvl', parent=cell_style, textColor=colors.white,
                fontName='Helvetica-Bold', alignment=TA_CENTER)),
            Paragraph(r.user.username if r.user else 'Unknown', cell_style),
            Paragraph(str(r.date), cell_style),
            Paragraph(str(r.time) if r.time else '-', cell_style),
            Paragraph(str(r.coordinator_rating) if r.coordinator_rating else '-', cell_style),
            Paragraph(r.coordinator_comment or '-', cell_style),
        ]
        data.append(row)
        if level in LEVEL_COLORS:
            level_cmds.append(('BACKGROUND', (3, i), (3, i), LEVEL_COLORS[level]))

    if not records:
        data.append([Paragraph('No records found for this period.', cell_style)] + [''] * 8)

    col_widths = [70, 68, 42, 46, 52, 46, 38, 30, 78]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BSU_MAROON),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 0), (3, -1), 'CENTER'),
        ('ALIGN', (7, 0), (7, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f7f2')]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ] + level_cmds)
    table.setStyle(style)

    story.append(table)
    story.append(Spacer(1, 14))

    note_style = ParagraphStyle(
        'Note', parent=styles['Normal'], fontSize=7.5,
        textColor=colors.HexColor('#64748b'),
    )
    story.append(Paragraph(
        'This report was automatically generated by the BSU Waste Management '
        'Information System.', note_style,
    ))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
