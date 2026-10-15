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
        "salt": salt_shajjad,
        "password_hash": hash_shajjad,
        "is_active": True
    })
    salt_admin, hash_admin = hash_password("S#imul7270733")
    users.append({
        "username": "admin",
        "name": "Administrator",
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
                return data
            return init_default_users()
    except Exception as e:
        print(f"Error loading users: {e}")
        return init_default_users()

def save_users(users: List[Dict[str, Any]]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

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
