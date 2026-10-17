import os
from typing import List, Dict, Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def hex_to_color(hex_str: str, default: colors.Color):
    if not hex_str:
        return default
    try:
        return colors.HexColor(hex_str)
    except Exception:
        return default

class DynamicBottomSpacer(Spacer):
    """
    Dynamically expands to push the signature block toward the bottom of the page
    without exceeding the available page height or triggering an unwanted second page.
    """
    def __init__(self, reserve_height: float, min_space: float = 25.0, max_space: float = 340.0):
        super().__init__(1, min_space)
        self.reserve_height = reserve_height
        self.min_space = min_space
        self.max_space = max_space

    def wrap(self, availWidth, availHeight):
        remaining = availHeight - self.reserve_height
        if remaining > self.min_space:
            self.height = min(remaining, self.max_space)
        else:
            self.height = self.min_space
        return availWidth, self.height

def generate_company_pdf(
    file_path: str,
    property_name: str,
    property_full: str,
    company_name: str,
    department: str,
    month_info: Dict[str, Any],
    associates: List[Dict[str, Any]],
    settings: Dict[str, Any] = None,
    stamps: List[Dict[str, Any]] = None,
    authorizers: List[Dict[str, Any]] = None
):
    doc = SimpleDocTemplate(
        file_path,
        pagesize=landscape(A4),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    days_cnt = month_info["days_in_month"]
    period_str = month_info["period_str"]
    
    # Build color & hour lookups from stamps
    color_config = {}
    stamp_hours = {}
    if stamps:
        for st in stamps:
            code = str(st.get("code", "")).strip().upper()
            bg = hex_to_color(st.get("bg_color"), colors.HexColor("#F1F5F9"))
            txt = hex_to_color(st.get("text_color"), colors.HexColor("#334155"))
            color_config[code] = (bg, txt)
            stamp_hours[code] = float(st.get("hours", 0))
    else:
        stamp_hours = {"8": 8.0, "WO": 8.0, "PH": 8.0, "SL": 8.0, "AL": 0.0, "A": 0.0, "V": 0.0}
        
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=16,
        textColor=colors.HexColor('#0F172A')
    )
    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#334155')
    )
    meta_style = ParagraphStyle(
        'DocMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569')
    )
    meta_bold = ParagraphStyle(
        'DocMetaBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#0F172A')
    )
    
    story.append(Paragraph(property_full, title_style))
    story.append(Paragraph("Daily Attendance Transaction Report", subtitle_style))
    story.append(Paragraph(f"Transaction Period From  {period_str}", meta_style))
    story.append(Spacer(1, 6))
    
    story.append(Paragraph(company_name.upper(), meta_bold))
    story.append(Paragraph(f"Department: {department}", meta_style))
    story.append(Spacer(1, 10))
    
    header_row = ["SL", "Employee Name"]
    for d in range(1, days_cnt + 1):
        header_row.append(str(d))
    header_row.extend(["Total hours", "Work"])
    
    table_data = [header_row]
    
    t_styles = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7.5),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.0),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    
    row_idx = 1
    for idx, assoc in enumerate(associates, start=1):
        days_vals = assoc.get("days", ["8"] * days_cnt)
        
        paid_days = 0
        tot_hrs = 0.0
        for d in days_vals:
            code = str(d).strip().upper()
            h = stamp_hours.get(code, 8.0 if code in ["8", 8] else (float(code) if code.replace('.','',1).isdigit() else 0.0))
            tot_hrs += h
            if h > 0:
                paid_days += 1
                
        tot_hrs_str = str(int(tot_hrs)) if tot_hrs.is_integer() else str(round(tot_hrs, 1))
        
        row_vals = [str(idx), assoc["name"]]
        for col_idx, raw_d in enumerate(days_vals, start=2):
            code = str(raw_d).strip().upper()
            row_vals.append(code)
            if code in color_config:
                bg_col, txt_col = color_config[code]
                t_styles.append(('BACKGROUND', (col_idx, row_idx), (col_idx, row_idx), bg_col))
                t_styles.append(('FONTNAME', (col_idx, row_idx), (col_idx, row_idx), 'Helvetica-Bold'))
                t_styles.append(('TEXTCOLOR', (col_idx, row_idx), (col_idx, row_idx), txt_col))
                
        row_vals.extend([tot_hrs_str, str(paid_days)])
        t_styles.append(('FONTNAME', (-2, row_idx), (-1, row_idx), 'Helvetica-Bold'))
        table_data.append(row_vals)
        row_idx += 1
        
    day_col_width = (790 - 225) / days_cnt
    col_widths = [22, 128] + [day_col_width] * days_cnt + [45, 30]
    
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(t_styles))
    story.append(t)
    
    # Active Authorizers
    if authorizers is not None:
        active_auths = [a for a in authorizers if a.get("is_active", True)]
    else:
        active_auths = [
            {"title": "Department Head", "name": ""},
            {"title": "Director of Human Resource", "name": ""},
            {"title": "Director of Finance", "name": ""}
        ]
    if not active_auths:
        active_auths = [{"title": "Department Head", "name": ""}]
        
    n_auths = len(active_auths)
    tot_sig_width = 780.0
    col_w = tot_sig_width / n_auths
    
    has_names = any(bool(a.get("name", "").strip()) for a in active_auths)
    
    sig_data = [
        ["____________________________"] * n_auths,
        [a.get("title", "Authorizer") for a in active_auths]
    ]
    if has_names:
        sig_data.append([f"({a.get('name', '').strip()})" if a.get('name', '').strip() else "" for a in active_auths])
        
    sig_table = Table(sig_data, colWidths=[col_w] * n_auths)
    t_sig_styles = [
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1E293B')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
    ]
    if has_names:
        t_sig_styles.extend([
            ('FONTNAME', (0, 2), (-1, 2), 'Helvetica'),
            ('FONTSIZE', (0, 2), (-1, 2), 8),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.HexColor('#64748B')),
        ])
    sig_table.setStyle(TableStyle(t_sig_styles))

    # Dynamically position signatures toward the bottom of the page
    _, sig_h = sig_table.wrap(tot_sig_width, 500)
    story.append(DynamicBottomSpacer(reserve_height=sig_h + 10, min_space=25, max_space=340))
    story.append(sig_table)
    
    doc.build(story)
    return file_path
