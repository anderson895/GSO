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
from reportlab.graphics.shapes import Drawing, String, Rect, Line


# BSU brand colors
BSU_MAROON = colors.HexColor('#7a1420')
BSU_GOLD = colors.HexColor('#f2a900')

LEVEL_COLORS = {
    'Low': colors.HexColor('#16a34a'),       # green
    'Moderate': colors.HexColor('#fbbf24'),  # yellow
    'High': colors.HexColor('#f87171'),      # red
    'Critical': colors.HexColor('#991b1b'),  # dark red
}

LEVEL_ORDER = {
    'Low': 0,
    'Moderate': 1,
    'High': 2,
    'Critical': 3,
}

# Text color per level (yellow needs dark text for readability).
LEVEL_TEXT_COLORS = {
    'Low': colors.white,
    'Moderate': colors.HexColor('#0f172a'),
    'High': colors.white,
    'Critical': colors.white,
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
            preserveAspectRatio=False,
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
    group_style = ParagraphStyle(
        'GroupHead', parent=styles['Normal'], fontSize=7.5, leading=9,
        textColor=BSU_MAROON, fontName='Helvetica-Bold',
    )

    story = []
    story.append(Paragraph('General Services Office', subtitle_style))
    story.append(Paragraph('Waste Management Summary Report', title_style))

    if report_type == 'daily':
        report_word = 'Daily Report'
    elif report_type == 'weekly':
        report_word = 'Weekly Report'
    elif report_type == 'monthly':
        report_word = 'Monthly Report'
    else:
        report_word = 'Yearly Report'

    story.append(Paragraph(f'{report_word} &mdash; {period_label}', office_style))

    records = list(records)
    total_amount = sum(r.amount or 0 for r in records)

    # Group records per area (sorted so each area appears together).
    from itertools import groupby
    sorted_records = sorted(records, key=lambda r: str(r.area))
    area_groups = [
        (area, list(items))
        for area, items in groupby(sorted_records, key=lambda r: str(r.area))
    ]

    # Summary line
    summary_style = ParagraphStyle(
        'Summary', parent=styles['Normal'], fontSize=9.5,
        textColor=colors.HexColor('#0f172a'), spaceAfter=12, alignment=TA_CENTER,
    )
    story.append(Paragraph(
        f'<b>Total Records:</b> {len(records)} &nbsp;&nbsp;|&nbsp;&nbsp; '
        f'<b>Areas:</b> {len(area_groups)} &nbsp;&nbsp;|&nbsp;&nbsp; '
        f'<b>Total Bags:</b> {total_amount:.0f}',
        summary_style,
    ))

    area_totals = {}
    area_alerts = {}
    for record in records:
        area_name = str(record.area)
        area_totals[area_name] = area_totals.get(area_name, 0) + (record.amount or 0)
        current_alert = area_alerts.get(area_name, 'Low')
        if LEVEL_ORDER.get(record.alert_level, 0) > LEVEL_ORDER.get(current_alert, 0):
            area_alerts[area_name] = record.alert_level

    if area_totals:
        sorted_areas = sorted(area_totals.items(), key=lambda x: x[1], reverse=True)
        top_areas = sorted_areas[:8]
        labels = [label if len(label) <= 12 else label[:12] + '...' for label, _ in top_areas]
        values = [[value for _, value in top_areas]]
        colors_for_bars = [LEVEL_COLORS.get(area_alerts.get(area, 'Low'), BSU_MAROON) for area, _ in top_areas]

    # Table
    header = ['Area', 'Waste Type', 'No. of Bags', 'Alert Level',
              'Janitor', 'Date', 'Time', 'Rating', 'Remarks']
    data = [[Paragraph(h, head_style) for h in header]]

    level_cmds = []
    group_cmds = []
    for area, items in area_groups:
        subtotal = sum(r.amount or 0 for r in items)
        gidx = len(data)
        data.append([
            Paragraph(
                f'{area} &nbsp;&mdash;&nbsp; {len(items)} record(s), '
                f'{subtotal:.0f} bag(s) total', group_style,
            )
        ] + [''] * 8)
        group_cmds.append(('SPAN', (0, gidx), (-1, gidx)))
        group_cmds.append(('BACKGROUND', (0, gidx), (-1, gidx), colors.HexColor('#e8f2ec')))

        for r in items:
            i = len(data)
            level = r.alert_level or '-'
            row = [
                Paragraph(str(r.area), cell_style),
                Paragraph(str(r.waste_type), cell_style),
                Paragraph(f'{r.amount:.0f}' if r.amount is not None else '-', cell_style),
                Paragraph(level, ParagraphStyle(
                    'lvl', parent=cell_style,
                    textColor=LEVEL_TEXT_COLORS.get(level, colors.white),
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
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ] + group_cmds + level_cmds)
    table.setStyle(style)

    story.append(table)
    story.append(Spacer(1, 14))

    if area_totals:
        drawing = Drawing(450, 280)
        drawing.add(String(225, 255, 'Waste by Area', fontSize=12, textAnchor='middle', fillColor=BSU_MAROON))

        legend_x = 50
        legend_y = 235
        for level in ['Low', 'Moderate', 'High', 'Critical']:
            drawing.add(Rect(legend_x, legend_y, 10, 6, fillColor=LEVEL_COLORS[level], strokeColor=LEVEL_COLORS[level]))
            drawing.add(String(legend_x + 14, legend_y, level, fontSize=7, fillColor=colors.HexColor('#334155'), textAnchor='start'))
            legend_x += 70

        max_value = max(values[0]) if values[0] else 1
        chart_height = 170
        chart_width = 340
        chart_x = 50
        chart_y = 25
        bar_gap = 12
        bar_width = min(28, (chart_width - (len(values[0]) - 1) * bar_gap) / len(values[0]))

        drawing.add(Line(chart_x, chart_y, chart_x, chart_y + chart_height, strokeColor=colors.HexColor('#334155')))
        drawing.add(Line(chart_x, chart_y, chart_x + chart_width, chart_y, strokeColor=colors.HexColor('#334155')))

        for idx, (area_name, amount) in enumerate(top_areas):
            bar_height = (amount / max_value) * chart_height if max_value else 0
            bar_x = chart_x + idx * (bar_width + bar_gap)
            bar_y = chart_y
            bar_color = LEVEL_COLORS.get(area_alerts.get(area_name, 'Low'), BSU_MAROON)
            drawing.add(Rect(bar_x, bar_y, bar_width, bar_height, fillColor=bar_color, strokeColor=colors.HexColor('#000000')))
            drawing.add(String(bar_x + bar_width / 2, bar_y - 10, labels[idx], fontSize=7, fillColor=colors.HexColor('#334155'), textAnchor='middle'))
            drawing.add(String(bar_x + bar_width / 2, bar_y + bar_height + 4, f'{amount:.0f}', fontSize=7, fillColor=colors.HexColor('#334155'), textAnchor='middle'))

        story.append(drawing)
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
