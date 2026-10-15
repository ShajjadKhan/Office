import os
import json
import secrets
import hashlib
import hmac
import time
from typing import Optional, Dict, Any, List

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
API_KEY_FILE = os.path.join(DATA_DIR, '.api_key')
COOKIE_NAME = "officework_session"

def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return salt, pw_hash

def verify_password(plain_password: str, salt: str, expected_hash: str) -> bool:
    try:
        derived = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
        return hmac.compare_digest(derived, expected_hash)
    except Exception:
        return False

def init_default_users() -> List[Dict[str, Any]]:
    # Create default accounts: shajjad and admin
    users = []
    salt_shajjad, hash_shajjad = hash_password("S#imul7270733")
    users.append({
        "username": "shajjad",
        "name": "Shajjad Khan",
        "department": "Hotel Engineering",
        "role": "admin",
        "workspace": "default",
        "salt": salt_shajjad,
        "password_hash": hash_shajjad,
        "is_active": True
    })
    salt_admin, hash_admin = hash_password("S#imul7270733")
    users.append({
        "username": "admin",
        "name": "Administrator",
        "department": "Hotel Engineering",
        "role": "admin",
        "workspace": "default",
        "salt": salt_admin,
        "password_hash": hash_admin,
        "is_active": True
    })
    save_users(users)
    return users

def load_users() -> List[Dict[str, Any]]:
    if not os.path.exists(USERS_FILE):
        return init_default_users()
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                # Ensure fields like role, department, workspace exist
                updated = False
                for u in data:
                    if "role" not in u:
                        u["role"] = "admin" if u.get("username") in ["shajjad", "admin"] else "user"
                        updated = True
                    if "workspace" not in u:
                        u["workspace"] = "default" if u.get("username") in ["shajjad", "admin"] else u.get("username")
                        updated = True
                    if "department" not in u:
                        u["department"] = "Hotel Engineering" if u.get("username") in ["shajjad", "admin"] else "General"
                        updated = True
                if updated:
                    save_users(data)
                return data
            return init_default_users()
    except Exception as e:
        print(f"Error loading users: {e}")
        return init_default_users()

def save_users(users: List[Dict[str, Any]]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def get_user(username: str) -> Optional[Dict[str, Any]]:
    uname = (username or '').strip().lower()
    for u in load_users():
        if u.get("username", "").lower() == uname:
            return u
    return None

def get_user_role(username: str) -> str:
    if username in ["shajjad", "admin"]:
        return "admin"
    u = get_user(username)
    return u.get("role", "user") if u else "user"

def get_user_workspace(username: str) -> str:
    if username in ["shajjad", "admin"]:
        return "default"
    u = get_user(username)
    return u.get("workspace", username) if u else "default"

def list_users_safe() -> List[Dict[str, Any]]:
    users = load_users()
    safe = []
    for u in users:
        safe.append({
            "username": u.get("username"),
            "name": u.get("name", u.get("username")),
            "department": u.get("department", "General"),
            "role": u.get("role", "user"),
            "workspace": u.get("workspace", u.get("username")),
            "is_active": u.get("is_active", True)
        })
    return safe

def list_workspaces() -> List[Dict[str, Any]]:
    users = load_users()
    ws_map = {}
    ws_map["default"] = {
        "id": "default",
        "name": "Shajjad Khan",
        "department": "Hotel Engineering"
    }
    for u in users:
        ws = u.get("workspace", u.get("username"))
        if ws and ws != "default":
            ws_map[ws] = {
                "id": ws,
                "name": u.get("name", u.get("username")),
                "department": u.get("department", "Department")
            }
    return list(ws_map.values())

def init_workspace(workspace: str, department_name: str = "General Department"):
    if not workspace or workspace in ["default", "shajjad"]:
        return
        
    ws_dir = os.path.join(DATA_DIR, "workspaces", workspace)
    os.makedirs(ws_dir, exist_ok=True)
    os.makedirs(os.path.join(ws_dir, "saved_months"), exist_ok=True)
    
    UNIVERSAL_STAMPS = [
        {"code": "8", "name": "Regular Work", "hours": 8, "bg_color": "#F1F5F9", "text_color": "#334155"},
        {"code": "WO", "name": "Weekly Off", "hours": 8, "bg_color": "#FEF3C7", "text_color": "#B45309"},
        {"code": "PH", "name": "Public Holiday", "hours": 8, "bg_color": "#D1FAE5", "text_color": "#065F46"},
        {"code": "SL", "name": "Sick Leave", "hours": 8, "bg_color": "#E0F2FE", "text_color": "#0369A1"},
        {"code": "AL", "name": "Annual Leave", "hours": 0, "bg_color": "#E0E7FF", "text_color": "#3730A3"},
        {"code": "A", "name": "Absent", "hours": 0, "bg_color": "#FEE2E2", "text_color": "#991B1B"},
        {"code": "V", "name": "Vacation", "hours": 0, "bg_color": "#FFE4E6", "text_color": "#9F1239"}
    ]

    # Clean Blank Slate for private department data
    for fname in ["associates.json", "companies.json", "properties.json", "authorizers.json"]:
        file_path = os.path.join(ws_dir, fname)
        if not os.path.exists(file_path):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)
                
    # Standard Universal Company Stamps (Consistent across all departments)
    stamps_file = os.path.join(ws_dir, "stamps.json")
    if not os.path.exists(stamps_file):
        with open(stamps_file, "w", encoding="utf-8") as f:
            json.dump(UNIVERSAL_STAMPS, f, indent=2)
            
    # Default Settings (only store their department name for report headers)
    settings_file = os.path.join(ws_dir, "default_settings.json")
    if not os.path.exists(settings_file):
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump({
                "properties": {},
                "department_names": {
                    "0430": department_name
                }
            }, f, indent=2)

def create_or_update_user(
    username: str,
    name: str,
    department: str,
    password: Optional[str] = None,
    role: str = "user"
) -> Dict[str, Any]:
    uname = (username or '').strip().lower()
    if not uname:
        raise ValueError("Username cannot be empty")
        
    users = load_users()
    existing = next((u for u in users if u.get("username", "").lower() == uname), None)
    
    if existing:
        existing["name"] = name.strip() or existing.get("name", uname)
        existing["department"] = department.strip() or existing.get("department", "General")
        if role:
            existing["role"] = role
        if password and password.strip():
            salt, pw_hash = hash_password(password.strip())
            existing["salt"] = salt
            existing["password_hash"] = pw_hash
        user_rec = existing
    else:
        if not password or not password.strip():
            raise ValueError("Password is required for new user creation")
        salt, pw_hash = hash_password(password.strip())
        workspace = uname
        user_rec = {
            "username": uname,
            "name": name.strip() or uname.capitalize(),
            "department": department.strip() or "General Department",
            "role": role or "user",
            "workspace": workspace,
            "salt": salt,
            "password_hash": pw_hash,
            "is_active": True
        }
        users.append(user_rec)
        
        # Initialize blank isolated workspace for the new user
        init_workspace(workspace, department_name=user_rec["department"])
        
    save_users(users)
    return {
        "username": user_rec["username"],
        "name": user_rec["name"],
        "department": user_rec["department"],
        "role": user_rec["role"],
        "workspace": user_rec["workspace"],
        "is_active": user_rec["is_active"]
    }

def toggle_user_status(username: str) -> bool:
    uname = username.strip().lower()
    if uname in ["shajjad", "admin"]:
        raise ValueError("Cannot deactivate primary administrator")
    users = load_users()
    target = next((u for u in users if u.get("username", "").lower() == uname), None)
    if not target:
        raise ValueError("User not found")
    target["is_active"] = not target.get("is_active", True)
    save_users(users)
    return target["is_active"]

def delete_user_account(username: str) -> bool:
    uname = username.strip().lower()
    if uname in ["shajjad", "admin"]:
        raise ValueError("Cannot delete primary administrator")
    users = load_users()
    new_users = [u for u in users if u.get("username", "").lower() != uname]
    if len(new_users) == len(users):
        raise ValueError("User not found")
    save_users(new_users)
    return True

def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    users = load_users()
    uname = (username or '').strip().lower()
    for u in users:
        if u.get("username", "").lower() == uname and u.get("is_active", True):
            if verify_password(password, u.get("salt", ""), u.get("password_hash", "")):
                return u
    return None

def get_or_create_api_key() -> str:
    if os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
                key = f.read().strip()
                if key:
                    return key
        except Exception:
            pass
    new_key = f"ow_{secrets.token_hex(20)}"
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(API_KEY_FILE, 'w', encoding='utf-8') as f:
        f.write(new_key)
    return new_key

# In-memory session cache with file persistence
_SESSIONS_CACHE: Dict[str, Dict[str, Any]] = {}

def load_sessions() -> Dict[str, Dict[str, Any]]:
    global _SESSIONS_CACHE
    if _SESSIONS_CACHE:
        return _SESSIONS_CACHE
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _SESSIONS_CACHE = data
                    return _SESSIONS_CACHE
        except Exception:
            pass
    _SESSIONS_CACHE = {}
    return _SESSIONS_CACHE

def save_sessions():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(_SESSIONS_CACHE, f, indent=2)

def create_session(username: str, duration_days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + (duration_days * 86400)
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "expires_at": expires_at,
        "created_at": time.time()
    }
    save_sessions()
    return token

def get_session_user(token: str) -> Optional[str]:
    if not token:
        return None
    sessions = load_sessions()
    session = sessions.get(token)
    if not session:
        return None
    if time.time() > session.get("expires_at", 0):
        revoke_session(token)
        return None
    return session.get("username")

def revoke_session(token: str):
    sessions = load_sessions()
    if token in sessions:
        del sessions[token]
        save_sessions()
