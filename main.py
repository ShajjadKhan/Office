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
from services.pdf_generator import generate_company_pdf
from services.auth_service import (
    authenticate_user,
    create_session,
    get_session_user,
    revoke_session,
    get_or_create_api_key,
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

# ================= Data Access Helpers =================

def load_json(filename: str, default: Any) -> Any:
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
    return default

def save_json(filename: str, data: Any):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_associates() -> List[Dict[str, Any]]:
    return load_json('associates.json', [])

def load_companies() -> List[str]:
    return load_json('companies.json', ["Tamkeen", "Nasim Alenjaz", "Soundline", "Work Force", "Qasir AL Nokba"])

def load_properties() -> List[Dict[str, Any]]:
    return load_json('properties.json', [
        {"code": "RMH", "name": "Riyadh Marriott Hotel"},
        {"code": "MEA", "name": "Marriott Executive Apartments"}
    ])

def load_stamps() -> List[Dict[str, Any]]:
    return load_json('stamps.json', [
        {"code": "8", "name": "Regular Work", "hours": 8, "bg_color": "#F1F5F9", "text_color": "#334155"},
        {"code": "WO", "name": "Weekly Off", "hours": 8, "bg_color": "#FEF3C7", "text_color": "#B45309"},
        {"code": "PH", "name": "Public Holiday", "hours": 8, "bg_color": "#D1FAE5", "text_color": "#065F46"},
        {"code": "SL", "name": "Sick Leave", "hours": 8, "bg_color": "#E0F2FE", "text_color": "#0369A1"},
        {"code": "AL", "name": "Annual Leave", "hours": 0, "bg_color": "#E0E7FF", "text_color": "#3730A3"},
        {"code": "A", "name": "Absent", "hours": 0, "bg_color": "#FEE2E2", "text_color": "#991B1B"},
        {"code": "V", "name": "Vacation", "hours": 0, "bg_color": "#FFE4E6", "text_color": "#9F1239"}
    ])

def load_authorizers() -> List[Dict[str, Any]]:
    return load_json('authorizers.json', [
        {"id": 1, "title": "Department Head", "name": "", "is_active": True},
        {"id": 2, "title": "Director of Human Resource", "name": "", "is_active": True},
        {"id": 3, "title": "Director of Finance", "name": "", "is_active": True}
    ])

def load_settings() -> Dict[str, Any]:
    props_list = load_properties()
    props_map = {p["code"]: p["name"] for p in props_list if isinstance(p, dict)}
    return {
        "properties": props_map,
        "department_names": {"0430": "Hotel Engineering"}
    }

# ================= Monthly Persistence Helpers =================

def get_month_file_path(year: int, month: int) -> str:
    return os.path.join(SAVED_DIR, f"{year}_{month:02d}.json")

def read_month_file(year: int, month: int) -> Optional[Dict[str, Any]]:
    path = get_month_file_path(year, month)
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

def write_month_file(year: int, month: int, data: Any):
    path = get_month_file_path(year, month)
    if isinstance(data, list):
        data = {"associates": data}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_month_data(year: int, month: int):
    all_associates = load_associates()
    stamps = load_stamps()
    authorizers = load_authorizers()
    settings = load_settings()
    month_info = get_month_info(year, month)
    days_cnt = month_info["days_in_month"]
    
    saved_content = read_month_file(year, month)
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
        key = f"{prop}_{comp}".replace(' ', '_').replace('-', '_')
        
        if key not in groups_dict:
            groups_dict[key] = {
                "key": key,
                "property": prop,
                "property_full": props.get(prop, f"{prop} Property"),
                "company": comp,
                "department": depts.get(assoc.get("department", "0430"), "Hotel Engineering"),
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
        "companies": load_companies(),
        "properties": load_properties()
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
    return response

@app.get("/logout")
async def logout_endpoint(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        revoke_session(token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response

@app.get("/", response_class=HTMLResponse)
async def dashboard_view(
    request: Request,
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
    month_names = {i: calendar.month_name[i] for i in range(1, 13)}
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "current_user": getattr(request.state, "user", "User"),
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
            "stamps": data["stamps"]
        }
    )

@app.get("/print/{group_key}", response_class=HTMLResponse)
async def print_report_view(
    request: Request,
    group_key: str,
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
    target_group = next((g for g in data["groups"] if g["key"] == group_key), None)
    if not target_group:
        raise HTTPException(status_code=404, detail="Report group not found for this month")
        
    return templates.TemplateResponse(
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

@app.post("/api/save-month")
async def save_month_endpoint(
    year: int = Query(...),
    month: int = Query(...),
    payload: Any = Body(...)
):
    write_month_file(year, month, payload)
    return {"success": True, "message": f"Saved attendance for {year}-{month:02d}"}

# ================= Quick Schedule Entry & Month Roster Endpoints =================

@app.post("/api/month/quick-entry")
async def month_quick_entry(payload: Dict[str, Any] = Body(...)):
    year = int(payload.get("year", 2026))
    month = int(payload.get("month", 10))
    assoc_id = payload.get("assoc_id")
    if assoc_id is None:
        raise HTTPException(status_code=400, detail="Associate ID is required")
    assoc_id = int(assoc_id)
    
    entries = payload.get("entries", [])
    month_info = get_month_info(year, month)
    days_cnt = month_info["days_in_month"]
    
    # All days default to "8"
    days = ["8"] * days_cnt
    for e in entries:
        try:
            d = int(e.get("day", 0))
            st = str(e.get("stamp", "WO")).strip().upper()
            if 1 <= d <= days_cnt and st:
                days[d - 1] = st
        except (ValueError, TypeError):
            continue
            
    saved_content = read_month_file(year, month) or {}
    raw_list = saved_content.get("associates", []) if isinstance(saved_content, dict) else (saved_content or [])
    
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
        
    write_month_file(year, month, {"associates": new_list})
    return {"success": True, "message": "Associate schedule saved to sheet"}

@app.post("/api/month/remove-associate")
async def month_remove_associate(payload: Dict[str, Any] = Body(...)):
    year = int(payload.get("year", 2026))
    month = int(payload.get("month", 10))
    assoc_id = payload.get("assoc_id")
    if assoc_id is None:
        raise HTTPException(status_code=400, detail="Associate ID is required")
    assoc_id = int(assoc_id)
    
    saved_content = read_month_file(year, month) or {}
    raw_list = saved_content.get("associates", []) if isinstance(saved_content, dict) else (saved_content or [])
    
    new_list = [item for item in raw_list if item.get("id") != assoc_id]
    write_month_file(year, month, {"associates": new_list})
    return {"success": True, "message": "Associate removed from this month's sheet"}

# ================= Configuration & Master Data Endpoints =================

@app.get("/api/config")
async def get_config():
    return {
        "associates": load_associates(),
        "companies": load_companies(),
        "properties": load_properties(),
        "stamps": load_stamps(),
        "authorizers": load_authorizers()
    }

@app.post("/api/employees")
async def save_employee(emp: Dict[str, Any] = Body(...)):
    associates = load_associates()
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
    save_json('associates.json', associates)
    return {"success": True, "employee": emp}

@app.delete("/api/employees/{emp_id}")
async def delete_employee(emp_id: int):
    associates = load_associates()
    associates = [a for a in associates if a.get("id") != emp_id]
    save_json('associates.json', associates)
    return {"success": True, "message": f"Employee #{emp_id} deleted"}

@app.post("/api/companies")
async def add_company(payload: Dict[str, str] = Body(...)):
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Company name required")
    companies = load_companies()
    if name not in companies:
        companies.append(name)
        save_json('companies.json', companies)
    return {"success": True, "companies": companies}

@app.delete("/api/companies/{name}")
async def delete_company(name: str):
    companies = load_companies()
    companies = [c for c in companies if c != name]
    save_json('companies.json', companies)
    return {"success": True, "companies": companies}

@app.post("/api/properties")
async def save_property(prop: Dict[str, str] = Body(...)):
    code = prop.get("code", "").strip().upper()
    name = prop.get("name", "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="Code and Name required")
    properties = load_properties()
    updated = False
    for i, p in enumerate(properties):
        if p.get("code", "").upper() == code:
            properties[i] = {"code": code, "name": name}
            updated = True
            break
    if not updated:
        properties.append({"code": code, "name": name})
    save_json('properties.json', properties)
    return {"success": True, "properties": properties}

@app.delete("/api/properties/{code}")
async def delete_property(code: str):
    code = code.strip().upper()
    properties = load_properties()
    properties = [p for p in properties if p.get("code", "").upper() != code]
    save_json('properties.json', properties)
    return {"success": True, "properties": properties}

@app.post("/api/stamps")
async def save_stamp(stamp: Dict[str, Any] = Body(...)):
    code = str(stamp.get("code", "")).strip().upper()
    name = stamp.get("name", code)
    hours = float(stamp.get("hours", 0))
    bg_color = stamp.get("bg_color", "#F1F5F9")
    text_color = stamp.get("text_color", "#334155")
    
    if not code:
        raise HTTPException(status_code=400, detail="Stamp code required")
        
    stamps = load_stamps()
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
    save_json('stamps.json', stamps)
    return {"success": True, "stamps": stamps}

@app.delete("/api/stamps/{code}")
async def delete_stamp(code: str):
    code = code.strip().upper()
    stamps = load_stamps()
    stamps = [s for s in stamps if str(s.get("code", "")).strip().upper() != code]
    save_json('stamps.json', stamps)
    return {"success": True, "stamps": stamps}

# ================= Authorizers Endpoints =================

@app.get("/api/authorizers")
async def get_authorizers():
    return {"success": True, "authorizers": load_authorizers()}

@app.post("/api/authorizers")
async def save_authorizer(auth: Dict[str, Any] = Body(...)):
    title = auth.get("title", "").strip()
    name = auth.get("name", "").strip()
    is_active = bool(auth.get("is_active", True))
    auth_id = auth.get("id")
    
    if not title:
        raise HTTPException(status_code=400, detail="Authorizer title is required")
        
    authorizers = load_authorizers()
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
        
    save_json('authorizers.json', authorizers)
    return {"success": True, "authorizers": authorizers}

@app.patch("/api/authorizers/{auth_id}/toggle")
async def toggle_authorizer(auth_id: int):
    authorizers = load_authorizers()
    found = False
    for a in authorizers:
        if a.get("id") == auth_id:
            a["is_active"] = not a.get("is_active", True)
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Authorizer not found")
    save_json('authorizers.json', authorizers)
    return {"success": True, "authorizers": authorizers}

@app.delete("/api/authorizers/{auth_id}")
async def delete_authorizer(auth_id: int):
    authorizers = load_authorizers()
    authorizers = [a for a in authorizers if a.get("id") != auth_id]
    save_json('authorizers.json', authorizers)
    return {"success": True, "authorizers": authorizers}

# ================= Export Endpoints =================

@app.get("/api/export/single-pdf/{group_key}")
async def export_single_pdf(
    group_key: str,
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
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
    
    return FileResponse(file_path, media_type="application/pdf", filename=filename)

@app.get("/api/export/single-excel/{group_key}")
async def export_single_excel(
    group_key: str,
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
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
    
    return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)

@app.get("/api/export/master-excel")
async def export_master_excel(
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
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
    return FileResponse(file_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)

@app.get("/api/export/pdfs-zip")
async def export_pdfs_zip(
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
    if not data["active_associates"]:
        raise HTTPException(status_code=400, detail="No associates on this month's report yet.")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
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
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

@app.get("/api/export/excels-zip")
async def export_excels_zip(
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
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
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

@app.get("/api/export/all-zip")
async def export_all_zip(
    year: int = Query(default=2026),
    month: int = Query(default=10)
):
    data = get_month_data(year, month)
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
    return HTMLResponse(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=1212, reload=False)
