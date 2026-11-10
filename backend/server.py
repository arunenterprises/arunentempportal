from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import re
import secrets
import base64
import logging
from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional, List, Literal
from zoneinfo import ZoneInfo

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends, UploadFile, File, Form
from fastapi.responses import Response
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from payslip_pdf import build_payslip_pdf
from vendor_sync import run_sync, push_now, push_day
import calendar
from shortcode import make_short_code, short_code_taken, SHORT_RE
import csv
import io
import asyncio
import hmac
import json
from pywebpush import webpush, WebPushException

client = AsyncIOMotorClient(os.environ['MONGO_URL'], tz_aware=True)
db = client[os.environ['DB_NAME']]
TZ = ZoneInfo(os.environ['APP_TIMEZONE'])
JWT_ALG = "HS256"

app = FastAPI()
api = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# ---------- helpers ----------
def now_utc():
    return datetime.now(timezone.utc)


def today_str():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def ser(doc):
    if doc is None:
        return None
    out = {}
    for k, v in doc.items():
        if k in ("password_hash", "pdf_b64"):
            continue
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Not found")


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


ONLINE_MINUTES = 15


def client_ip(request: Request) -> str:
    h = request.headers
    xff = [p.strip() for p in (h.get("x-forwarded-for") or "").split(",") if p.strip()]
    ip = h.get("cf-connecting-ip") or (xff[-3] if len(xff) >= 3 else xff[0] if xff else "") or h.get("x-real-ip")
    return ip or (request.client.host if request.client else "")


async def log_auth(kind: str, request: Request, user: Optional[dict] = None, identifier: str = "", sid: str = None, detail: str = ""):
    await db.login_logs.insert_one({
        "type": kind, "user_id": str(user["_id"]) if user else None, "role": (user or {}).get("role"), "identifier": identifier,
        "ip": client_ip(request), "user_agent": request.headers.get("user-agent", "")[:300], "sid": sid, "detail": detail, "at": now_utc()})


def make_token(user_id: str, role: str, sid: str = None) -> str:
    payload = {"sub": user_id, "role": role, "type": "access", "exp": now_utc() + timedelta(hours=12)}
    if sid:
        payload["sid"] = sid
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALG)


async def current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"_id": oid(payload["sub"])})
    if not user or not user.get("active", True) or user.get("portal_enabled") is False:
        raise HTTPException(status_code=401, detail="User not found")
    sid = payload.get("sid")
    if sid:
        sess = await db.login_sessions.find_one({"sid": sid}, {"logout_at": 1, "last_seen": 1})
        if not sess or sess.get("logout_at"):
            raise HTTPException(status_code=401, detail="Session ended. Please log in again.")
        if sess["last_seen"].replace(tzinfo=timezone.utc) < now_utc() - timedelta(seconds=60):
            await db.login_sessions.update_one({"sid": sid}, {"$set": {"last_seen": now_utc(), "ip": client_ip(request)}})
    out = ser(user)
    out["sid"] = sid
    return out


STAFF_ROLES = ("superadmin", "admin", "hr", "manager")
CREATABLE_ROLES = ("admin", "hr", "manager")
MODULES = ("employees", "attendance", "requests", "leave", "payslips", "service_book", "logins")
ACTIONS = ("view", "edit", "approve")
MODULE_PREFIXES = [
    ("/api/admin/employees", "employees"), ("/api/admin/credential-slips", "employees"), ("/api/admin/vendor-sync", "employees"),
    ("/api/admin/attendance", "attendance"), ("/api/admin/settings/employee-sheet", "attendance"),
    ("/api/admin/requests", "requests"), ("/api/admin/leave-", "leave"),
    ("/api/admin/payslips", "payslips"), ("/api/admin/service-records", "service_book"), ("/api/admin/appraisals", "service_book"),
    ("/api/admin/login-activity", "logins"),
]


def has_perm(user: dict, module: str, action: str) -> bool:
    if user.get("role") == "superadmin":
        return True
    return bool(((user.get("permissions") or {}).get(module) or {}).get(action))


async def admin_user(request: Request, user: dict = Depends(current_user)) -> dict:
    if user["role"] not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    if user["role"] == "superadmin":
        return user
    path = request.url.path
    if path.startswith("/api/admin/users"):
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage users")
    if path.startswith("/api/admin/stats"):
        return user
    module = next((m for p, m in MODULE_PREFIXES if path.startswith(p)), None)
    if module is None:
        raise HTTPException(status_code=403, detail="Permission required")
    if request.method == "GET":
        action = "view"
    elif module == "requests" and request.method == "PATCH":
        action = "approve"
    else:
        action = "edit"
    if not has_perm(user, module, action):
        raise HTTPException(status_code=403, detail=f"You don't have {action} permission for {module.replace('_', ' ')}")
    return user


async def superadmin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can manage users")
    return user


async def employee_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "employee":
        raise HTTPException(status_code=403, detail="Employee access required")
    return user


async def employee_map(ids) -> dict:
    ids = [oid(i) for i in set(ids) if i]
    docs = await db.users.find({"_id": {"$in": ids}}, {"name": 1, "employee_id": 1, "short_code": 1, "department": 1, "designation": 1}).to_list(5000)
    return {str(d["_id"]): {"name": d.get("name"), "employee_id": d.get("employee_id"), "short_code": d.get("short_code"), "department": d.get("department"), "designation": d.get("designation")} for d in docs}


async def attach_employee(items: List[dict]) -> List[dict]:
    m = await employee_map([i.get("user_id") for i in items])
    for i in items:
        i["employee"] = m.get(i.get("user_id"))
    return items


# ---------- auth ----------
class LoginIn(BaseModel):
    identifier: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


@api.post("/auth/login")
async def login(body: LoginIn, request: Request):
    ident = body.identifier.strip()
    if re.sub(r"[^a-z]", "", ident.lower()) in ("superadmin", "supradmin", "supperadmin"):
        sa = await db.users.find_one({"role": "superadmin"}, {"email": 1})
        if sa:
            ident = sa["email"]
    user = await db.users.find_one({"$or": [{"email": ident.lower()}, {"employee_id": ident.upper()}, {"short_code": ident.upper()}]})
    key = f"user:{user['_id']}" if user else ident.lower()
    att = await db.login_attempts.find_one({"identifier": key})
    locked = att and att.get("count", 0) >= 5 and att["last"] > now_utc() - timedelta(minutes=15)
    if locked:
        await log_auth("failed", request, user, ident, detail="Locked: too many failed attempts")
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
    if not user or not verify_password(body.password, user["password_hash"]):
        await log_auth("failed", request, user, ident, detail="Wrong password" if user else "Unknown user")
        expired = att and att["last"] <= now_utc() - timedelta(minutes=15)
        if expired:
            await db.login_attempts.update_one({"identifier": key}, {"$set": {"count": 1, "last": now_utc()}})
        else:
            await db.login_attempts.update_one({"identifier": key}, {"$inc": {"count": 1}, "$set": {"last": now_utc()}}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email/employee ID or password")
    if not user.get("active", True):
        await log_auth("failed", request, user, ident, detail="Account inactive")
        raise HTTPException(status_code=403, detail="Your account is inactive. Contact HR.")
    if user.get("portal_enabled") is False:
        await log_auth("failed", request, user, ident, detail="Portal access disabled")
        raise HTTPException(status_code=403, detail="Your portal access is disabled. Contact HR.")
    await db.login_attempts.delete_one({"identifier": key})
    sid = secrets.token_urlsafe(16)
    now = now_utc()
    await db.login_sessions.insert_one({"sid": sid, "user_id": str(user["_id"]), "role": user["role"], "ip": client_ip(request), "login_ip": client_ip(request),
                                        "user_agent": request.headers.get("user-agent", "")[:300], "login_at": now, "last_seen": now, "logout_at": None})
    await log_auth("login", request, user, ident, sid)
    return {"token": make_token(str(user["_id"]), user["role"], sid), "user": ser(user)}


@api.post("/auth/logout")
async def logout(request: Request, user: dict = Depends(current_user)):
    if user.get("sid"):
        await db.login_sessions.update_one({"sid": user["sid"]}, {"$set": {"logout_at": now_utc()}})
    await log_auth("logout", request, {"_id": user["id"], "role": user["role"]}, user.get("employee_id") or user.get("email", ""), user.get("sid"))
    return {"ok": True}


def _session_out(s: dict, emps: dict) -> dict:
    cutoff = now_utc() - timedelta(minutes=ONLINE_MINUTES)
    last = s["last_seen"].replace(tzinfo=timezone.utc)
    login_at = s["login_at"].replace(tzinfo=timezone.utc)
    expired = login_at < now_utc() - timedelta(hours=12)
    status = "logged_out" if s.get("logout_at") else "expired" if expired else "online" if last >= cutoff else "idle"
    return {"sid": s["sid"], "user_id": s["user_id"], "role": s.get("role"), "employee": emps.get(s["user_id"]), "ip": s.get("ip"), "login_ip": s.get("login_ip"),
            "user_agent": s.get("user_agent"), "login_at": login_at.isoformat(), "last_seen": last.isoformat(),
            "logout_at": s["logout_at"].replace(tzinfo=timezone.utc).isoformat() if s.get("logout_at") else None, "status": status}


@api.get("/admin/login-activity/sessions")
async def login_sessions(admin: dict = Depends(admin_user)):
    docs = await db.login_sessions.find({"role": "employee", "logout_at": None, "login_at": {"$gte": now_utc() - timedelta(hours=12)}}).sort("last_seen", -1).to_list(1000)
    emps = await employee_map([d["user_id"] for d in docs])
    allowed = {str(u["_id"]) for u in await db.users.find({"_id": {"$in": [oid(d["user_id"]) for d in docs]}, "active": {"$ne": False}, "portal_enabled": {"$ne": False}}, {"_id": 1}).to_list(1000)}
    out = [_session_out(d, emps) for d in docs if d["user_id"] in allowed]
    return {"online_minutes": ONLINE_MINUTES, "sessions": out}


@api.get("/admin/login-activity/logs")
async def login_logs(date: Optional[str] = None, user_id: Optional[str] = None, type: Optional[str] = None, admin: dict = Depends(admin_user)):
    q = {"role": {"$nin": list(STAFF_ROLES)}}
    if user_id:
        q["user_id"] = user_id
    if type in ("login", "logout", "failed"):
        q["type"] = type
    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TZ)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
        q["at"] = {"$gte": d.astimezone(timezone.utc), "$lt": (d + timedelta(days=1)).astimezone(timezone.utc)}
    docs = await db.login_logs.find(q).sort("at", -1).to_list(500)
    emps = await employee_map([d["user_id"] for d in docs if d.get("user_id")])
    return [{"id": str(d["_id"]), "type": d["type"], "user_id": d.get("user_id"), "employee": emps.get(d.get("user_id")), "identifier": d.get("identifier"),
             "ip": d.get("ip"), "user_agent": d.get("user_agent"), "detail": d.get("detail"), "at": d["at"].replace(tzinfo=timezone.utc).isoformat()} for d in docs]


@api.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    return user


@api.post("/auth/change-password")
async def change_password(body: ChangePasswordIn, user: dict = Depends(current_user)):
    doc = await db.users.find_one({"_id": oid(user["id"])})
    if not verify_password(body.current_password, doc["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await db.users.update_one({"_id": doc["_id"]}, {"$set": {"password_hash": hash_password(body.new_password), "must_change_password": False, "password_set_in_app": True}})
    return {"ok": True}


# ---------- employees (admin) ----------
class EmployeeIn(BaseModel):
    employee_id: str
    name: str
    email: str
    password: Optional[str] = None
    phone: str = ""
    department: str = ""
    designation: str = ""
    joining_date: str = ""
    dob: str = ""
    gender: str = ""
    address: str = ""
    bank_name: str = ""
    bank_account: str = ""
    ifsc: str = ""
    pan: str = ""
    uan: str = ""
    basic: float = 0
    hra: float = 0
    allowances: float = 0
    active: bool = True


async def check_unique(email: str, emp_id: str, exclude: Optional[ObjectId] = None):
    if not emp_id or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Valid Employee ID and email are required")
    q = {"$or": [{"email": email}, {"employee_id": emp_id}, {"short_code": emp_id}]}
    if exclude:
        q["_id"] = {"$ne": exclude}
    if await db.users.find_one(q):
        raise HTTPException(status_code=400, detail="Email or Employee ID already exists")


@api.get("/admin/employees")
async def list_employees(admin: dict = Depends(admin_user)):
    docs = await db.users.find({"role": "employee"}).sort("employee_id", 1).to_list(5000)
    return [ser(d) for d in docs]


@api.post("/admin/employees")
async def create_employee(body: EmployeeIn, admin: dict = Depends(admin_user)):
    data = body.model_dump()
    data["email"] = data["email"].strip().lower()
    data["employee_id"] = data["employee_id"].strip().upper()
    data["name"] = data["name"].strip()
    if not data["name"]:
        raise HTTPException(status_code=400, detail="Name is required")
    pwd = data.pop("password")
    if not pwd or len(pwd) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    await check_unique(data["email"], data["employee_id"])
    data.update({"role": "employee", "password_hash": hash_password(pwd), "created_at": now_utc(), "short_code": await make_short_code(db, data["employee_id"])})
    res = await db.users.insert_one(data)
    if data["joining_date"]:
        await db.service_records.insert_one({
            "user_id": str(res.inserted_id), "date": data["joining_date"], "type": "joining",
            "title": f"Joined as {data['designation'] or 'Employee'}", "notes": data["department"], "created_at": now_utc(),
        })
    return ser(await db.users.find_one({"_id": res.inserted_id}))


class ShortCodeIn(BaseModel):
    short_code: Optional[str] = None


class ShortCodeBulkIn(BaseModel):
    overwrite: bool = False


@api.post("/admin/employees/short-codes/generate")
async def generate_short_codes(body: ShortCodeBulkIn, admin: dict = Depends(admin_user)):
    q = {"role": "employee"} if body.overwrite else {"role": "employee", "$or": [{"short_code": None}, {"short_code": ""}, {"short_code": {"$exists": False}}]}
    docs = await db.users.find(q, {"employee_id": 1}).sort("employee_id", 1).to_list(5000)
    if body.overwrite:
        await db.users.update_many({"_id": {"$in": [d["_id"] for d in docs]}}, {"$unset": {"short_code": ""}})
    for d in docs:
        await db.users.update_one({"_id": d["_id"]}, {"$set": {"short_code": await make_short_code(db, d.get("employee_id"), d["_id"])}})
    return {"generated": len(docs)}


@api.put("/admin/employees/{emp_id}/short-code")
async def set_short_code(emp_id: str, body: ShortCodeIn, admin: dict = Depends(admin_user)):
    emp = await db.users.find_one({"_id": oid(emp_id), "role": "employee"}, {"employee_id": 1})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    code = (body.short_code or "").strip().upper()
    if code:
        if not SHORT_RE.match(code):
            raise HTTPException(status_code=400, detail="Short code must be 5-6 letters/numbers (A-Z, 0-9)")
        if await short_code_taken(db, code, emp["_id"]):
            raise HTTPException(status_code=409, detail=f"Short code {code} is already used by another employee")
    else:
        code = await make_short_code(db, emp.get("employee_id"), emp["_id"])
    await db.users.update_one({"_id": emp["_id"]}, {"$set": {"short_code": code}})
    return {"short_code": code}


@api.get("/admin/employees/{emp_id}")
async def get_employee(emp_id: str, admin: dict = Depends(admin_user)):
    doc = await db.users.find_one({"_id": oid(emp_id), "role": "employee"})
    if not doc:
        raise HTTPException(status_code=404, detail="Employee not found")
    return ser(doc)


@api.put("/admin/employees/{emp_id}")
async def update_employee(emp_id: str, body: EmployeeIn, admin: dict = Depends(admin_user)):
    _id = oid(emp_id)
    if not await db.users.find_one({"_id": _id, "role": "employee"}):
        raise HTTPException(status_code=404, detail="Employee not found")
    data = body.model_dump()
    data["email"] = data["email"].strip().lower()
    data["employee_id"] = data["employee_id"].strip().upper()
    pwd = data.pop("password")
    await check_unique(data["email"], data["employee_id"], exclude=_id)
    if pwd:
        if len(pwd) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        data["password_hash"] = hash_password(pwd)
    await db.users.update_one({"_id": _id}, {"$set": data})
    return ser(await db.users.find_one({"_id": _id}))


@api.delete("/admin/employees/{emp_id}")
async def delete_employee(emp_id: str, admin: dict = Depends(admin_user)):
    res = await db.users.delete_one({"_id": oid(emp_id), "role": "employee"})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Employee not found")
    for col in (db.service_records, db.attendance, db.requests, db.payslips, db.employee_media, db.leave_balances, db.leave_adjustments, db.appraisals, db.login_sessions, db.login_logs, db.attendance_overrides, db.push_subscriptions):
        await col.delete_many({"user_id": emp_id})
    return {"ok": True}


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6)


class AccessIn(BaseModel):
    enabled: bool


class MediaIn(BaseModel):
    photo: Optional[str] = None
    signature: Optional[str] = None


async def get_emp_or_404(emp_id: str) -> dict:
    doc = await db.users.find_one({"_id": oid(emp_id), "role": "employee"})
    if not doc:
        raise HTTPException(status_code=404, detail="Employee not found")
    return doc


@api.post("/admin/employees/{emp_id}/reset-password")
async def reset_employee_password(emp_id: str, body: ResetPasswordIn, admin: dict = Depends(admin_user)):
    doc = await get_emp_or_404(emp_id)
    await db.users.update_one({"_id": doc["_id"]}, {"$set": {"password_hash": hash_password(body.new_password), "must_change_password": True}})
    await db.login_attempts.delete_many({"identifier": {"$in": [doc["email"], doc["employee_id"].lower()]}})
    return {"ok": True}


class SlipsIn(BaseModel):
    user_ids: List[str] = Field(min_length=1, max_length=500)


SLIP_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


@api.post("/admin/credential-slips")
async def credential_slips(body: SlipsIn, admin: dict = Depends(admin_user)):
    slips = []
    for uid in dict.fromkeys(body.user_ids):
        doc = await get_emp_or_404(uid)
        pwd = "".join(secrets.choice(SLIP_CHARS) for _ in range(8))
        await db.users.update_one({"_id": doc["_id"]}, {"$set": {"password_hash": hash_password(pwd), "must_change_password": True, "slip_issued_at": now_utc()}})
        slips.append({"id": uid, "name": doc.get("name"), "employee_id": doc.get("employee_id"), "short_code": doc.get("short_code"), "designation": doc.get("designation"),
                      "department": doc.get("department"), "email": doc.get("email"), "password": pwd})
    return {"slips": slips, "issued_at": now_utc().isoformat()}


@api.patch("/admin/employees/{emp_id}/access")
async def set_employee_access(emp_id: str, body: AccessIn, admin: dict = Depends(admin_user)):
    doc = await get_emp_or_404(emp_id)
    await db.users.update_one({"_id": doc["_id"]}, {"$set": {"portal_enabled": body.enabled}})
    return ser(await db.users.find_one({"_id": doc["_id"]}))


async def media_for(user_id: str) -> dict:
    m = await db.employee_media.find_one({"user_id": user_id}) or {}
    return {"photo": m.get("photo"), "signature": m.get("signature"), "source": m.get("source")}


@api.get("/admin/employees/{emp_id}/media")
async def admin_employee_media(emp_id: str, admin: dict = Depends(admin_user)):
    await get_emp_or_404(emp_id)
    return await media_for(emp_id)


@api.post("/admin/employees/{emp_id}/media")
async def upload_employee_media(emp_id: str, body: MediaIn, admin: dict = Depends(admin_user)):
    await get_emp_or_404(emp_id)
    upd = {}
    for k in ("photo", "signature"):
        v = getattr(body, k)
        if v is not None:
            m = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", v)
            try:
                ok = bool(m) and len(v) <= 800_000 and base64.b64decode(m.group(2), validate=True)
            except Exception:
                ok = False
            if not ok:
                raise HTTPException(status_code=400, detail=f"Invalid {k} image (PNG/JPEG/WEBP, max ~500 KB)")
            upd[k] = v
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to upload")
    await db.employee_media.update_one({"user_id": emp_id}, {"$set": upd | {"source": "admin", "updated_at": now_utc()}}, upsert=True)
    return await media_for(emp_id)


@api.get("/me/media")
async def my_media(user: dict = Depends(employee_user)):
    return await media_for(user["id"])


# ---------- service records ----------
class ServiceRecordIn(BaseModel):
    user_id: str
    date: str
    type: Literal["joining", "promotion", "transfer", "appraisal", "increment", "training", "award", "other"]
    title: str
    notes: str = ""


@api.get("/service-records")
async def my_service_records(user: dict = Depends(employee_user)):
    docs = await db.service_records.find({"user_id": user["id"]}).sort("date", -1).to_list(500)
    return [ser(d) for d in docs]


@api.get("/admin/service-records")
async def admin_service_records(user_id: str, admin: dict = Depends(admin_user)):
    docs = await db.service_records.find({"user_id": user_id}).sort("date", -1).to_list(500)
    return [ser(d) for d in docs]


@api.post("/admin/service-records")
async def add_service_record(body: ServiceRecordIn, admin: dict = Depends(admin_user)):
    if not await db.users.find_one({"_id": oid(body.user_id), "role": "employee"}):
        raise HTTPException(status_code=404, detail="Employee not found")
    data = body.model_dump() | {"created_at": now_utc()}
    res = await db.service_records.insert_one(data)
    return ser(await db.service_records.find_one({"_id": res.inserted_id}))


@api.delete("/admin/service-records/{rec_id}")
async def delete_service_record(rec_id: str, admin: dict = Depends(admin_user)):
    res = await db.service_records.delete_one({"_id": oid(rec_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Record not found")
    return {"ok": True}


# ---------- attendance ----------
class PunchIn(BaseModel):
    selfie: str
    lat: float
    lng: float
    accuracy: Optional[float] = None


def punch_windows() -> dict:
    return {"in": os.environ["PUNCH_IN_WINDOW"].split("-"), "out": os.environ["PUNCH_OUT_WINDOW"].split("-")}


def check_window(kind: str):
    start, end = punch_windows()[kind]
    now = datetime.now(TZ).strftime("%H:%M")
    if not (start <= now <= end):
        label = "Punch In" if kind == "in" else "Punch Out"
        tip = " Please raise a Missed Punch request." if now > end else ""
        raise HTTPException(status_code=400, detail=f"{label} is allowed only between {start} and {end}.{tip}")


def mins(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def late_info(hm: str) -> dict:
    late = max(0, mins(hm) - mins(punch_windows()["in"][1]))
    return {"late": late > 0, "late_minutes": late}


def ist_iso(d: str, hm: str) -> str:
    return datetime.fromisoformat(f"{d}T{hm}:00").replace(tzinfo=TZ).astimezone(timezone.utc).isoformat()


def punch_payload(body: PunchIn) -> dict:
    if not body.selfie.startswith("data:image/") or len(body.selfie) > 200_000:
        raise HTTPException(status_code=400, detail="Invalid selfie image")
    return {"time": now_utc().isoformat(), "selfie": body.selfie, "lat": body.lat, "lng": body.lng, "accuracy": body.accuracy}


@api.get("/attendance/config")
async def attendance_config(user: dict = Depends(current_user)):
    return {"windows": punch_windows(), "server_time": now_utc().isoformat(), "timezone": os.environ["APP_TIMEZONE"], "auto_submit_seconds": 30}


@api.get("/attendance/today")
async def attendance_today(user: dict = Depends(employee_user)):
    return ser(await db.attendance.find_one({"user_id": user["id"], "date": today_str()}))


@api.post("/attendance/punch-in")
async def punch_in(body: PunchIn, user: dict = Depends(employee_user)):
    today = today_str()
    if await db.attendance.find_one({"user_id": user["id"], "date": today}):
        raise HTTPException(status_code=400, detail="Already punched in today")
    now_hm = datetime.now(TZ).strftime("%H:%M")
    w = punch_windows()
    if now_hm < w["in"][0]:
        raise HTTPException(status_code=400, detail=f"Punch In opens at {w['in'][0]}")
    if now_hm > w["out"][1]:
        raise HTTPException(status_code=400, detail="Punch In is closed for today. Please raise a Missed Punch request.")
    res = await db.attendance.insert_one({"user_id": user["id"], "date": today, "punch_in": punch_payload(body), "punch_out": None, "work_minutes": 0, **late_info(now_hm), "created_at": now_utc()})
    spawn_push(user)
    return ser(await db.attendance.find_one({"_id": res.inserted_id}))


@api.post("/attendance/punch-out")
async def punch_out(body: PunchIn, user: dict = Depends(employee_user)):
    rec = await db.attendance.find_one({"user_id": user["id"], "date": today_str()})
    if not rec:
        raise HTTPException(status_code=400, detail="Please punch in first")
    if rec.get("punch_out"):
        raise HTTPException(status_code=400, detail="Already punched out today")
    check_window("out")
    out = punch_payload(body)
    minutes = int((datetime.fromisoformat(out["time"]) - datetime.fromisoformat(rec["punch_in"]["time"])).total_seconds() // 60)
    await db.attendance.update_one({"_id": rec["_id"]}, {"$set": {"punch_out": out, "work_minutes": minutes}})
    spawn_push(user)
    return ser(await db.attendance.find_one({"_id": rec["_id"]}))


@api.get("/attendance")
async def my_attendance(month: Optional[str] = None, user: dict = Depends(employee_user)):
    q = {"user_id": user["id"]}
    if month:
        q["date"] = {"$regex": f"^{month}"}
    docs = await db.attendance.find(q).sort("date", -1).to_list(400)
    return [ser(d) for d in docs]


@api.get("/admin/attendance")
async def admin_attendance(date: Optional[str] = None, month: Optional[str] = None, user_id: Optional[str] = None, admin: dict = Depends(admin_user)):
    q = {}
    if date:
        q["date"] = date
    elif month:
        q["date"] = {"$regex": f"^{month}"}
    if user_id:
        q["user_id"] = user_id
    docs = await db.attendance.find(q).sort([("date", -1), ("created_at", -1)]).to_list(300)
    return await attach_employee([ser(d) for d in docs])


# ---------- requests ----------
class RequestIn(BaseModel):
    type: Literal["leave", "advance", "payslip", "missed_punch", "other"]
    leave_type: str = ""
    start_date: str = ""
    end_date: str = ""
    amount: float = 0
    repayment: str = ""
    month: str = ""
    punch_date: str = ""
    missed: Literal["in", "out", "both", ""] = ""
    in_time: str = ""
    out_time: str = ""
    subject: str = ""
    reason: str = ""


HM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


async def validate_missed_punch(body: RequestIn, user_id: str):
    try:
        d = date_cls.fromisoformat(body.punch_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Select a valid date")
    if d.isoformat() > today_str():
        raise HTTPException(status_code=400, detail="Date cannot be in the future")
    if not body.missed:
        raise HTTPException(status_code=400, detail="Select which punch was missed")
    need_in, need_out = body.missed in ("in", "both"), body.missed in ("out", "both")
    if (need_in and not HM_RE.match(body.in_time)) or (need_out and not HM_RE.match(body.out_time)):
        raise HTTPException(status_code=400, detail="Enter valid time (HH:MM)")
    rec = await db.attendance.find_one({"user_id": user_id, "date": body.punch_date})
    if need_in and rec and rec.get("punch_in"):
        raise HTTPException(status_code=400, detail="Punch In already exists for this date")
    if need_out and rec and rec.get("punch_out"):
        raise HTTPException(status_code=400, detail="Punch Out already exists for this date")
    if body.missed == "out" and not (rec and rec.get("punch_in")):
        raise HTTPException(status_code=400, detail="No Punch In on this date. Select 'Both In & Out'.")
    in_hm = body.in_time if need_in else datetime.fromisoformat(rec["punch_in"]["time"]).astimezone(TZ).strftime("%H:%M")
    if need_out and body.out_time <= in_hm:
        raise HTTPException(status_code=400, detail="Out time must be after In time")
    if await db.requests.find_one({"user_id": user_id, "type": "missed_punch", "punch_date": body.punch_date, "status": "pending"}):
        raise HTTPException(status_code=400, detail="A Missed Punch request for this date is already pending")


async def apply_missed_punch(r: dict):
    rec = await db.attendance.find_one({"user_id": r["user_id"], "date": r["punch_date"]}) or {}
    manual = lambda hm: {"time": ist_iso(r["punch_date"], hm), "selfie": None, "lat": None, "lng": None, "accuracy": None, "manual": True}
    upd = {"manual": True}
    if r["missed"] in ("in", "both") and not rec.get("punch_in"):
        upd["punch_in"] = manual(r["in_time"])
        upd.update(late_info(r["in_time"]))
    if r["missed"] in ("out", "both") and not rec.get("punch_out"):
        upd["punch_out"] = manual(r["out_time"])
    pin, pout = upd.get("punch_in") or rec.get("punch_in"), upd.get("punch_out") or rec.get("punch_out")
    if pin and pout:
        upd["work_minutes"] = max(0, int((datetime.fromisoformat(pout["time"]) - datetime.fromisoformat(pin["time"])).total_seconds() // 60))
    if rec:
        await db.attendance.update_one({"_id": rec["_id"]}, {"$set": upd})
    else:
        await db.attendance.insert_one({"user_id": r["user_id"], "date": r["punch_date"], "punch_out": None, "work_minutes": 0, "created_at": now_utc(), **upd})


class DecisionIn(BaseModel):
    status: Literal["approved", "rejected"]
    admin_comment: str = ""


@api.post("/requests")
async def create_request(body: RequestIn, user: dict = Depends(employee_user)):
    data = body.model_dump()
    if body.type == "leave":
        try:
            s, e = date_cls.fromisoformat(body.start_date), date_cls.fromisoformat(body.end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Valid start and end dates are required")
        if e < s:
            raise HTTPException(status_code=400, detail="End date cannot be before start date")
        data["days"] = ((e - s).days + 1) * (0.5 if body.leave_type == "Half Day" else 1)
        await check_leave_balance(user["id"], body.start_date[:4], body.leave_type, data["days"], include_pending=True)
    elif body.type == "advance" and body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
    elif body.type == "payslip":
        valid_month(body.month)
    elif body.type == "missed_punch":
        await validate_missed_punch(body, user["id"])
    elif body.type == "other" and not body.subject.strip():
        raise HTTPException(status_code=400, detail="Subject is required")
    data.update({"user_id": user["id"], "status": "pending", "admin_comment": "", "created_at": now_utc(), "decided_at": None})
    res = await db.requests.insert_one(data)
    return ser(await db.requests.find_one({"_id": res.inserted_id}))


@api.get("/requests")
async def my_requests(user: dict = Depends(employee_user)):
    docs = await db.requests.find({"user_id": user["id"]}).sort("created_at", -1).to_list(1000)
    return [ser(d) for d in docs]


@api.delete("/requests/{req_id}")
async def cancel_request(req_id: str, user: dict = Depends(employee_user)):
    res = await db.requests.delete_one({"_id": oid(req_id), "user_id": user["id"], "status": "pending"})
    if not res.deleted_count:
        raise HTTPException(status_code=400, detail="Only pending requests can be cancelled")
    return {"ok": True}


@api.get("/admin/requests")
async def admin_requests(status: Optional[str] = None, type: Optional[str] = None, admin: dict = Depends(admin_user)):
    q = {}
    if status:
        q["status"] = status
    if type:
        q["type"] = type
    docs = await db.requests.find(q).sort("created_at", -1).to_list(2000)
    items = await attach_employee([ser(d) for d in docs])
    cache = {}
    for r in items:
        if r["type"] != "leave" or not r.get("start_date"):
            continue
        key = (r["user_id"], r["start_date"][:4])
        if key not in cache:
            cache[key] = await compute_balance(*key)
        b = cache[key]
        row = next((x for x in b["balances"] if x["leave_type"] == bal_type(r.get("leave_type"))), None) if b["configured"] else None
        r["balance"] = row and {k: row[k] for k in ("leave_type", "allotted", "used", "pending", "available")}
    return items


@api.patch("/admin/requests/{req_id}")
async def decide_request(req_id: str, body: DecisionIn, admin: dict = Depends(admin_user)):
    req = await db.requests.find_one({"_id": oid(req_id), "status": "pending"})
    if not req:
        raise HTTPException(status_code=400, detail="Request not found or already decided")
    if body.status == "approved" and req["type"] == "missed_punch":
        await apply_missed_punch(req)
    if body.status == "approved" and req["type"] == "leave":
        await check_leave_balance(req["user_id"], req["start_date"][:4], req.get("leave_type"), req.get("days", 0), include_pending=False)
    await db.requests.update_one(
        {"_id": req["_id"]},
        {"$set": {"status": body.status, "admin_comment": body.admin_comment, "decided_at": now_utc()}},
    )
    if body.status == "approved" and req["type"] in ("leave", "missed_punch"):
        spawn_push(await db.users.find_one({"_id": oid(req["user_id"])}) or {})
    return ser(await db.requests.find_one({"_id": req["_id"]}))


async def sheet_row(e: dict, month: str) -> dict:
    y, m = int(month[:4]), int(month[5:])
    ndays = calendar.monthrange(y, m)[1]
    first, last = f"{month}-01", f"{month}-{ndays:02d}"
    uid = str(e["_id"])
    va = await db.vendor_attendance.find_one({"user_id": uid, "year": y, "month": m}) or {}
    vlate = va.get("late") or {}
    cells = {dd: {"code": c, "source": "hr", "late": vlate.get(dd) or 0} for dd, c in (va.get("days") or {}).items() if c}
    for a in await db.attendance.find({"user_id": uid, "date": {"$regex": f"^{month}"}}, {"date": 1, "punch_in.time": 1, "punch_out.time": 1, "late": 1, "late_minutes": 1, "manual": 1}).to_list(40):
        dd = a["date"][8:10]
        prev = (cells.get(dd) or {}).get("code")
        cells[dd] = {"code": prev if prev not in (None, "", "A") else "P", "source": "portal", "manual": bool(a.get("manual")),
                     "in": (a.get("punch_in") or {}).get("time"), "out": (a.get("punch_out") or {}).get("time"), "late": a.get("late_minutes", 0) if a.get("late") else 0}
    for lv in await db.requests.find({"user_id": uid, "type": "leave", "status": "approved", "start_date": {"$lte": last}, "end_date": {"$gte": first}}).to_list(50):
        d = max(date_cls.fromisoformat(lv["start_date"]), date_cls.fromisoformat(first))
        while d <= min(date_cls.fromisoformat(lv["end_date"]), date_cls.fromisoformat(last)):
            cells.setdefault(f"{d.day:02d}", {"code": "H" if lv.get("leave_type") == "Half Day" else "L", "source": "leave", "note": lv.get("leave_type")})
            d += timedelta(days=1)
    for o in await db.attendance_overrides.find({"user_id": uid, "date": {"$regex": f"^{month}"}}).to_list(40):
        dd = o["date"][8:10]
        base = cells.get(dd) or {}
        cells[dd] = {**base, "code": o["code"], "source": "admin", "late": base.get("late", 0) if o["code"] == "P" else 0, "note": f"Edited by admin{' (' + o['reason'] + ')' if o.get('reason') else ''}"}
    totals = {}
    for c in cells.values():
        totals[c["code"]] = totals.get(c["code"], 0) + 1
    totals["late"] = sum(1 for c in cells.values() if c.get("late"))
    return {"user_id": uid, "name": e.get("name"), "employee_id": e.get("employee_id"), "short_code": e.get("short_code"), "department": e.get("department"), "cells": cells, "totals": totals}


@api.get("/admin/attendance-sheet")
async def attendance_sheet(month: str, admin: dict = Depends(admin_user)):
    valid_month(month)
    ndays = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    emps = await db.users.find({"role": "employee"}, {"name": 1, "employee_id": 1, "short_code": 1, "department": 1}).sort("employee_id", 1).to_list(5000)
    rows = [await sheet_row(e, month) for e in emps]
    last_sync = await db.sync_logs.find_one({"status": "success"}, sort=[("started_at", -1)])
    return {"month": month, "days": ndays, "rows": rows, "last_sync": last_sync["finished_at"].isoformat() if last_sync else None}


class SheetVisibilityIn(BaseModel):
    enabled: bool


async def employee_sheet_enabled() -> bool:
    doc = await db.settings.find_one({"_id": "portal"}) or {}
    return bool(doc.get("employee_sheet_visible"))


@api.get("/admin/settings/employee-sheet")
async def get_sheet_visibility(admin: dict = Depends(admin_user)):
    return {"enabled": await employee_sheet_enabled()}


@api.put("/admin/settings/employee-sheet")
async def set_sheet_visibility(body: SheetVisibilityIn, admin: dict = Depends(admin_user)):
    await db.settings.update_one({"_id": "portal"}, {"$set": {"employee_sheet_visible": body.enabled, "updated_at": now_utc()}}, upsert=True)
    return {"enabled": body.enabled}


@api.get("/attendance/my-sheet")
async def my_sheet(user: dict = Depends(employee_user)):
    if not await employee_sheet_enabled():
        return {"enabled": False, "months": []}
    first = datetime.now(TZ).date().replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    emp = await db.users.find_one({"_id": oid(user["id"])}, {"name": 1, "employee_id": 1, "department": 1})
    months = []
    for d in (prev, first):
        mk = d.strftime("%Y-%m")
        row = await sheet_row(emp, mk)
        months.append({"month": mk, "days": calendar.monthrange(d.year, d.month)[1], "cells": row["cells"], "totals": row["totals"]})
    return {"enabled": True, "months": months}


class SheetCellIn(BaseModel):
    user_id: str
    date: str
    code: str
    reason: Optional[str] = ""


SHEET_CODES = {"P", "A", "L", "H", "W", "HL"}


@api.put("/admin/attendance-sheet/cell")
async def edit_sheet_cell(body: SheetCellIn, admin: dict = Depends(admin_user)):
    try:
        date_cls.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    if body.code not in SHEET_CODES:
        raise HTTPException(status_code=400, detail=f"Code must be one of {', '.join(sorted(SHEET_CODES))}")
    emp = await db.users.find_one({"_id": oid(body.user_id), "role": "employee"})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.attendance_overrides.update_one(
        {"user_id": body.user_id, "date": body.date},
        {"$set": {"code": body.code, "reason": (body.reason or "").strip(), "by": admin.get("email"), "updated_at": now_utc()}}, upsert=True)
    if not emp.get("vendor_id"):
        return {"saved": True, "hr_updated": False, "hr_message": "Employee is not linked to HR Management"}
    try:
        await push_day(db, body.user_id, emp["vendor_id"], body.date, body.code)
        return {"saved": True, "hr_updated": True}
    except Exception as e:
        logger.exception("Sheet cell push failed")
        return {"saved": True, "hr_updated": False, "hr_message": f"HR Management update failed: {e}"}


# ---------- leave balance ----------
TRACKED_LEAVES = ["Casual Leave", "Sick Leave", "Earned Leave"]


def bal_type(lt: str) -> str:
    return "Casual Leave" if lt == "Half Day" else lt


async def compute_balance(uid: str, year: str) -> dict:
    doc = await db.leave_balances.find_one({"user_id": uid, "year": year}) or {}
    quotas = doc.get("quotas") or {}
    adjs = await db.leave_adjustments.find({"user_id": uid, "year": year}).sort("created_at", -1).to_list(500)
    reqs = await db.requests.find({"user_id": uid, "type": "leave", "status": {"$in": ["approved", "pending"]}, "start_date": {"$regex": f"^{year}"}}).to_list(1000)
    out = []
    for lt in TRACKED_LEAVES:
        adj = sum(a["days"] for a in adjs if a["leave_type"] == lt)
        used = sum(r.get("days", 0) for r in reqs if r["status"] == "approved" and bal_type(r.get("leave_type")) == lt)
        pending = sum(r.get("days", 0) for r in reqs if r["status"] == "pending" and bal_type(r.get("leave_type")) == lt)
        quota = float(quotas.get(lt, 0))
        out.append({"leave_type": lt, "quota": quota, "adjustment": adj, "allotted": quota + adj, "used": used, "pending": pending, "available": quota + adj - used})
    return {"year": year, "configured": bool(doc), "balances": out, "adjustments": [ser(a) for a in adjs]}


async def check_leave_balance(uid: str, year: str, leave_type: str, days: float, include_pending: bool):
    lt = bal_type(leave_type)
    if lt not in TRACKED_LEAVES:
        return
    b = await compute_balance(uid, year)
    if not b["configured"]:
        return
    row = next(x for x in b["balances"] if x["leave_type"] == lt)
    free = row["available"] - (row["pending"] if include_pending else 0)
    if days > free and include_pending:
        emp = await db.users.find_one({"_id": oid(uid)}, {"leave_balance_live": 1}) or {}
        if emp.get("leave_balance_live") is False:
            raise HTTPException(status_code=400, detail=f"Not enough {lt} balance for this request. Contact HR.")
    if days > free:
        raise HTTPException(status_code=400, detail=f"Insufficient {lt} balance. Available: {free:g} day(s), requested: {days:g}")


class QuotaIn(BaseModel):
    year: str = Field(pattern=r"^\d{4}$")
    quotas: dict
    apply_to_all: bool = False


class AdjustIn(BaseModel):
    year: str = Field(pattern=r"^\d{4}$")
    leave_type: Literal["Casual Leave", "Sick Leave", "Earned Leave"]
    days: float
    reason: str = Field(min_length=1)


def this_year() -> str:
    return today_str()[:4]


@api.get("/leave-balance")
async def my_leave_balance(year: Optional[str] = None, user: dict = Depends(employee_user)):
    if user.get("leave_balance_live") is False:
        return {"year": year or this_year(), "live": False, "configured": False, "balances": [], "adjustments": []}
    return await compute_balance(user["id"], year or this_year()) | {"live": True}


SHORT_LEAVES = {"CL": "Casual Leave", "SL": "Sick Leave", "EL": "Earned Leave"}


class LeaveLiveIn(BaseModel):
    live: bool
    user_ids: Optional[List[str]] = None


@api.get("/admin/leave-balances")
async def all_leave_balances(year: Optional[str] = None, admin: dict = Depends(admin_user)):
    year = year or this_year()
    emps = await db.users.find({"role": "employee"}, {"name": 1, "employee_id": 1, "short_code": 1, "department": 1, "leave_balance_live": 1, "active": 1}).sort("employee_id", 1).to_list(5000)
    out = []
    for e in emps:
        b = await compute_balance(str(e["_id"]), year)
        out.append({"user_id": str(e["_id"]), "name": e.get("name"), "employee_id": e.get("employee_id"), "short_code": e.get("short_code"), "department": e.get("department"), "active": e.get("active", True),
                    "live": e.get("leave_balance_live") is not False, "configured": b["configured"], "balances": b["balances"]})
    return {"year": year, "rows": out}


@api.put("/admin/leave-balances/live")
async def set_leave_live(body: LeaveLiveIn, admin: dict = Depends(admin_user)):
    q = {"role": "employee"}
    if body.user_ids is not None:
        if not body.user_ids:
            raise HTTPException(status_code=400, detail="user_ids cannot be empty")
        q["_id"] = {"$in": [oid(u) for u in body.user_ids]}
    res = await db.users.update_many(q, {"$set": {"leave_balance_live": body.live}})
    return {"live": body.live, "updated": res.matched_count}


@api.post("/admin/leave-balances/upload")
async def upload_leave_balances(year: str = Form(...), file: UploadFile = File(...), admin: dict = Depends(admin_user)):
    if not re.fullmatch(r"\d{4}", year):
        raise HTTPException(status_code=400, detail="Year must be YYYY")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())
    cols = {norm(c): c for c in (reader.fieldnames or [])}
    code_col = cols.get("employeecode") or cols.get("employeeid") or cols.get("empcode") or cols.get("code")
    lt_cols = {lt: cols.get(norm(short)) or cols.get(norm(lt)) for short, lt in SHORT_LEAVES.items()}
    live_col = cols.get("live") or cols.get("showtoemployee")
    if not code_col or not any(lt_cols.values()):
        raise HTTPException(status_code=400, detail="CSV needs an 'Employee Code' column and at least one of CL, SL, EL")
    updated, errors = 0, []
    for i, row in enumerate(reader, start=2):
        code = (row.get(code_col) or "").strip().upper()
        if not code:
            continue
        emp = await db.users.find_one({"$or": [{"employee_id": code}, {"short_code": code}], "role": "employee"}, {"_id": 1})
        if not emp:
            errors.append(f"Row {i}: employee code {code} not found")
            continue
        uid = str(emp["_id"])
        doc = await db.leave_balances.find_one({"user_id": uid, "year": year}) or {}
        quotas = dict(doc.get("quotas") or {})
        bad = False
        for lt, col in lt_cols.items():
            if not col or str(row.get(col) or "").strip() == "":
                continue
            try:
                v = float(str(row[col]).strip())
            except ValueError:
                v = -1
            if v < 0 or v > 365:
                errors.append(f"Row {i}: invalid {lt} value '{row[col]}'")
                bad = True
                break
            quotas[lt] = v
        if bad:
            continue
        await db.leave_balances.update_one({"user_id": uid, "year": year}, {"$set": {"quotas": quotas, "updated_at": now_utc()}}, upsert=True)
        if live_col and str(row.get(live_col) or "").strip():
            await db.users.update_one({"_id": emp["_id"]}, {"$set": {"leave_balance_live": str(row[live_col]).strip().lower() in ("yes", "y", "live", "1", "true", "on")}})
        updated += 1
    return {"updated": updated, "errors": errors[:50]}


@api.get("/admin/leave-balance/{emp_id}")
async def admin_leave_balance(emp_id: str, year: Optional[str] = None, admin: dict = Depends(admin_user)):
    await get_emp_or_404(emp_id)
    return await compute_balance(emp_id, year or this_year())


@api.put("/admin/leave-balance/{emp_id}")
async def set_leave_quota(emp_id: str, body: QuotaIn, admin: dict = Depends(admin_user)):
    await get_emp_or_404(emp_id)
    quotas = {}
    for lt in TRACKED_LEAVES:
        try:
            v = float(body.quotas.get(lt, 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid quota for {lt}")
        if v < 0 or v > 365:
            raise HTTPException(status_code=400, detail=f"Quota for {lt} must be 0-365")
        quotas[lt] = v
    ids = [emp_id]
    if body.apply_to_all:
        ids = [str(d["_id"]) for d in await db.users.find({"role": "employee"}, {"_id": 1}).to_list(5000)]
    for uid in ids:
        await db.leave_balances.update_one({"user_id": uid, "year": body.year}, {"$set": {"quotas": quotas, "updated_at": now_utc()}}, upsert=True)
    return await compute_balance(emp_id, body.year) | {"applied_to": len(ids)}


@api.post("/admin/leave-balance/{emp_id}/adjust")
async def adjust_leave(emp_id: str, body: AdjustIn, admin: dict = Depends(admin_user)):
    await get_emp_or_404(emp_id)
    if body.days == 0 or abs(body.days) > 365:
        raise HTTPException(status_code=400, detail="Adjustment days must be non-zero (max 365)")
    if not await db.leave_balances.find_one({"user_id": emp_id, "year": body.year}):
        await db.leave_balances.insert_one({"user_id": emp_id, "year": body.year, "quotas": {}, "updated_at": now_utc()})
    await db.leave_adjustments.insert_one(body.model_dump() | {"user_id": emp_id, "created_at": now_utc()})
    return await compute_balance(emp_id, body.year)


@api.delete("/admin/leave-adjustments/{adj_id}")
async def delete_adjustment(adj_id: str, admin: dict = Depends(admin_user)):
    res = await db.leave_adjustments.delete_one({"_id": oid(adj_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return {"ok": True}


# ---------- performance appraisals ----------
CRITERIA = ["Work Quality", "Punctuality", "Teamwork", "Communication", "Initiative", "Discipline"]


def grade_for(score: float) -> str:
    for cut, g in ((4.5, "Outstanding"), (3.5, "Very Good"), (2.5, "Good"), (1.5, "Needs Improvement")):
        if score >= cut:
            return g
    return "Poor"


class AppraisalIn(BaseModel):
    user_id: str
    period: str = Field(min_length=1)
    review_date: str
    ratings: dict
    reviewer: str = ""
    strengths: str = ""
    improvements: str = ""
    remarks: str = ""
    recommendation: Literal["none", "increment", "promotion", "training", "pip"] = "none"


@api.post("/admin/appraisals")
async def add_appraisal(body: AppraisalIn, admin: dict = Depends(admin_user)):
    await get_emp_or_404(body.user_id)
    try:
        date_cls.fromisoformat(body.review_date)
        raw = {c: body.ratings[c] for c in CRITERIA}
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Valid review date and a rating for every criterion are required")
    if not body.period.strip() or any(type(v) is not int or not 1 <= v <= 5 for v in raw.values()):
        raise HTTPException(status_code=400, detail="Period is required and ratings must be whole numbers 1-5")
    ratings = raw
    score = round(sum(ratings.values()) / len(ratings), 1)
    data = body.model_dump() | {"ratings": ratings, "score": score, "grade": grade_for(score), "created_at": now_utc()}
    res = await db.appraisals.insert_one(data)
    return ser(await db.appraisals.find_one({"_id": res.inserted_id}))


@api.get("/admin/appraisals")
async def list_appraisals(user_id: str, admin: dict = Depends(admin_user)):
    return [ser(d) for d in await db.appraisals.find({"user_id": user_id}).sort("review_date", -1).to_list(200)]


@api.delete("/admin/appraisals/{ap_id}")
async def delete_appraisal(ap_id: str, admin: dict = Depends(admin_user)):
    res = await db.appraisals.delete_one({"_id": oid(ap_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Appraisal not found")
    return {"ok": True}


@api.get("/appraisals")
async def my_appraisals(user: dict = Depends(employee_user)):
    return [ser(d) for d in await db.appraisals.find({"user_id": user["id"]}).sort("review_date", -1).to_list(200)]


# ---------- payslips ----------
class LineItem(BaseModel):
    label: str
    amount: float = 0


class PayslipGenIn(BaseModel):
    user_id: str
    month: str
    working_days: float = 0
    paid_days: float = 0
    earnings: List[LineItem]
    deductions: List[LineItem] = []


def valid_month(m: str):
    try:
        datetime.strptime(m, "%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="Month must be YYYY-MM")


async def publish_payslip(user_id: str, month: str, data: dict):
    await db.payslips.delete_many({"user_id": user_id, "month": month})
    data.update({"user_id": user_id, "month": month, "created_at": now_utc()})
    res = await db.payslips.insert_one(data)
    await db.requests.update_many(
        {"user_id": user_id, "type": "payslip", "month": month, "status": "pending"},
        {"$set": {"status": "approved", "admin_comment": "Payslip published", "decided_at": now_utc()}},
    )
    return ser(await db.payslips.find_one({"_id": res.inserted_id}))


@api.post("/admin/payslips/generate")
async def generate_payslip(body: PayslipGenIn, admin: dict = Depends(admin_user)):
    valid_month(body.month)
    if not await db.users.find_one({"_id": oid(body.user_id), "role": "employee"}):
        raise HTTPException(status_code=404, detail="Employee not found")
    earnings = [i.model_dump() for i in body.earnings if i.label.strip()]
    deductions = [i.model_dump() for i in body.deductions if i.label.strip()]
    gross = round(sum(i["amount"] for i in earnings), 2)
    total_ded = round(sum(i["amount"] for i in deductions), 2)
    return await publish_payslip(body.user_id, body.month, {
        "kind": "generated", "working_days": body.working_days, "paid_days": body.paid_days,
        "earnings": earnings, "deductions": deductions, "gross": gross, "total_deductions": total_ded, "net": round(gross - total_ded, 2),
    })


@api.post("/admin/payslips/upload")
async def upload_payslip(user_id: str = Form(...), month: str = Form(...), net: float = Form(0), file: UploadFile = File(...), admin: dict = Depends(admin_user)):
    valid_month(month)
    if not await db.users.find_one({"_id": oid(user_id), "role": "employee"}):
        raise HTTPException(status_code=404, detail="Employee not found")
    content = await file.read()
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF must be under 4 MB")
    return await publish_payslip(user_id, month, {
        "kind": "uploaded", "file_name": file.filename, "pdf_b64": base64.b64encode(content).decode(), "net": net,
    })


@api.get("/payslips")
async def my_payslips(user: dict = Depends(employee_user)):
    docs = await db.payslips.find({"user_id": user["id"]}, {"pdf_b64": 0}).sort("month", -1).to_list(500)
    return [ser(d) for d in docs]


@api.get("/admin/payslips")
async def admin_payslips(user_id: Optional[str] = None, month: Optional[str] = None, admin: dict = Depends(admin_user)):
    q = {}
    if user_id:
        q["user_id"] = user_id
    if month:
        q["month"] = month
    docs = await db.payslips.find(q, {"pdf_b64": 0}).sort("month", -1).to_list(2000)
    return await attach_employee([ser(d) for d in docs])


@api.get("/payslips/{slip_id}/pdf")
async def payslip_pdf(slip_id: str, user: dict = Depends(current_user)):
    slip = await db.payslips.find_one({"_id": oid(slip_id)})
    if not slip or (user["role"] not in STAFF_ROLES and slip["user_id"] != user["id"]):
        raise HTTPException(status_code=404, detail="Payslip not found")
    if user["role"] in STAFF_ROLES and not has_perm(user, "payslips", "view"):
        raise HTTPException(status_code=403, detail="You don't have view permission for payslips")
    if slip["kind"] == "uploaded":
        content = base64.b64decode(slip["pdf_b64"])
    else:
        emp = await db.users.find_one({"_id": oid(slip["user_id"])}) or {}
        company = {"name": os.environ["COMPANY_NAME"], "address": os.environ["COMPANY_ADDRESS"], "contact": os.environ["COMPANY_CONTACT"], "logo": str(ROOT_DIR / os.environ["COMPANY_LOGO"])}
        content = build_payslip_pdf(slip, emp, company)
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="payslip-{slip["month"]}.pdf"'})


@api.delete("/admin/payslips/{slip_id}")
async def delete_payslip(slip_id: str, admin: dict = Depends(admin_user)):
    res = await db.payslips.delete_one({"_id": oid(slip_id)})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Payslip not found")
    return {"ok": True}


# ---------- dashboards ----------
@api.get("/admin/stats")
async def admin_stats(admin: dict = Depends(admin_user)):
    today = today_str()
    return {
        "employees": await db.users.count_documents({"role": "employee", "active": True}),
        "present_today": await db.attendance.count_documents({"date": today}),
        "late_today": await db.attendance.count_documents({"date": today, "late": True}),
        "pending_requests": await db.requests.count_documents({"status": "pending"}),
        "on_leave_today": await db.requests.count_documents({"type": "leave", "status": "approved", "start_date": {"$lte": today}, "end_date": {"$gte": today}}),
        "today": today,
    }


@api.get("/me/summary")
async def my_summary(user: dict = Depends(employee_user)):
    today = today_str()
    leaves = await db.requests.find({"user_id": user["id"], "type": "leave", "status": "approved", "start_date": {"$regex": f"^{today[:4]}"}}).to_list(500)
    last = await db.payslips.find_one({"user_id": user["id"]}, {"pdf_b64": 0}, sort=[("month", -1)])
    return {
        "present_this_month": await db.attendance.count_documents({"user_id": user["id"], "date": {"$regex": f"^{today[:7]}"}}),
        "pending_requests": await db.requests.count_documents({"user_id": user["id"], "status": "pending"}),
        "leave_days_year": sum(l.get("days", 0) for l in leaves),
        "last_payslip": ser(last),
        "today": today,
    }


# ---------- vendor portal sync ----------
_bg_tasks = set()


def spawn_push(user: dict):
    if user.get("vendor_id"):
        task = asyncio.create_task(push_now(db, str(user.get("id") or user["_id"]), datetime.now(TZ).date()))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

@api.post("/admin/vendor-sync")
async def vendor_sync_now(admin: dict = Depends(admin_user)):
    return await run_sync(db, hash_password, datetime.now(TZ).date(), "manual")


@api.get("/admin/vendor-sync/status")
async def vendor_sync_status(admin: dict = Depends(admin_user)):
    return ser(await db.sync_logs.find_one({}, sort=[("started_at", -1)]))


@api.post("/cron/vendor-sync")
async def cron_vendor_sync(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], os.environ["WEBHOOK_CRON_SECRET"]):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is not None and not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("X-Webhook-Id") or (body or {}).get("run_id")
    if run_id and await db.sync_logs.find_one({"run_id": run_id}):
        return {"accepted": True, "duplicate": True}
    task = asyncio.create_task(run_sync(db, hash_password, datetime.now(TZ).date(), "cron", run_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"accepted": True}


class PushSubIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=2048)
    keys: dict = {}


def _webpush_sync(sub: dict, payload: dict):
    webpush(subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]}, data=json.dumps(payload),
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"], vapid_claims={"sub": os.environ["VAPID_SUBJECT"]}, ttl=3600)


async def push_to_user(uid: str, payload: dict) -> int:
    sent = 0
    for s in await db.push_subscriptions.find({"user_id": uid}).to_list(20):
        try:
            await asyncio.to_thread(_webpush_sync, s, payload)
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code in (404, 410):
                await db.push_subscriptions.delete_one({"_id": s["_id"]})
            else:
                logger.warning("Push failed (%s) for user %s", code, uid)
        except Exception:
            logger.exception("Push error for user %s", uid)
    return sent


@api.get("/push/public-key")
async def push_public_key():
    return {"publicKey": os.environ["VAPID_PUBLIC_KEY"]}


@api.get("/push/status")
async def push_status(user: dict = Depends(employee_user)):
    return {"devices": await db.push_subscriptions.count_documents({"user_id": user["id"]})}


@api.post("/push/subscribe")
async def push_subscribe(body: PushSubIn, request: Request, user: dict = Depends(employee_user)):
    if not body.endpoint.startswith("https://") or not {"p256dh", "auth"} <= set(body.keys):
        raise HTTPException(status_code=400, detail="Invalid push subscription")
    await db.push_subscriptions.update_one({"endpoint": body.endpoint}, {"$set": {
        "user_id": user["id"], "keys": {"p256dh": str(body.keys["p256dh"]), "auth": str(body.keys["auth"])},
        "user_agent": request.headers.get("user-agent", "")[:300], "updated_at": now_utc()}}, upsert=True)
    return {"ok": True}


@api.post("/push/unsubscribe")
async def push_unsubscribe(body: PushSubIn, user: dict = Depends(employee_user)):
    await db.push_subscriptions.delete_one({"endpoint": body.endpoint, "user_id": user["id"]})
    return {"ok": True}


@api.post("/push/test")
async def push_test(user: dict = Depends(employee_user)):
    sent = await push_to_user(user["id"], {"title": "ARUN ENTERPRISES", "body": "Test reminder: punch notifications are working.", "url": "/employee", "tag": "punch-test"})
    return {"sent": sent}


REMINDER_TEXT = {
    "in": ("Punch In reminder", "Good morning {name}! Punch In window is open ({win}). Tap to punch now."),
    "out": ("Punch Out reminder", "{name}, don't forget to Punch Out ({win}). Tap to punch now."),
}


async def run_punch_reminder(kind: str, run_id: Optional[str]):
    today = today_str()
    uids = await db.push_subscriptions.distinct("user_id")
    emps = await db.users.find({"_id": {"$in": [oid(u) for u in uids]}, "role": "employee", "active": {"$ne": False}, "portal_enabled": {"$ne": False}}, {"name": 1}).to_list(5000)
    att = {a["user_id"]: a for a in await db.attendance.find({"date": today}, {"user_id": 1, "punch_out": 1}).to_list(5000)}
    on_leave = set(await db.requests.distinct("user_id", {"type": "leave", "status": "approved", "start_date": {"$lte": today}, "end_date": {"$gte": today}}))
    win = os.environ["PUNCH_IN_WINDOW" if kind == "in" else "PUNCH_OUT_WINDOW"].replace("-", " – ")
    title, body = REMINDER_TEXT[kind]
    sent = 0
    for e in emps:
        uid = str(e["_id"])
        a = att.get(uid)
        if uid in on_leave or (kind == "in" and a) or (kind == "out" and (not a or a.get("punch_out"))):
            continue
        sent += await push_to_user(uid, {"title": title, "body": body.format(name=(e.get("name") or "").split(" ")[0], win=win), "url": "/employee", "tag": f"punch-{kind}-{today}"})
    await db.reminder_logs.update_one({"run_id": run_id, "kind": kind, "date": today}, {"$set": {"sent": sent, "finished_at": now_utc()}})


@api.post("/cron/punch-reminder-{kind}")
async def cron_punch_reminder(kind: str, request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], os.environ["WEBHOOK_CRON_SECRET"]):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if kind not in ("in", "out"):
        raise HTTPException(status_code=404, detail="Unknown reminder")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if body is not None and not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("X-Webhook-Id") or (body or {}).get("run_id") or secrets.token_hex(8)
    try:
        await db.reminder_logs.insert_one({"run_id": run_id, "kind": kind, "date": today_str(), "started_at": now_utc(), "sent": 0})
    except DuplicateKeyError:
        return {"accepted": True, "duplicate": True}
    task = asyncio.create_task(run_punch_reminder(kind, run_id))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"accepted": True}


class StaffUserIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=120)
    mobile: str = Field(default="", max_length=15)
    password: Optional[str] = None
    confirm_password: Optional[str] = None
    role: str
    permissions: dict = {}
    active: bool = True


def _clean_perms(p: dict) -> dict:
    return {m: {a: bool(((p or {}).get(m) or {}).get(a)) for a in ACTIONS} for m in MODULES}


def _staff_out(d: dict) -> dict:
    return {"id": str(d["_id"]), "name": d.get("name"), "email": d.get("email"), "mobile": d.get("mobile", ""), "role": d["role"],
            "permissions": _clean_perms(d.get("permissions")), "active": d.get("active", True), "created_at": d.get("created_at")}


async def _validate_staff(body: StaffUserIn, exclude=None, need_password=True) -> dict:
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Valid email is required")
    if body.mobile and not re.fullmatch(r"\+?\d{10,13}", body.mobile.strip()):
        raise HTTPException(status_code=400, detail="Mobile number must be 10-13 digits")
    if body.role not in CREATABLE_ROLES:
        raise HTTPException(status_code=400, detail="Role must be Admin, HR or Manager")
    q = {"email": email}
    if exclude:
        q["_id"] = {"$ne": exclude}
    if await db.users.find_one(q, {"_id": 1}):
        raise HTTPException(status_code=409, detail="This email is already used")
    data = {"name": body.name.strip(), "email": email, "mobile": body.mobile.strip(), "role": body.role, "permissions": _clean_perms(body.permissions), "active": body.active}
    if body.password or need_password:
        if not body.password or len(body.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        if body.password != body.confirm_password:
            raise HTTPException(status_code=400, detail="Password and Confirm password do not match")
        data["password_hash"] = hash_password(body.password)
    return data


@api.get("/admin/users")
async def list_staff(sa: dict = Depends(superadmin_user)):
    docs = await db.users.find({"role": {"$in": list(STAFF_ROLES)}}).sort("created_at", 1).to_list(500)
    return {"modules": MODULES, "actions": ACTIONS, "users": [_staff_out(d) for d in docs]}


@api.post("/admin/users")
async def create_staff(body: StaffUserIn, sa: dict = Depends(superadmin_user)):
    data = await _validate_staff(body)
    data.update({"created_at": now_utc(), "created_by": sa.get("email")})
    res = await db.users.insert_one(data)
    return _staff_out(await db.users.find_one({"_id": res.inserted_id}))


@api.put("/admin/users/{uid}")
async def update_staff(uid: str, body: StaffUserIn, sa: dict = Depends(superadmin_user)):
    doc = await db.users.find_one({"_id": oid(uid), "role": {"$in": list(CREATABLE_ROLES)}})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    data = await _validate_staff(body, doc["_id"], need_password=False)
    await db.users.update_one({"_id": doc["_id"]}, {"$set": data})
    if not data["active"] or "password_hash" in data:
        await db.login_sessions.update_many({"user_id": uid, "logout_at": None}, {"$set": {"logout_at": now_utc()}})
    return _staff_out(await db.users.find_one({"_id": doc["_id"]}))


@api.delete("/admin/users/{uid}")
async def delete_staff(uid: str, sa: dict = Depends(superadmin_user)):
    res = await db.users.delete_one({"_id": oid(uid), "role": {"$in": list(CREATABLE_ROLES)}})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="User not found")
    await db.login_sessions.update_many({"user_id": uid, "logout_at": None}, {"$set": {"logout_at": now_utc()}})
    return {"ok": True}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ['CORS_ORIGINS'].split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("employee_id", unique=True, sparse=True)
    await db.reminder_logs.create_index("run_id", unique=True)
    await db.push_subscriptions.create_index("endpoint", unique=True)
    await db.users.create_index("short_code", unique=True, partialFilterExpression={"short_code": {"$type": "string"}})
    await db.login_attempts.create_index("identifier")
    await db.attendance.create_index([("user_id", 1), ("date", 1)], unique=True)
    await db.requests.create_index([("user_id", 1), ("created_at", -1)])
    await db.payslips.create_index([("user_id", 1), ("month", -1)])
    await db.users.create_index("vendor_id", sparse=True)
    await db.employee_media.create_index("user_id", unique=True)
    await db.sync_logs.create_index([("started_at", -1)])
    email, pwd = os.environ["ADMIN_EMAIL"].lower(), os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({"email": email, "password_hash": hash_password(pwd), "name": "Super Admin", "role": "superadmin", "active": True, "created_at": now_utc()})
    elif existing.get("role") != "superadmin":
        await db.users.update_one({"_id": existing["_id"]}, {"$set": {"role": "superadmin"}})
    elif (os.environ.get("ADMIN_FORCE_RESET") == "true" or not existing.get("password_set_in_app")) and not verify_password(pwd, existing["password_hash"]):
        await db.users.update_one({"_id": existing["_id"]}, {"$set": {"password_hash": hash_password(pwd)}})


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
