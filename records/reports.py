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
from reportlab.pdfbase.pdfmetrics import stringWidth


# BSU brand colors
BSU_MAROON = colors.HexColor('#7a1420')
BSU_GOLD = colors.HexColor('#f2a900')

# Must stay in step with STATUS_LEVEL_COLORS in views.py so the exported PDF
# uses the same colours as the on-screen report preview.
LEVEL_HEX = {
    'Low': '#16a34a',       # green
    'Moderate': '#fbbf24',  # yellow
    'High': '#f87171',      # red
    'Critical': '#991b1b',  # dark red
}

LEVEL_COLORS = {level: colors.HexColor(hex_value) for level, hex_value in LEVEL_HEX.items()}

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


def _legend_entry_width(item, font_size):
    """Width one 'Level (range)' entry needs to stay on a single line."""

    return (
        stringWidth(item['level'] + ' ', 'Helvetica-Bold', font_size)
        + stringWidth(f"({item['range']})", 'Helvetica', font_size)
    )


def _legend_font_size(level_legend, available_width):
    """Largest font size that keeps every legend entry on one line."""

    for font_size in (7, 6.5, 6, 5.5):
        needed = sum(_legend_entry_width(item, font_size) for item in level_legend)
        if needed <= available_width:
            return font_size

    return 5.5


def _legend_flowable(level_legend, total_width, styles):
    """The 'Alert Levels' strip shown above the table in the report preview."""

    label_width = 62
    swatch_width = 9
    cell_padding = 6  # LEFTPADDING + RIGHTPADDING on each text cell

    entries = len(level_legend)
    text_space = (
        total_width - label_width - entries * (swatch_width + cell_padding)
    )
    font_size = _legend_font_size(level_legend, text_space)

    # Give each entry the width its own text needs; share the slack evenly.
    # If even the smallest font overflows, scale the columns down together so
    # the wrapping is spread across entries instead of crushing the short ones.
    needed = [_legend_entry_width(item, font_size) for item in level_legend]
    if sum(needed) <= text_space:
        slack = (text_space - sum(needed)) / entries
        text_widths = [width + slack for width in needed]
    else:
        scale = text_space / sum(needed)
        text_widths = [width * scale for width in needed]

    label_style = ParagraphStyle(
        'LegendLabel', parent=styles['Normal'], fontSize=font_size, leading=font_size + 1.5,
        textColor=colors.HexColor('#4b5563'), fontName='Helvetica-Bold',
    )
    text_style = ParagraphStyle(
        'LegendText', parent=styles['Normal'], fontSize=font_size, leading=font_size + 1.5,
        textColor=colors.HexColor('#0f172a'),
    )

    row = [Paragraph('ALERT LEVELS', label_style)]
    widths = [label_width]
    cmds = [
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#cfe3d6')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f7fbf6')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
    ]

    for index, item in enumerate(level_legend):
        swatch_col = len(row)
        row.append('')
        row.append(Paragraph(
            f"<b>{item['level']}</b> "
            f"<font color='#64748b'>({item['range']})</font>",
            text_style,
        ))
        widths += [swatch_width, text_widths[index] + cell_padding]
        cmds.append(('BACKGROUND', (swatch_col, 0), (swatch_col, 0),
                     colors.HexColor(item['color'])))
        cmds.append(('TOPPADDING', (swatch_col, 0), (swatch_col, 0), 4))
        cmds.append(('BOTTOMPADDING', (swatch_col, 0), (swatch_col, 0), 4))
        cmds.append(('LEFTPADDING', (swatch_col, 0), (swatch_col, 0), 0))
        cmds.append(('RIGHTPADDING', (swatch_col, 0), (swatch_col, 0), 0))

    table = Table([row], colWidths=widths)
    table.setStyle(TableStyle(cmds))
    return table


def _waste_by_area_chart(area_totals, area_levels, level_legend, total_width):
    """Bar chart coloured by each area's threshold-derived alert level."""

    top_areas = sorted(area_totals.items(), key=lambda x: x[1], reverse=True)[:8]

    # Laid out bottom-up: area labels, x-axis, bars, legend, title.
    chart_x = 50
    chart_y = 32
    chart_height = 170
    chart_width = total_width - chart_x - 20
    legend_line_height = 14
    legend_rows = -(-len(level_legend) // 2)  # two entries per row
    # Clearance so the tallest bar's value label never runs into the legend.
    legend_bottom = chart_y + chart_height + 16
    title_y = legend_bottom + (legend_rows - 1) * legend_line_height + 20
    drawing = Drawing(total_width, title_y + 14)

    title = 'Waste by Area'
    if len(area_totals) > len(top_areas):
        title += f' (Top {len(top_areas)})'
    drawing.add(String(total_width / 2, title_y, title,
                       fontSize=12, textAnchor='middle', fillColor=BSU_MAROON))

    # Same legend as the preview: colour, level, and the threshold range.
    legend_col_width = (total_width - chart_x) / 2
    for index, item in enumerate(level_legend):
        x = chart_x + (index % 2) * legend_col_width
        y = legend_bottom + (legend_rows - 1 - index // 2) * legend_line_height
        drawing.add(Rect(x, y, 9, 7,
                         fillColor=colors.HexColor(item['color']),
                         strokeColor=colors.HexColor(item['color'])))
        drawing.add(String(x + 13, y, f"{item['level']}  ({item['range']})",
                           fontSize=7, fillColor=colors.HexColor('#334155'),
                           textAnchor='start'))

    drawing.add(Line(chart_x, chart_y, chart_x, chart_y + chart_height,
                     strokeColor=colors.HexColor('#334155')))
    drawing.add(Line(chart_x, chart_y, chart_x + chart_width, chart_y,
                     strokeColor=colors.HexColor('#334155')))

    max_value = max((value for _, value in top_areas), default=0) or 1
    bar_gap = 12
    bar_width = min(28, (chart_width - (len(top_areas) - 1) * bar_gap) / len(top_areas))

    for index, (area_name, amount) in enumerate(top_areas):
        bar_height = (amount / max_value) * chart_height
        bar_x = chart_x + index * (bar_width + bar_gap)
        bar_color = LEVEL_COLORS.get(area_levels.get(area_name), BSU_MAROON)
        label = area_name if len(area_name) <= 12 else area_name[:12] + '...'
        drawing.add(Rect(bar_x, chart_y, bar_width, bar_height,
                         fillColor=bar_color, strokeColor=colors.HexColor('#334155')))
        drawing.add(String(bar_x + bar_width / 2, chart_y - 10, label,
                           fontSize=7, fillColor=colors.HexColor('#334155'),
                           textAnchor='middle'))
        drawing.add(String(bar_x + bar_width / 2, chart_y + bar_height + 4, f'{amount:.0f}',
                           fontSize=7, fillColor=colors.HexColor('#334155'),
                           textAnchor='middle'))

    return drawing


def build_waste_report_pdf(records, report_type, period_label,
                           area_groups=None, level_legend=None):
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
    area_groups = list(area_groups or [])
    level_legend = level_legend or [
        {'level': level, 'range': '', 'color': hex_value}
        for level, hex_value in LEVEL_HEX.items()
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

    col_widths = [70, 68, 42, 46, 52, 46, 38, 30, 78]
    content_width = sum(col_widths)

    story.append(_legend_flowable(level_legend, content_width, styles))
    story.append(Spacer(1, 12))

    # Area totals / levels come from the same grouping the preview renders,
    # so a bar's colour always agrees with its group header.
    area_totals = {g['area']: g['total_bags'] for g in area_groups}
    area_levels = {g['area']: g['alert_level'] for g in area_groups}

    # Table
    header = ['Area', 'Waste Type', 'No. of Bags', 'Alert Level',
              'Janitor', 'Date', 'Time', 'Rating', 'Remarks']
    data = [[Paragraph(h, head_style) for h in header]]

    level_cmds = []
    group_cmds = []
    for group in area_groups:
        area = group['area']
        items = group['records']
        group_level = group['alert_level']
        gidx = len(data)

        # Group header mirrors the preview row: area, record/bag counts, and
        # the level for the area's total under the current thresholds.
        data.append([
            Paragraph(
                f"{area} &nbsp;&mdash;&nbsp; {group['record_count']} record(s), "
                f"{group['total_bags']:.0f} bag(s) total", group_style,
            ), '', '',
            Paragraph(group_level, ParagraphStyle(
                'GroupLevel', parent=cell_style, fontSize=7,
                textColor=LEVEL_TEXT_COLORS.get(group_level, colors.white),
                fontName='Helvetica-Bold', alignment=TA_CENTER)),
        ] + [''] * 5)
        group_cmds.append(('SPAN', (0, gidx), (2, gidx)))
        group_cmds.append(('SPAN', (4, gidx), (-1, gidx)))
        group_cmds.append(('BACKGROUND', (0, gidx), (-1, gidx), colors.HexColor('#e8f2ec')))
        if group_level in LEVEL_COLORS:
            group_cmds.append(('BACKGROUND', (3, gidx), (3, gidx), LEVEL_COLORS[group_level]))

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
        story.append(_waste_by_area_chart(
            area_totals, area_levels, level_legend, content_width,
        ))
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
