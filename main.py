import os
import io
import json
import calendar
import zipfile
import hmac
from urllib.parse import quote, parse_qs
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from fastapi import FastAPI, Request, Query, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from services.smart_attendance import get_month_info, generate_default_days, calculate_totals
from services.excel_generator import generate_company_excel, generate_master_excel
from services.pdf_generator import generate_company_pdf, generate_master_pdf
from services.history_service import (
    load_history,
    record_history_entry,
    delete_history_entry,
    clear_all_history_entries
)
from services.auth_service import (
    authenticate_user,
    create_session,
    get_session_user,
    revoke_session,
    get_or_create_api_key,
    get_user,
    get_user_role,
    get_user_workspace,
    list_users_safe,
    list_workspaces,
    create_or_update_user,
    toggle_user_status,
    delete_user_account,
    COOKIE_NAME
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
SAVED_DIR = os.path.join(DATA_DIR, 'saved_months')
EXPORTS_DIR = os.path.join(BASE_DIR, 'exports')

os.makedirs(SAVED_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

app = FastAPI(title="officework", description="Monthly Salary & Attendance Formatter")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    
    # Public routes
    if path in ["/login", "/logout"] or path.startswith("/static"):
        return await call_next(request)
        
    # Check session cookie
    token = request.cookies.get(COOKIE_NAME)
    user = get_session_user(token) if token else None
    
    # Check API Key (for desktop script & automation)
    if not user:
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if api_key and hmac.compare_digest(api_key, get_or_create_api_key()):
            user = "api_user"
            
    if user:
        request.state.user = user
        return await call_next(request)
        
    # Unauthenticated
    if path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "Authentication required. Please sign in."})
        
    # Redirect to login page
    next_url = request.url.path
    if request.url.query:
        next_url += f"?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(next_url)}", status_code=302)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, 'templates'))
static_dir = os.path.join(BASE_DIR, 'static')
if os.path.exists(static_dir):
    app.mount('/static', StaticFiles(directory=static_dir), name='static')

# ================= Workspace Resolution & Data Access Helpers =================

def get_workspace_dir(workspace: str = "default") -> str:
    if not workspace or workspace in ["default", "shajjad"]:
        return DATA_DIR
    ws_dir = os.path.join(DATA_DIR, "workspaces", workspace)
    os.makedirs(ws_dir, exist_ok=True)
    os.makedirs(os.path.join(ws_dir, "saved_months"), exist_ok=True)
    return ws_dir

def get_current_workspace(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not user or user == "api_user":
        return "default"
    
    u = get_user(user)
    if not u:
        return "default"
        
    is_admin = u.get("role") == "admin" or user in ["shajjad", "admin"]
    if is_admin:
        # Admin can view/manage colleague workspaces via query param or switcher cookie
        ws_param = request.query_params.get("ws")
        if ws_param and ws_param.strip():
            return ws_param.strip()
        cookie_ws = request.cookies.get("ow_active_ws")
        if cookie_ws and cookie_ws.strip() and cookie_ws.strip() not in ["default", "shajjad"]:
            return cookie_ws.strip()
        return "admin"
    else:
        # Colleague is strictly isolated to their own department workspace
        return u.get("workspace", user)

def load_json(filename: str, default: Any, workspace: str = "default") -> Any:
    ws_dir = get_workspace_dir(workspace)
    path = os.path.join(ws_dir, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading {filename} in workspace {workspace}: {e}")
    return default

def save_json(filename: str, data: Any, workspace: str = "default"):
    ws_dir = get_workspace_dir(workspace)
    os.makedirs(ws_dir, exist_ok=True)
    path = os.path.join(ws_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_associates(workspace: str = "default") -> List[Dict[str, Any]]:
    return load_json('associates.json', [], workspace=workspace)

def load_companies(workspace: str = "default") -> List[str]:
    default = ["Dar Al Ishraq", "Dar Al Wafa", "Nasim Alenjaz", "Sama Al riyadha", "Soundline", "Work Force", "Qasir AL Nokba", "Tamkeen"] if workspace in ["default", "shajjad"] else []
    return load_json('companies.json', default, workspace=workspace)

STANDARD_PROPERTIES: List[Dict[str, str]] = [
    {"code": "MEA", "name": "Marriott Executive Apartments"},
    {"code": "RMH", "name": "Riyadh Marriott Hotel"},
    {"code": "Housing", "name": "Staff Housing"}
]

STANDARD_PROPERTY_MAP: Dict[str, str] = {
    "MEA": "Marriott Executive Apartments",
    "RMH": "Riyadh Marriott Hotel",
    "HOUSING": "Staff Housing",
    "MARRIOTT EXECUTIVE APARTMENTS": "Marriott Executive Apartments",
    "RIYADH MARRIOTT HOTEL": "Riyadh Marriott Hotel",
    "STAFF HOUSING": "Staff Housing",
    "AL WIZARAT": "Marriott Executive Apartments",
    "AL-WIZARAT": "Marriott Executive Apartments",
    "WIZARAT": "Marriott Executive Apartments",
    "HQ": "Riyadh Marriott Hotel"
}

def resolve_property_full_name(prop: str, props_map: Dict[str, str] = None) -> str:
    if not prop:
        return "Marriott Executive Apartments"
    clean = str(prop).strip()
    upper = clean.upper()
    
    # 1. Check custom properties map (by exact key or uppercase key)
    if props_map:
        if prop in props_map:
            return props_map[prop]
        for k, v in props_map.items():
            if str(k).strip().upper() == upper:
                return v
            if str(v).strip().upper() == upper:
                return v
                
    # 2. Check standard properties map
    if upper in STANDARD_PROPERTY_MAP:
        return STANDARD_PROPERTY_MAP[upper]
        
    # 3. If prop already contains descriptive terms
    if any(term in upper for term in ["MARRIOTT", "HOTEL", "APARTMENT", "HOUSING"]):
        return clean
        
    # 4. Return clean code / name without ever appending " Property"
    return clean

def load_properties(workspace: str = "default") -> List[Dict[str, Any]]:
    props = load_json('properties.json', None, workspace=workspace)
    if not props or len(props) == 0:
        return [dict(p) for p in STANDARD_PROPERTIES]
    return props

UNIVERSAL_STAMPS: List[Dict[str, Any]] = [
    {"code": "8", "name": "Regular Work", "hours": 8, "bg_color": "#F1F5F9", "text_color": "#334155"},
    {"code": "WO", "name": "Weekly Off", "hours": 8, "bg_color": "#FEF3C7", "text_color": "#B45309"},
    {"code": "PH", "name": "Public Holiday", "hours": 8, "bg_color": "#D1FAE5", "text_color": "#065F46"},
    {"code": "SL", "name": "Sick Leave", "hours": 8, "bg_color": "#E0F2FE", "text_color": "#0369A1"},
    {"code": "AL", "name": "Annual Leave", "hours": 0, "bg_color": "#E0E7FF", "text_color": "#3730A3"},
    {"code": "A", "name": "Absent", "hours": 0, "bg_color": "#FEE2E2", "text_color": "#991B1B"},
    {"code": "V", "name": "Vacation", "hours": 0, "bg_color": "#FFE4E6", "text_color": "#9F1239"}
]

def load_universal_stamps() -> List[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, "stamps.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                stamps = json.load(f)
                if stamps and isinstance(stamps, list) and len(stamps) > 0:
                    return stamps
        except Exception as e:
            print(f"Error reading universal stamps: {e}")
    return [dict(s) for s in UNIVERSAL_STAMPS]

def save_universal_stamps(stamps: List[Dict[str, Any]]):
    path = os.path.join(DATA_DIR, "stamps.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stamps, f, indent=2)

def load_stamps(workspace: str = "default") -> List[Dict[str, Any]]:
    if workspace in ["admin", "default", "shajjad"]:
        return load_universal_stamps()
    stamps = load_json('stamps.json', None, workspace=workspace)
    if stamps is None or len(stamps) == 0:
        return load_universal_stamps()
    return stamps

def load_authorizers(workspace: str = "default") -> List[Dict[str, Any]]:
    default = [
        {"id": 1, "title": "Department Head", "name": "", "is_active": True},
        {"id": 2, "title": "Director of Human Resource", "name": "", "is_active": True},
        {"id": 3, "title": "Director of Finance", "name": "", "is_active": True},
        {"id": 4, "title": "General Manager", "name": "Eng. Khalid Al-Otaibi", "is_active": True}
    ] if workspace in ["default", "shajjad"] else []
    return load_json('authorizers.json', default, workspace=workspace)

def load_departments(workspace: str = "default") -> List[Dict[str, str]]:
    deps = load_json('departments.json', None, workspace=workspace)
    if deps and isinstance(deps, list) and len(deps) > 0:
        return deps
    custom = load_json('default_settings.json', None, workspace=workspace)
    if custom and isinstance(custom, dict) and "department_names" in custom:
        dnames = custom["department_names"]
        if isinstance(dnames, dict) and len(dnames) > 0:
            res = [{"code": str(k), "name": str(v)} for k, v in dnames.items()]
            save_json('departments.json', res, workspace=workspace)
            return res
    dept_name = "Hotel Engineering"
    if workspace not in ["default", "shajjad"]:
        u = get_user(workspace)
        if u and u.get("department"):
            dept_name = u["department"]
    default_deps = [{"code": "0430", "name": dept_name}]
    save_json('departments.json', default_deps, workspace=workspace)
    return default_deps

def save_departments(departments: List[Dict[str, str]], workspace: str = "default"):
    save_json('departments.json', departments, workspace=workspace)
    settings = load_json('default_settings.json', {}, workspace=workspace) or {}
    dept_names = {d["code"]: d["name"] for d in departments if isinstance(d, dict) and "code" in d}
    settings["department_names"] = dept_names
    save_json('default_settings.json', settings, workspace=workspace)

def load_settings(workspace: str = "default") -> Dict[str, Any]:
    custom = load_json('default_settings.json', None, workspace=workspace)
    if not custom or not isinstance(custom, dict):
        custom = {}
    props_list = load_properties(workspace=workspace)
    props_map = {p["code"]: p["name"] for p in props_list if isinstance(p, dict)}
    for std_code, std_name in STANDARD_PROPERTY_MAP.items():
        if std_code not in props_map:
            props_map[std_code] = std_name
    depts_list = load_departments(workspace=workspace)
    dept_map = {d["code"]: d["name"] for d in depts_list if isinstance(d, dict)}
    custom["properties"] = props_map
    custom["department_names"] = dept_map
    return custom

# ================= Monthly Persistence Helpers =================

def get_month_file_path(year: int, month: int, workspace: str = "default") -> str:
    ws_dir = get_workspace_dir(workspace)
    saved_dir = os.path.join(ws_dir, 'saved_months')
    os.makedirs(saved_dir, exist_ok=True)
    return os.path.join(saved_dir, f"{year}_{month:02d}.json")

def read_month_file(year: int, month: int, workspace: str = "default") -> Optional[Dict[str, Any]]:
    path = get_month_file_path(year, month, workspace=workspace)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = json.load(f)
                if isinstance(content, dict):
                    return content
                elif isinstance(content, list):
                    return {"associates": content, "authorizer_ids": None}
        except Exception as e:
            print(f"Warning reading month file: {e}")
    return None

def write_month_file(year: int, month: int, data: Any, workspace: str = "default"):
    path = get_month_file_path(year, month, workspace=workspace)
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                c = json.load(f)
                if isinstance(c, dict):
                    existing = c
        except Exception:
            pass

    if isinstance(data, list):
        existing["associates"] = data
        data = existing
    elif isinstance(data, dict):
        for k, v in existing.items():
            if k not in data:
                data[k] = v

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_month_data(year: int, month: int, workspace: str = "default"):
    all_associates = load_associates(workspace=workspace)
    stamps = load_stamps(workspace=workspace)
    authorizers = load_authorizers(workspace=workspace)
    settings = load_settings(workspace=workspace)
    month_info = get_month_info(year, month)
    days_cnt = month_info["days_in_month"]
    
    saved_content = read_month_file(year, month, workspace=workspace)
    active_associates = []
    if saved_content:
        raw_list = saved_content.get("associates", []) if isinstance(saved_content, dict) else saved_content
        if isinstance(raw_list, list):
            for item in raw_list:
                aid = item.get("id")
                if aid is not None:
                    assoc = next((a for a in all_associates if a["id"] == aid), None)
                    if assoc:
                        days = item.get("days", [])
                        if len(days) != days_cnt:
                            days = (list(days) + ["8"] * days_cnt)[:days_cnt]
                        totals = calculate_totals(days, stamps_list=stamps)
                        entry = dict(assoc)
                        entry["days"] = days
                        entry.update(totals)
                        active_associates.append(entry)
        
    # Grouped reports for active associates
    groups_dict = {}
    props = settings.get("properties", {})
    depts = settings.get("department_names", {})
    
    for assoc in active_associates:
        prop = assoc.get("property", "RMH")
        comp = assoc.get("company", "Company")
        dept_code = assoc.get("department", "0430")
        key = f"{prop}_{comp}_{dept_code}".replace(' ', '_').replace('-', '_')
        
        if key not in groups_dict:
            dept_title = depts.get(dept_code)
            if not dept_title:
                dept_title = depts.get("0430", "Department")
            prop_full = resolve_property_full_name(prop, props)
            groups_dict[key] = {
                "key": key,
                "property": prop,
                "property_full": prop_full,
                "company": comp,
                "department": dept_title,
                "department_code": dept_code,
                "associates": []
            }
        groups_dict[key]["associates"].append(assoc)
        
    groups = list(groups_dict.values())
    
    return {
        "month_info": month_info,
        "active_associates": active_associates,
        "all_associates": all_associates,
        "authorizers": authorizers,
        "all_authorizers": authorizers,
        "groups": groups,
        "settings": settings,
        "stamps": stamps,
        "companies": load_companies(workspace=workspace),
        "properties": load_properties(workspace=workspace),
        "departments": load_departments(workspace=workspace)
    }

# ================= Routes & Views =================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    token = request.cookies.get(COOKIE_NAME)
    if token and get_session_user(token):
        return RedirectResponse(url=next or "/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "request": request,
            "next_url": next or "/",
            "error": None,
            "current_year": datetime.now().year
        }
    )

@app.post("/login")
async def login_post(request: Request):
    body_bytes = await request.body()
    form_data = parse_qs(body_bytes.decode('utf-8'))
    username = form_data.get("username", [""])[0].strip()
    password = form_data.get("password", [""])[0]
    remember = form_data.get("remember", [""])[0]
    next_url = form_data.get("next", ["/"])[0]
    
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,
                "next_url": next_url or "/",
                "username": username,
                "error": "Invalid username or password. Please try again.",
                "current_year": datetime.now().year
            },
            status_code=401
        )
        
    duration = 30 if remember else 1
    token = create_session(user["username"], duration_days=duration)
    
    target_url = next_url if (next_url and next_url.startswith("/") and not next_url.startswith("//")) else "/"
    response = RedirectResponse(url=target_url, status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=duration * 86400,
        httponly=True,
        samesite="lax",
        path="/"
    )
    user_ws = user.get("workspace", user.get("username", "default"))
    if user.get("role") == "admin" or user.get("username") in ["shajjad", "admin"]:
        user_ws = "admin"
    response.set_cookie(
        key="ow_active_ws",
        value=user_ws,
        max_age=duration * 86400,
        httponly=False,
        samesite="lax",
        path="/"
    )
    return response

@app.get("/logout")
async def logout_endpoint(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        revoke_session(token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME, path="/")
    response.delete_cookie("ow_active_ws", path="/")
    return response

@app.get("/", response_class=HTMLResponse)
async def dashboard_view(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None),
    group: Optional[str] = Query(default=None)
):
    current_username = getattr(request.state, "user", "shajjad")
    u = get_user(current_username)
    is_admin = bool(u and (u.get("role") == "admin" or current_username in ["shajjad", "admin"]))
    
    active_ws = get_current_workspace(request)
    if is_admin:
        if ws and ws.strip():
            target = ws.strip()
            target_u = get_user(target)
            if target_u and target_u.get("workspace"):
                active_ws = target_u["workspace"]
            else:
                active_ws = target
        else:
            cookie_ws = request.cookies.get("ow_active_ws")
            if cookie_ws and cookie_ws.strip() and cookie_ws.strip() not in ["default", "shajjad"]:
                active_ws = cookie_ws.strip()
            else:
                active_ws = "admin"
    else:
        active_ws = u.get("workspace", current_username) if u else "default"

    # ================= MASTER ADMIN PORTAL VIEW (ZERO DEPARTMENTAL CLUTTER) =================
    if is_admin and active_ws in ["admin", "default", "shajjad"]:
        user_display_name = u.get("name", current_username) if u else current_username
        response = templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "request": request,
                "current_user": current_username,
                "current_user_name": user_display_name,
                "is_admin": True,
                "all_users": list_users_safe(),
                "workspaces_list": list_workspaces(),
                "universal_stamps": load_universal_stamps()
            }
        )
        response.set_cookie(key="ow_active_ws", value="admin", max_age=30*86400, httponly=False, samesite="lax", path="/")
        return response

    # ================= DEPARTMENT TIMESHEET VIEW =================
    data = get_month_data(year, month, workspace=active_ws)
    month_names = {i: calendar.month_name[i] for i in range(1, 13)}
    
    user_display_name = u.get("name", current_username) if u else current_username
    user_dept = u.get("department", "Department") if u else "Department"
    
    ws_list = list_workspaces() if is_admin else []
    active_ws_info = next((w for w in ws_list if w["id"] == active_ws), None)
    active_ws_title = active_ws_info["department"] if active_ws_info else (user_dept if not is_admin else active_ws)
    
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "current_user": current_username,
            "current_user_name": user_display_name,
            "current_user_dept": user_dept,
            "is_admin": is_admin,
            "active_workspace": active_ws,
            "active_workspace_title": active_ws_title,
            "workspaces_list": ws_list,
            "all_users": list_users_safe() if is_admin else [],
            "current_year": year,
            "current_month": month,
            "month_info": data["month_info"],
            "month_names": month_names,
            "associates": data["active_associates"],
            "all_associates": data["all_associates"],
            "authorizers": data["authorizers"],
            "all_authorizers": data["all_authorizers"],
            "groups": data["groups"],
            "settings": data["settings"],
            "companies": data["companies"],
            "properties": data["properties"],
            "departments": data["departments"],
            "stamps": data["stamps"],
            "initial_group": (group or "").strip(),
            "history": load_history(workspace=active_ws)
        }
    )
    if is_admin and ws and ws.strip():
        response.set_cookie(key="ow_active_ws", value=active_ws, max_age=30*86400, httponly=False, samesite="lax", path="/")
    return response

@app.get("/print/{group_key}", response_class=HTMLResponse)
async def print_report_view(
    request: Request,
    group_key: str,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    target_group = next((g for g in data["groups"] if g["key"] == group_key), None)
    if not target_group:
        raise HTTPException(status_code=404, detail="Report group not found for this month")
        
    response = templates.TemplateResponse(
        request=request,
        name="report_print.html",
        context={
            "request": request,
            "property_name": target_group["property"],
            "property_full": target_group["property_full"],
            "company_name": target_group["company"],
            "department": target_group["department"],
            "month_info": data["month_info"],
            "associates": target_group["associates"],
            "settings": data["settings"],
            "stamps": data["stamps"],
            "authorizers": data["authorizers"]
        }
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response

@app.post("/api/save-month")
async def save_month_endpoint(
    request: Request,
    year: int = Query(...),
    month: int = Query(...),
    ws: Optional[str] = Query(default=None),
    payload: Any = Body(...)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    write_month_file(year, month, payload, workspace=target_ws)
    try:
        d = get_month_data(year, month, workspace=target_ws)
        active_list = d.get("active_associates", [])
        cnt = len(active_list)
        record_history_entry(
            action="save",
            title=f"Saved Attendance Grid ({cnt} Staff)",
            year=year,
            month=month,
            workspace=target_ws,
            group_key="",
            company="All Companies",
            department="Roster Save",
            property_code="All",
            property_full="All Properties",
            associates_count=cnt,
            associates_summary=", ".join(a["name"] for a in active_list[:5]) + ("..." if cnt > 5 else ""),
            assoc_ids=[a["id"] for a in active_list],
            file_name=f"{year}_{month:02d}.json"
        )
    except Exception as e:
        print(f"Warning recording history on save: {e}")
    return {"success": True, "message": f"Saved attendance for {year}-{month:02d}"}

# ================= Quick Schedule Entry & Month Roster Endpoints =================

@app.post("/api/month/quick-entry")
async def month_quick_entry(request: Request, payload: Dict[str, Any] = Body(...)):
    ws = payload.get("ws") or request.query_params.get("ws") or get_current_workspace(request)
    year = int(payload.get("year", 2026))
    month = int(payload.get("month", 10))
    assoc_id = payload.get("assoc_id")
    if assoc_id is None:
        raise HTTPException(status_code=400, detail="Associate ID is required")
    assoc_id = int(assoc_id)
    
    entries = payload.get("entries", [])
    month_info = get_month_info(year, month)
    days_cnt = month_info["days_in_month"]
    
    saved_content = read_month_file(year, month, workspace=ws) or {}
    raw_list = saved_content.get("associates", []) if isinstance(saved_content, dict) else (saved_content or [])

    # If associate already exists on the sheet, preserve their existing days and only update the specified entries!
    existing_entry = next((item for item in raw_list if item.get("id") == assoc_id), None)
    if existing_entry and isinstance(existing_entry.get("days"), list) and len(existing_entry["days"]) == days_cnt:
        days = list(existing_entry["days"])
    else:
        days = ["8"] * days_cnt

    for e in entries:
        try:
            d = int(e.get("day", 0))
            st = str(e.get("stamp", "WO")).strip().upper()
            if 1 <= d <= days_cnt and st:
                days[d - 1] = st
        except (ValueError, TypeError):
            continue
            
    updated = False
    new_list = []
    for item in raw_list:
        if item.get("id") == assoc_id:
            new_list.append({"id": assoc_id, "days": days})
            updated = True
        else:
            new_list.append(item)
            
    if not updated:
        new_list.append({"id": assoc_id, "days": days})
        
    write_month_file(year, month, {"associates": new_list}, workspace=ws)
    return {"success": True, "message": "Associate schedule saved to sheet"}

@app.post("/api/month/remove-associate")
@app.post("/api/month/bulk-remove-associates")
async def month_remove_associate(request: Request, payload: Dict[str, Any] = Body(...)):
    ws = payload.get("ws") or request.query_params.get("ws") or get_current_workspace(request)
    year = int(payload.get("year", 2026))
    month = int(payload.get("month", 10))
    
    ids_to_remove = set()
    assoc_ids = payload.get("assoc_ids")
    if assoc_ids is not None and isinstance(assoc_ids, list):
        for aid in assoc_ids:
            try:
                ids_to_remove.add(int(aid))
            except (ValueError, TypeError):
                continue
    elif payload.get("assoc_id") is not None:
        try:
            ids_to_remove.add(int(payload.get("assoc_id")))
        except (ValueError, TypeError):
            pass

    if not ids_to_remove:
        raise HTTPException(status_code=400, detail="Associate ID(s) required")
    
    saved_content = read_month_file(year, month, workspace=ws) or {}
    raw_list = saved_content.get("associates", []) if isinstance(saved_content, dict) else (saved_content or [])
    
    new_list = [item for item in raw_list if item.get("id") not in ids_to_remove]
    write_month_file(year, month, {"associates": new_list}, workspace=ws)
    return {
        "success": True,
        "message": f"{len(ids_to_remove)} associate(s) removed from sheet",
        "removed_ids": list(ids_to_remove),
        "count": len(ids_to_remove)
    }

@app.post("/api/employees/bulk-delete")
async def bulk_delete_employees(request: Request, payload: Dict[str, Any] = Body(...)):
    ws = get_current_workspace(request)
    ids = payload.get("ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="Employee IDs required")
    ids_set = set()
    for x in ids:
        try:
            ids_set.add(int(x))
        except (ValueError, TypeError):
            continue
    associates = load_associates(workspace=ws)
    associates = [a for a in associates if a.get("id") not in ids_set]
    save_json('associates.json', associates, workspace=ws)
    return {"success": True, "message": f"{len(ids_set)} associates deleted", "associates": associates}

# ================= Configuration & Master Data Endpoints =================

@app.get("/api/config")
async def get_config(request: Request):
    ws = get_current_workspace(request)
    return {
        "associates": load_associates(workspace=ws),
        "companies": load_companies(workspace=ws),
        "properties": load_properties(workspace=ws),
        "departments": load_departments(workspace=ws),
        "stamps": load_stamps(workspace=ws),
        "authorizers": load_authorizers(workspace=ws)
    }

@app.post("/api/employees")
async def save_employee(request: Request, emp: Dict[str, Any] = Body(...)):
    ws = get_current_workspace(request)
    associates = load_associates(workspace=ws)
    emp_id = emp.get("id")
    if emp_id:
        found = False
        for i, a in enumerate(associates):
            if a.get("id") == emp_id:
                associates[i] = emp
                found = True
                break
        if not found:
            associates.append(emp)
    else:
        new_id = max([a.get("id", 0) for a in associates], default=0) + 1
        emp["id"] = new_id
        associates.append(emp)
    save_json('associates.json', associates, workspace=ws)
    return {"success": True, "employee": emp, "associates": associates}

@app.delete("/api/employees/{emp_id}")
async def delete_employee(request: Request, emp_id: int):
    ws = get_current_workspace(request)
    associates = load_associates(workspace=ws)
    associates = [a for a in associates if a.get("id") != emp_id]
    save_json('associates.json', associates, workspace=ws)
    return {"success": True, "message": f"Employee #{emp_id} deleted", "associates": associates}

@app.post("/api/companies")
async def add_company(request: Request, payload: Dict[str, str] = Body(...)):
    ws = get_current_workspace(request)
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name required")
    companies = load_companies(workspace=ws)
    if name not in companies:
        companies.append(name)
        save_json('companies.json', companies, workspace=ws)
    return {"success": True, "companies": companies}

@app.delete("/api/companies/{name}")
async def delete_company(request: Request, name: str):
    ws = get_current_workspace(request)
    companies = load_companies(workspace=ws)
    companies = [c for c in companies if c != name]
    save_json('companies.json', companies, workspace=ws)
    return {"success": True, "companies": companies}

@app.post("/api/properties")
async def save_property(request: Request, prop: Dict[str, str] = Body(...)):
    ws = get_current_workspace(request)
    code = prop.get("code", "").strip().upper()
    name = prop.get("name", "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Code and Name required")
    properties = load_properties(workspace=ws)
    updated = False
    for i, p in enumerate(properties):
        if p.get("code", "").upper() == code:
            properties[i] = {"code": code, "name": name}
            updated = True
            break
    if not updated:
        properties.append({"code": code, "name": name})
    save_json('properties.json', properties, workspace=ws)
    return {"success": True, "properties": properties}

@app.delete("/api/properties/{code}")
async def delete_property(request: Request, code: str):
    ws = get_current_workspace(request)
    code = code.strip().upper()
    properties = load_properties(workspace=ws)
    properties = [p for p in properties if p.get("code", "").upper() != code]
    save_json('properties.json', properties, workspace=ws)
    return {"success": True, "properties": properties}

@app.get("/api/departments")
async def get_departments_endpoint(request: Request):
    ws = get_current_workspace(request)
    return {"success": True, "departments": load_departments(workspace=ws)}

@app.post("/api/departments")
async def save_department_endpoint(request: Request, dept: Dict[str, str] = Body(...)):
    ws = get_current_workspace(request)
    code = dept.get("code", "").strip()
    name = dept.get("name", "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Code and Name required")
    departments = load_departments(workspace=ws)
    updated = False
    for i, d in enumerate(departments):
        if d.get("code", "").strip().upper() == code.upper():
            departments[i] = {"code": code, "name": name}
            updated = True
            break
    if not updated:
        departments.append({"code": code, "name": name})
    save_departments(departments, workspace=ws)
    return {"success": True, "departments": departments}

@app.delete("/api/departments/{code}")
async def delete_department_endpoint(request: Request, code: str):
    ws = get_current_workspace(request)
    code_clean = code.strip().upper()
    departments = load_departments(workspace=ws)
    departments = [d for d in departments if d.get("code", "").strip().upper() != code_clean]
    save_departments(departments, workspace=ws)
    return {"success": True, "departments": departments}

@app.post("/api/stamps")
async def save_stamp(request: Request, stamp: Dict[str, Any] = Body(...)):
    ws = get_current_workspace(request)
    code = str(stamp.get("code", "")).strip().upper()
    name = stamp.get("name", code)
    hours = float(stamp.get("hours", 0))
    bg_color = stamp.get("bg_color", "#F1F5F9")
    text_color = stamp.get("text_color", "#334155")
    
    if not code:
        raise HTTPException(status_code=400, detail="Stamp code required")
        
    stamps = load_stamps(workspace=ws)
    updated = False
    new_stamp = {
        "code": code,
        "name": name,
        "hours": int(hours) if hours.is_integer() else hours,
        "bg_color": bg_color,
        "text_color": text_color
    }
    for i, s in enumerate(stamps):
        if str(s.get("code", "")).strip().upper() == code:
            stamps[i] = new_stamp
            updated = True
            break
    if not updated:
        stamps.append(new_stamp)
    save_json('stamps.json', stamps, workspace=ws)
    return {"success": True, "stamps": stamps}

@app.delete("/api/stamps/{code}")
async def delete_stamp(request: Request, code: str):
    ws = get_current_workspace(request)
    code = code.strip().upper()
    stamps = load_stamps(workspace=ws)
    stamps = [s for s in stamps if str(s.get("code", "")).strip().upper() != code]
    save_json('stamps.json', stamps, workspace=ws)
    return {"success": True, "stamps": stamps}

@app.post("/api/stamps/reset-universal")
async def reset_universal_stamps(request: Request):
    ws = get_current_workspace(request)
    stamps = [dict(s) for s in UNIVERSAL_STAMPS]
    save_json('stamps.json', stamps, workspace=ws)
    return {"success": True, "stamps": stamps}

# ================= Authorizers Endpoints =================

@app.get("/api/authorizers")
async def get_authorizers(request: Request):
    ws = get_current_workspace(request)
    return {"success": True, "authorizers": load_authorizers(workspace=ws)}

@app.post("/api/authorizers")
async def save_authorizer(request: Request, auth: Dict[str, Any] = Body(...)):
    ws = get_current_workspace(request)
    title = auth.get("title", "").strip()
    name = auth.get("name", "").strip()
    is_active = bool(auth.get("is_active", True))
    auth_id = auth.get("id")
    
    if not title:
        raise HTTPException(status_code=400, detail="Authorizer title is required")
        
    authorizers = load_authorizers(workspace=ws)
    if auth_id:
        updated = False
        for i, a in enumerate(authorizers):
            if a.get("id") == auth_id:
                authorizers[i] = {"id": auth_id, "title": title, "name": name, "is_active": is_active}
                updated = True
                break
        if not updated:
            authorizers.append({"id": auth_id, "title": title, "name": name, "is_active": is_active})
    else:
        new_id = max([a.get("id", 0) for a in authorizers], default=0) + 1
        authorizers.append({"id": new_id, "title": title, "name": name, "is_active": is_active})
        
    save_json('authorizers.json', authorizers, workspace=ws)
    return {"success": True, "authorizers": authorizers}

@app.patch("/api/authorizers/{auth_id}/toggle")
async def toggle_authorizer(request: Request, auth_id: int):
    ws = get_current_workspace(request)
    authorizers = load_authorizers(workspace=ws)
    found = False
    for a in authorizers:
        if a.get("id") == auth_id:
            a["is_active"] = not a.get("is_active", True)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    save_json('authorizers.json', authorizers, workspace=ws)
    return {"success": True, "authorizers": authorizers}

@app.delete("/api/authorizers/{auth_id}")
async def delete_authorizer(request: Request, auth_id: int):
    ws = get_current_workspace(request)
    authorizers = load_authorizers(workspace=ws)
    authorizers = [a for a in authorizers if a.get("id") != auth_id]
    save_json('authorizers.json', authorizers, workspace=ws)
    return {"success": True, "authorizers": authorizers}

# ================= Master Control Panel Endpoints (Admin Only) =================

def require_admin(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    u = get_user(user)
    if not u or (u.get("role") != "admin" and user not in ["shajjad", "admin"]):
        raise HTTPException(status_code=403, detail="Administrator permissions required")
    return u

@app.get("/api/users")
async def get_all_users(request: Request):
    require_admin(request)
    return {"success": True, "users": list_users_safe(), "workspaces": list_workspaces()}

@app.post("/api/users")
async def create_user_endpoint(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin(request)
    username = payload.get("username", "").strip()
    name = payload.get("name", "").strip()
    department = payload.get("department", "").strip()
    password = payload.get("password", "")
    role = payload.get("role", "user")
    
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not department:
        raise HTTPException(status_code=400, detail="Department is required")
        
    try:
        user_info = create_or_update_user(
            username=username,
            name=name,
            department=department,
            password=password,
            role=role
        )
        return {"success": True, "user": user_info, "users": list_users_safe(), "workspaces": list_workspaces()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create user: {e}")

@app.patch("/api/users/{target_username}/toggle")
async def toggle_user_endpoint(request: Request, target_username: str):
    require_admin(request)
    try:
        new_status = toggle_user_status(target_username)
        return {"success": True, "username": target_username, "is_active": new_status, "users": list_users_safe()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/users/{target_username}")
async def delete_user_endpoint(request: Request, target_username: str):
    require_admin(request)
    try:
        delete_user_account(target_username)
        return {"success": True, "username": target_username, "users": list_users_safe(), "workspaces": list_workspaces()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/switch-workspace")
async def switch_workspace_endpoint(request: Request, payload: Dict[str, str] = Body(...)):
    require_admin(request)
    target_ws = payload.get("workspace", "default").strip()
    workspaces = [w["id"] for w in list_workspaces()]
    if target_ws not in workspaces and target_ws not in ["default", "shajjad"]:
        raise HTTPException(status_code=400, detail="Unknown workspace")
        
    response = JSONResponse(content={"success": True, "active_workspace": target_ws})
    response.set_cookie(
        key="ow_active_ws",
        value=target_ws,
        max_age=30 * 86400,
        httponly=False,
        samesite="lax",
        path="/"
    )
    return response

@app.post("/api/users/{target_username}/password")
async def reset_user_password_endpoint(request: Request, target_username: str, payload: Dict[str, str] = Body(...)):
    require_admin(request)
    new_pw = payload.get("password", "").strip()
    if not new_pw:
        raise HTTPException(status_code=400, detail="Password is required")
    create_or_update_user(target_username, password=new_pw)
    return {"success": True, "message": f"Password for {target_username} updated successfully"}

# ================= Master Admin Universal Stamps Standard Endpoints =================

@app.get("/api/admin/stamps")
async def get_admin_universal_stamps(request: Request):
    require_admin(request)
    return {"success": True, "stamps": load_universal_stamps()}

@app.post("/api/admin/stamps")
async def save_admin_universal_stamp(request: Request, stamp: Dict[str, Any] = Body(...)):
    require_admin(request)
    code = str(stamp.get("code", "")).strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Stamp code required")
    name = str(stamp.get("name", code)).strip()
    try:
        hours = float(stamp.get("hours", 0))
    except (ValueError, TypeError):
        hours = 0.0
    bg_color = stamp.get("bg_color", "#F1F5F9")
    text_color = stamp.get("text_color", "#334155")
    
    stamps = load_universal_stamps()
    new_stamp = {
        "code": code,
        "name": name,
        "hours": int(hours) if hours.is_integer() else hours,
        "bg_color": bg_color,
        "text_color": text_color
    }
    updated = False
    for i, s in enumerate(stamps):
        if str(s.get("code", "")).strip().upper() == code:
            stamps[i] = new_stamp
            updated = True
            break
    if not updated:
        stamps.append(new_stamp)
    save_universal_stamps(stamps)
    return {"success": True, "stamps": stamps}

@app.delete("/api/admin/stamps/{code}")
async def delete_admin_universal_stamp(request: Request, code: str):
    require_admin(request)
    code = code.strip().upper()
    stamps = load_universal_stamps()
    stamps = [s for s in stamps if str(s.get("code", "")).strip().upper() != code]
    save_universal_stamps(stamps)
    return {"success": True, "stamps": stamps}

@app.post("/api/admin/stamps/reset")
async def reset_admin_universal_stamps(request: Request):
    require_admin(request)
    stamps = [dict(s) for s in UNIVERSAL_STAMPS]
    save_universal_stamps(stamps)
    return {"success": True, "stamps": stamps}

# ================= Export Endpoints =================

@app.get("/api/export/single-pdf/{group_key}")
async def export_single_pdf(
    request: Request,
    group_key: str,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    g = next((item for item in data["groups"] if item["key"] == group_key), None)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found for this month")
        
    emp_names_abbr = "+".join(a["name"].split()[0] for a in g["associates"])
    filename = f"({g['property']})-{g['company'].replace(' ', '_')}-{emp_names_abbr}-{data['month_info']['month_short']}-{year}.pdf"
    file_path = os.path.join(EXPORTS_DIR, filename)
    
    generate_company_pdf(
        file_path=file_path,
        property_name=g["property"],
        property_full=g["property_full"],
        company_name=g["company"],
        department=g["department"],
        month_info=data["month_info"],
        associates=g["associates"],
        settings=data["settings"],
        stamps=data["stamps"],
        authorizers=data["authorizers"]
    )
    
    try:
        record_history_entry(
            action="pdf",
            title=f"{g['company']} — {g['department']}",
            year=year,
            month=month,
            workspace=target_ws,
            group_key=group_key,
            company=g["company"],
            department=g["department"],
            property_code=g["property"],
            property_full=g["property_full"],
            associates_count=len(g["associates"]),
            associates_summary=", ".join(a["name"] for a in g["associates"]),
            assoc_ids=[a["id"] for a in g["associates"]],
            file_name=filename
        )
    except Exception as e:
        print(f"Warning recording history on PDF export: {e}")
    
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )

@app.get("/api/export/single-excel/{group_key}")
async def export_single_excel(
    request: Request,
    group_key: str,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    g = next((item for item in data["groups"] if item["key"] == group_key), None)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found for this month")
        
    filename = f"{g['company']} {g['property']}.xlsx"
    file_path = os.path.join(EXPORTS_DIR, filename)
    
    generate_company_excel(
        file_path=file_path,
        property_name=g["property"],
        property_full=g["property_full"],
        company_name=g["company"],
        department=g["department"],
        month_info=data["month_info"],
        associates=g["associates"],
        settings=data["settings"],
        stamps=data["stamps"],
        authorizers=data["authorizers"]
    )
    
    try:
        record_history_entry(
            action="excel",
            title=f"{g['company']} — {g['department']}",
            year=year,
            month=month,
            workspace=target_ws,
            group_key=group_key,
            company=g["company"],
            department=g["department"],
            property_code=g["property"],
            property_full=g["property_full"],
            associates_count=len(g["associates"]),
            associates_summary=", ".join(a["name"] for a in g["associates"]),
            assoc_ids=[a["id"] for a in g["associates"]],
            file_name=filename
        )
    except Exception as e:
        print(f"Warning recording history on Excel export: {e}")
    
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )

@app.get("/api/export/master-excel")
async def export_master_excel(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    if not data["active_associates"]:
        raise HTTPException(status_code=400, detail="No associates on this month's report yet.")
    filename = f"Attendance All in Excel-{data['month_info']['month_short']}-{year}.xlsx"
    file_path = os.path.join(EXPORTS_DIR, filename)
    
    generate_master_excel(
        file_path=file_path,
        month_info=data["month_info"],
        associates=data["active_associates"],
        stamps=data["stamps"],
        companies_list=data["companies"],
        properties_list=data["properties"]
    )
    try:
        active_list = data["active_associates"]
        cnt = len(active_list)
        record_history_entry(
            action="master_excel",
            title=f"Master Excel — All Staff ({cnt} Associates)",
            year=year,
            month=month,
            workspace=target_ws,
            group_key="",
            company="All Companies",
            department="Master Roster",
            property_code="All",
            property_full="All Properties",
            associates_count=cnt,
            associates_summary=", ".join(a["name"] for a in active_list[:5]) + ("..." if cnt > 5 else ""),
            assoc_ids=[a["id"] for a in active_list],
            file_name=filename
        )
    except Exception as e:
        print(f"Warning recording history on Master Excel export: {e}")

    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )

@app.get("/api/export/master-pdf")
async def export_master_pdf(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    if not data["active_associates"]:
        raise HTTPException(status_code=400, detail="No associates on this month's report yet.")
        
    filename = f"Master Attendance Report-{data['month_info']['month_short']}-{year}.pdf"
    file_path = os.path.join(EXPORTS_DIR, filename)
    
    props = data["settings"].get("properties", {})
    prop_codes = set(a.get("property", "RMH") for a in data["active_associates"])
    if len(prop_codes) == 1:
        prop_full = resolve_property_full_name(list(prop_codes)[0], props)
    else:
        prop_full = "Riyadh Marriott Hotel & Associated Properties"
        
    generate_master_pdf(
        file_path=file_path,
        month_info=data["month_info"],
        associates=data["active_associates"],
        property_full=prop_full,
        settings=data["settings"],
        stamps=data["stamps"],
        authorizers=data["authorizers"]
    )
    
    try:
        active_list = data["active_associates"]
        cnt = len(active_list)
        record_history_entry(
            action="master_pdf",
            title=f"Master PDF — All Staff ({cnt} Associates)",
            year=year,
            month=month,
            workspace=target_ws,
            group_key="",
            company="All Companies",
            department="Master Roster",
            property_code="All",
            property_full="All Properties",
            associates_count=cnt,
            associates_summary=", ".join(a["name"] for a in active_list[:5]) + ("..." if cnt > 5 else ""),
            assoc_ids=[a["id"] for a in active_list],
            file_name=filename
        )
    except Exception as e:
        print(f"Warning recording history on Master PDF export: {e}")

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
    )

@app.get("/api/export/pdfs-zip")
async def export_pdfs_zip(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    if not data["active_associates"]:
        raise HTTPException(status_code=400, detail="No associates on this month's report yet.")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        # Include Master PDF at top of PDFs ZIP
        master_pdf_name = f"00.Master-Attendance-Report-{data['month_info']['month_short']}-{year}.pdf"
        master_pdf_path = os.path.join(EXPORTS_DIR, master_pdf_name)
        generate_master_pdf(
            file_path=master_pdf_path,
            month_info=data["month_info"],
            associates=data["active_associates"],
            property_full="Riyadh Marriott Hotel",
            settings=data["settings"],
            stamps=data["stamps"],
            authorizers=data["authorizers"]
        )
        z.write(master_pdf_path, arcname=master_pdf_name)

        for idx, g in enumerate(data["groups"], start=1):
            emp_abbr = "+".join(a["name"].split()[0] for a in g["associates"])
            pdf_name = f"{idx:02d}.({g['property']})-{g['company'].replace(' ', '_')}-{emp_abbr}-{data['month_info']['month_short']}-{year}.pdf"
            temp_pdf_path = os.path.join(EXPORTS_DIR, pdf_name)
            generate_company_pdf(
                file_path=temp_pdf_path,
                property_name=g["property"],
                property_full=g["property_full"],
                company_name=g["company"],
                department=g["department"],
                month_info=data["month_info"],
                associates=g["associates"],
                settings=data["settings"],
                stamps=data["stamps"],
                authorizers=data["authorizers"]
            )
            z.write(temp_pdf_path, arcname=pdf_name)
            
    zip_buffer.seek(0)
    zip_filename = f"All-PDFs-{data['month_info']['month_short']}-{year}.zip"
    return HTMLResponse(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={zip_filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
        }
    )

@app.get("/api/export/excels-zip")
async def export_excels_zip(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    if not data["active_associates"]:
        raise HTTPException(status_code=400, detail="No associates on this month's report yet.")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        master_name = f"Attendance All in Excel-{data['month_info']['month_short']}-{year}.xlsx"
        master_path = os.path.join(EXPORTS_DIR, master_name)
        generate_master_excel(master_path, data["month_info"], data["active_associates"], stamps=data["stamps"], companies_list=data["companies"], properties_list=data["properties"])
        z.write(master_path, arcname=master_name)
        
        for g in data["groups"]:
            xl_name = f"{g['company']} {g['property']}.xlsx"
            temp_path = os.path.join(EXPORTS_DIR, xl_name)
            generate_company_excel(
                file_path=temp_path,
                property_name=g["property"],
                property_full=g["property_full"],
                company_name=g["company"],
                department=g["department"],
                month_info=data["month_info"],
                associates=g["associates"],
                settings=data["settings"],
                stamps=data["stamps"],
                authorizers=data["authorizers"]
            )
            z.write(temp_path, arcname=xl_name)
            
    zip_buffer.seek(0)
    zip_filename = f"All-Excels-{data['month_info']['month_short']}-{year}.zip"
    return HTMLResponse(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={zip_filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
        }
    )

@app.get("/api/export/all-zip")
async def export_all_zip(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10),
    ws: Optional[str] = Query(default=None)
):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    data = get_month_data(year, month, workspace=target_ws)
    if not data["active_associates"]:
        raise HTTPException(status_code=400, detail="No associates on this month's report yet.")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        master_name = f"Attendance All in Excel-{data['month_info']['month_short']}-{year}.xlsx"
        master_path = os.path.join(EXPORTS_DIR, master_name)
        generate_master_excel(master_path, data["month_info"], data["active_associates"], stamps=data["stamps"], companies_list=data["companies"], properties_list=data["properties"])
        z.write(master_path, arcname=master_name)
        
        for g in data["groups"]:
            xl_name = f"Excel/{g['company']} {g['property']}.xlsx"
            temp_path = os.path.join(EXPORTS_DIR, f"{g['company']} {g['property']}.xlsx")
            generate_company_excel(
                file_path=temp_path,
                property_name=g["property"],
                property_full=g["property_full"],
                company_name=g["company"],
                department=g["department"],
                month_info=data["month_info"],
                associates=g["associates"],
                settings=data["settings"],
                stamps=data["stamps"],
                authorizers=data["authorizers"]
            )
            z.write(temp_path, arcname=xl_name)
            
        # Include Master PDF at top of PDFs folder
        master_pdf_name = f"00.Master-Attendance-Report-{data['month_info']['month_short']}-{year}.pdf"
        master_pdf_path = os.path.join(EXPORTS_DIR, master_pdf_name)
        generate_master_pdf(
            file_path=master_pdf_path,
            month_info=data["month_info"],
            associates=data["active_associates"],
            property_full="Riyadh Marriott Hotel",
            settings=data["settings"],
            stamps=data["stamps"],
            authorizers=data["authorizers"]
        )
        z.write(master_pdf_path, arcname=f"PDFs/{master_pdf_name}")

        for idx, g in enumerate(data["groups"], start=1):
            emp_abbr = "+".join(a["name"].split()[0] for a in g["associates"])
            pdf_name = f"PDFs/{idx:02d}.({g['property']})-{g['company'].replace(' ', '_')}-{emp_abbr}-{data['month_info']['month_short']}-{year}.pdf"
            temp_pdf_path = os.path.join(EXPORTS_DIR, f"temp_{idx}.pdf")
            generate_company_pdf(
                file_path=temp_pdf_path,
                property_name=g["property"],
                property_full=g["property_full"],
                company_name=g["company"],
                department=g["department"],
                month_info=data["month_info"],
                associates=g["associates"],
                settings=data["settings"],
                stamps=data["stamps"],
                authorizers=data["authorizers"]
            )
            z.write(temp_pdf_path, arcname=pdf_name)
            
    zip_buffer.seek(0)
    zip_filename = f"officework-Package-{data['month_info']['month_short']}-{year}.zip"
    try:
        active_list = data["active_associates"]
        cnt = len(active_list)
        record_history_entry(
            action="all_zip",
            title=f"Full Package ZIP — All Reports ({cnt} Associates)",
            year=year,
            month=month,
            workspace=target_ws,
            group_key="",
            company="All Companies",
            department="Full Package",
            property_code="All",
            property_full="All Properties",
            associates_count=cnt,
            associates_summary=", ".join(a["name"] for a in active_list[:5]) + ("..." if cnt > 5 else ""),
            assoc_ids=[a["id"] for a in active_list],
            file_name=zip_filename
        )
    except Exception as e:
        print(f"Warning recording history on All ZIP export: {e}")

    return HTMLResponse(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={zip_filename}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache"
        }
    )

# ================= History & Saved Sheets Endpoints =================

@app.get("/api/history")
async def get_history_endpoint(request: Request, ws: Optional[str] = Query(default=None)):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    return {"success": True, "history": load_history(workspace=target_ws)}

@app.delete("/api/history/{item_id}")
async def delete_history_endpoint(request: Request, item_id: str, ws: Optional[str] = Query(default=None)):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    success = delete_history_entry(item_id, workspace=target_ws)
    return {"success": success, "history": load_history(workspace=target_ws)}

@app.post("/api/history/clear")
async def clear_history_endpoint(request: Request, ws: Optional[str] = Query(default=None)):
    target_ws = ws.strip() if ws and ws.strip() else get_current_workspace(request)
    clear_all_history_entries(workspace=target_ws)
    return {"success": True, "history": []}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=1212, reload=False)
