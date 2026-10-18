import os
import json
import time
import datetime
import uuid
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def get_workspace_dir(workspace: str = "default") -> str:
    ws = (workspace or "default").strip()
    if ws in ["default", "shajjad"]:
        return DATA_DIR
    return os.path.join(DATA_DIR, 'workspaces', ws)

def get_history_file(workspace: str = "default") -> str:
    ws_dir = get_workspace_dir(workspace)
    os.makedirs(ws_dir, exist_ok=True)
    return os.path.join(ws_dir, 'export_history.json')

def load_history(workspace: str = "default") -> List[Dict[str, Any]]:
    path = get_history_file(workspace)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"Warning loading history: {e}")
            
    # Auto-seed from saved_months if history is currently empty
    seeded = seed_history_from_saved_months(workspace)
    if seeded:
        save_history(seeded, workspace)
        return seeded
    return []

def seed_history_from_saved_months(workspace: str = "default") -> List[Dict[str, Any]]:
    ws_dir = get_workspace_dir(workspace)
    saved_dir = os.path.join(ws_dir, 'saved_months')
    if not os.path.exists(saved_dir):
        return []
        
    assoc_file = os.path.join(ws_dir, 'associates.json')
    if not os.path.exists(assoc_file):
        assoc_file = os.path.join(DATA_DIR, 'associates.json')
    all_associates = []
    if os.path.exists(assoc_file):
        try:
            with open(assoc_file, 'r', encoding='utf-8') as f:
                all_associates = json.load(f) or []
        except Exception:
            pass

    history_items = []
    month_files = sorted(
        [f for f in os.listdir(saved_dir) if f.endswith('.json') and not f.endswith('.bak')],
        reverse=True
    )
    
    for mf in month_files:
        try:
            base = mf.replace('.json', '')
            parts = base.split('_')
            if len(parts) != 2:
                continue
            y = int(parts[0])
            m = int(parts[1])
            m_date = datetime.date(y, m, 1)
            month_name = m_date.strftime("%B %Y")
            
            fpath = os.path.join(saved_dir, mf)
            with open(fpath, 'r', encoding='utf-8') as f:
                c = json.load(f)
                raw_list = c.get("associates", []) if isinstance(c, dict) else (c or [])
                
            active_assocs = []
            for item in raw_list:
                aid = item.get("id")
                a = next((x for x in all_associates if x.get("id") == aid), None)
                if a:
                    active_assocs.append(a)
                    
            if not active_assocs:
                continue
                
            # Master Excel record
            m_time = os.path.getmtime(fpath)
            f_date = datetime.datetime.fromtimestamp(m_time).strftime("%d %b %Y, %I:%M %p")
            history_items.append({
                "id": f"seed_{y}_{m}_master",
                "created_at": datetime.datetime.fromtimestamp(m_time).isoformat(),
                "formatted_date": f_date,
                "action": "master_excel",
                "title": f"Master Excel — All Staff ({len(active_assocs)} Associates)",
                "year": y,
                "month": m,
                "month_name": month_name,
                "group_key": "",
                "company": "All Companies",
                "department": "Master Roster",
                "property": "All Properties",
                "property_full": "All Properties",
                "associates_count": len(active_assocs),
                "associates_summary": ", ".join(a["name"] for a in active_assocs[:5]) + ("..." if len(active_assocs) > 5 else ""),
                "assoc_ids": [a["id"] for a in active_assocs],
                "file_name": f"Attendance All in Excel-{m_date.strftime('%b')}-{y}.xlsx"
            })
            
            # Groups breakdown records
            groups = {}
            for a in active_assocs:
                prop = a.get("property", "RMH")
                comp = a.get("company", "Company")
                dept = a.get("department", "General")
                gkey = f"{prop}_{comp}_{dept}".replace(' ', '_').replace('-', '_')
                if gkey not in groups:
                    groups[gkey] = {
                        "key": gkey,
                        "property": prop,
                        "company": comp,
                        "department": dept,
                        "associates": []
                    }
                groups[gkey]["associates"].append(a)
                
            for g in groups.values():
                history_items.append({
                    "id": f"seed_{y}_{m}_{g['key']}",
                    "created_at": datetime.datetime.fromtimestamp(m_time).isoformat(),
                    "formatted_date": f_date,
                    "action": "excel",
                    "title": f"{g['company']} — {g['department']}",
                    "year": y,
                    "month": m,
                    "month_name": month_name,
                    "group_key": g["key"],
                    "company": g["company"],
                    "department": g["department"],
                    "property": g["property"],
                    "property_full": "Riyadh Marriott Hotel" if g["property"] == "RMH" else g["property"],
                    "associates_count": len(g["associates"]),
                    "associates_summary": ", ".join(a["name"] for a in g["associates"]),
                    "assoc_ids": [a["id"] for a in g["associates"]],
                    "file_name": f"{g['company']} {g['property']}.xlsx"
                })
        except Exception as e:
            print(f"Error seeding history for {mf}: {e}")
            
    return history_items

def save_history(history: List[Dict[str, Any]], workspace: str = "default"):
    path = get_history_file(workspace)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(history[:100], f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving history: {e}")

def record_history_entry(
    action: str,
    title: str,
    year: int,
    month: int,
    workspace: str = "default",
    group_key: Optional[str] = None,
    company: Optional[str] = None,
    department: Optional[str] = None,
    property_code: Optional[str] = None,
    property_full: Optional[str] = None,
    associates_count: int = 0,
    associates_summary: str = "",
    assoc_ids: Optional[List[int]] = None,
    file_name: Optional[str] = None
) -> Dict[str, Any]:
    history = load_history(workspace)
    now = datetime.datetime.now()
    month_name = datetime.date(year, month, 1).strftime("%B %Y")
    
    item_id = f"hist_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    
    entry = {
        "id": item_id,
        "created_at": now.isoformat(),
        "formatted_date": now.strftime("%d %b %Y, %I:%M %p"),
        "action": action, # 'excel', 'master_excel', 'pdf', 'save', 'all_zip'
        "title": title,
        "year": year,
        "month": month,
        "month_name": month_name,
        "group_key": group_key or "",
        "company": company or "",
        "department": department or "",
        "property": property_code or "",
        "property_full": property_full or property_code or "",
        "associates_count": associates_count,
        "associates_summary": associates_summary,
        "assoc_ids": assoc_ids or [],
        "file_name": file_name or ""
    }
    
    # Avoid exact duplicate logs in short window
    filtered = []
    for h in history:
        if (h.get("action") == action and 
            h.get("group_key") == (group_key or "") and 
            h.get("year") == year and 
            h.get("month") == month):
            continue
        filtered.append(h)
        
    filtered.insert(0, entry)
    save_history(filtered, workspace)
    return entry

def delete_history_entry(item_id: str, workspace: str = "default") -> bool:
    history = load_history(workspace)
    new_hist = [h for h in history if h.get("id") != item_id]
    if len(new_hist) != len(history):
        save_history(new_hist, workspace)
        return True
    return False

def clear_all_history_entries(workspace: str = "default"):
    save_history([], workspace)
