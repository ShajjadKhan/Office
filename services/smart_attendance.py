import calendar
import random
from typing import List, Dict, Any

def get_month_info(year: int, month: int):
    days_in_month = calendar.monthrange(year, month)[1]
    month_name = calendar.month_name[month]
    month_short = calendar.month_abbr[month].upper()
    return {
        "year": year,
        "month": month,
        "days_in_month": days_in_month,
        "month_name": month_name,
        "month_short": month_short,
        "period_str": f"01/{month:02d}/{year} To {days_in_month:02d}/{month:02d}/{year}",
        "label": f"{month_name} {year}"
    }

def generate_default_days(days_in_month: int, off_days_count: int = 4, seed_offset: int = 0) -> List[str]:
    days = ["8"] * days_in_month
    chunk_size = days_in_month // off_days_count
    rng = random.Random(42 + seed_offset)
    
    chosen_indices = set()
    for i in range(off_days_count):
        start = i * chunk_size
        end = (i + 1) * chunk_size - 1 if i < off_days_count - 1 else days_in_month - 1
        possible = [idx for idx in range(start, end + 1) if idx not in chosen_indices]
        if possible:
            chosen = rng.choice(possible)
            chosen_indices.add(chosen)
            
    for idx in chosen_indices:
        days[idx] = "WO"
        
    return days

def calculate_totals(days: List[str], stamps_list: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Build hours lookup map from stamps list
    stamp_hours = {}
    if stamps_list:
        for st in stamps_list:
            c = str(st.get("code", "")).strip().upper()
            stamp_hours[c] = float(st.get("hours", 0))
    else:
        # Fallback default
        stamp_hours = {
            "8": 8.0, "WO": 8.0, "OFF": 8.0, "PH": 8.0, "SL": 8.0,
            "AL": 0.0, "A": 0.0, "V": 0.0
        }
        
    total_hours = 0.0
    paid_days = 0
    
    for d in days:
        val = str(d).strip().upper()
        h = 0.0
        if val in stamp_hours:
            h = stamp_hours[val]
        elif val in ["8", 8]:
            h = 8.0
        elif val.replace('.', '', 1).isdigit():
            h = float(val)
            
        total_hours += h
        if h > 0:
            paid_days += 1
            
    return {
        "work_days": paid_days,
        "total_hours": int(total_hours) if total_hours.is_integer() else round(total_hours, 1)
    }
