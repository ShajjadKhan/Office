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
        leftMargin=20,
        rightMargin=20,
        topMargin=16,
        bottomMargin=16
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
        fontSize=13,
        leading=15,
        textColor=colors.HexColor('#0F172A')
    )
    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor('#334155')
    )
    meta_style = ParagraphStyle(
        'DocMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
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
    story.append(Spacer(1, 4))
    
    story.append(Paragraph(company_name.upper(), meta_bold))
    story.append(Paragraph(f"Department: {department}", meta_style))
    story.append(Spacer(1, 8))
    
    header_row = ["SL", "Employee Name"]
    for d in range(1, days_cnt + 1):
        header_row.append(str(d))
    header_row.extend(["Total\nHours", "Work\nDays"])
    
    table_data = [header_row]
    n_real = len(associates)
    
    tot_width = 841.89 - 40  # 801.89 pt
    fixed_widths = 24 + 140 + 36 + 26  # 226 pt
    day_col_width = (tot_width - fixed_widths) / days_cnt
    col_widths = [24, 140] + [day_col_width] * days_cnt + [36, 26]
    
    # Calculate row layout & padding to fit and balance the full page
    target_rows = max(n_real, 10)
    tot_rows = target_rows + 1  # Including header
    if tot_rows <= 11:
        padding = 6.0
        font_sz = 8.0
        hdr_font_sz = 8.5
        spacer_h = 35
    elif tot_rows <= 15:
        padding = 5.0
        font_sz = 7.5
        hdr_font_sz = 8.0
        spacer_h = 30
    else:
        padding = 3.5
        font_sz = 7.0
        hdr_font_sz = 7.5
        spacer_h = 24
        
    t_styles = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), hdr_font_sz),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), font_sz),
        ('TOPPADDING', (0, 0), (-1, -1), padding),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding),
        ('LEFTPADDING', (2, 0), (-1, -1), 0.5),
        ('RIGHTPADDING', (2, 0), (-1, -1), 0.5),
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
        
    # Standard grid lines fill up to target_rows for clean, full-page format
    for r in range(n_real + 1, target_rows + 1):
        table_data.append([str(r), ""] + [""] * days_cnt + ["", ""])
        row_idx += 1
        
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
            {"title": "Director of Finance", "name": ""},
            {"title": "General Manager", "name": ""}
        ]
    if not active_auths:
        active_auths = [{"title": "Department Head", "name": ""}]
        
    n_auths = len(active_auths)
    col_w = tot_width / n_auths
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
        ('FONTSIZE', (0, 1), (-1, 1), 8.5),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1E293B')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
    ]
    if has_names:
        t_sig_styles.extend([
            ('FONTNAME', (0, 2), (-1, 2), 'Helvetica'),
            ('FONTSIZE', (0, 2), (-1, 2), 7.5),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.HexColor('#64748B')),
        ])
    sig_table.setStyle(TableStyle(t_sig_styles))

    story.append(Spacer(1, spacer_h))
    story.append(sig_table)
    
    doc.build(story)
    return file_path

def generate_master_pdf(
    file_path: str,
    month_info: Dict[str, Any],
    associates: List[Dict[str, Any]],
    property_full: str = "Riyadh Marriott Hotel",
    settings: Dict[str, Any] = None,
    stamps: List[Dict[str, Any]] = None,
    authorizers: List[Dict[str, Any]] = None
) -> str:
    doc = SimpleDocTemplate(
        file_path,
        pagesize=landscape(A4),
        leftMargin=16,
        rightMargin=16,
        topMargin=14,
        bottomMargin=14
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
        'MasterDocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=15,
        textColor=colors.HexColor('#0F172A')
    )
    subtitle_style = ParagraphStyle(
        'MasterDocSub',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#334155')
    )
    meta_style = ParagraphStyle(
        'MasterDocMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#475569')
    )
    
    story.append(Paragraph(property_full, title_style))
    story.append(Paragraph("Master Daily Attendance Transaction Report", subtitle_style))
    story.append(Paragraph(f"Transaction Period From  {period_str} — ALL COMPANIES & DEPARTMENTS", meta_style))
    story.append(Spacer(1, 8))
    
    header_row = ["SL", "Associate Name", "Company", "Department"]
    for d in range(1, days_cnt + 1):
        header_row.append(str(d))
    header_row.extend(["Total\nHours", "Work\nDays"])
    
    table_data = [header_row]
    n_assoc = len(associates)
    
    tot_table_width = 841.89 - 32  # 809.89 pt
    fixed_widths = 18 + 125 + 76 + 65 + 32 + 24  # 340 pt
    day_col_width = (tot_table_width - fixed_widths) / days_cnt
    col_widths = [18, 125, 76, 65] + [day_col_width] * days_cnt + [32, 24]
    
    # Calculate padding based on associate count to optimize 1-page full layout
    if n_assoc <= 12:
        padding = 5.5
        font_sz = 7.5
        hdr_font_sz = 8.0
        spacer_h = 35
        target_rows = 12
    elif n_assoc <= 17:
        padding = 4.5
        font_sz = 7.0
        hdr_font_sz = 7.5
        spacer_h = 32
        target_rows = n_assoc
    elif n_assoc <= 22:
        padding = 3.0
        font_sz = 6.5
        hdr_font_sz = 7.0
        spacer_h = 24
        target_rows = n_assoc
    else:
        padding = 3.5
        font_sz = 7.0
        hdr_font_sz = 7.5
        spacer_h = 36
        target_rows = n_assoc
        
    t_styles = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('ALIGN', (2, 1), (3, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), hdr_font_sz),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), font_sz),
        ('TOPPADDING', (0, 0), (-1, -1), padding),
        ('BOTTOMPADDING', (0, 0), (-1, -1), padding),
        ('LEFTPADDING', (4, 0), (-1, -1), 0.5),
        ('RIGHTPADDING', (4, 0), (-1, -1), 0.5),
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
        
        comp_name = assoc.get("company", "Company")
        dept_name = assoc.get("department", "General")
        
        row_vals = [str(idx), assoc["name"], comp_name, dept_name]
        for col_idx, raw_d in enumerate(days_vals, start=4):
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
        
    # If fewer than target_rows, add neat grid rows so the report fills the page
    for r in range(n_assoc + 1, target_rows + 1):
        table_data.append([str(r), "", "", ""] + [""] * days_cnt + ["", ""])
        row_idx += 1
        
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
            {"title": "Director of Finance", "name": ""},
            {"title": "General Manager", "name": ""}
        ]
    if not active_auths:
        active_auths = [{"title": "Department Head", "name": ""}]
        
    n_auths = len(active_auths)
    col_w = tot_table_width / n_auths
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
        ('FONTSIZE', (0, 1), (-1, 1), 8.5),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1E293B')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
    ]
    if has_names:
        t_sig_styles.extend([
            ('FONTNAME', (0, 2), (-1, 2), 'Helvetica'),
            ('FONTSIZE', (0, 2), (-1, 2), 7.5),
            ('TEXTCOLOR', (0, 2), (-1, 2), colors.HexColor('#64748B')),
        ])
    sig_table.setStyle(TableStyle(t_sig_styles))

    story.append(Spacer(1, spacer_h))
    story.append(sig_table)
    
    doc.build(story)
    return file_path
