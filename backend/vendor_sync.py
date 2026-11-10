import os
from shortcode import make_short_code
import re
import logging
from datetime import datetime, timezone, timedelta, date as date_cls

import httpx
from bson import ObjectId

logger = logging.getLogger("vendor_sync")

# Vendor attendance grid codes: P present, A absent, L leave, H half-day, W week-off, HL holiday
LEAVE_CODES = {"Half Day": "H"}


def _url():
    return os.environ["VENDOR_API_URL"].rstrip("/")


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def initial_password(v: dict, code: str) -> str:
    dob = v.get("dob") or ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", dob):
        return f"{dob[8:10]}{dob[5:7]}{dob[0:4]}"
    return v.get("contactMobile") or code


def map_employee(v: dict, code: str) -> dict:
    addr = ", ".join(x for x in [v.get("presentLine"), v.get("presentCity"), v.get("presentState"), v.get("presentPincode")] if x)
    return {
        "employee_id": code,
        "vendor_id": v["id"],
        "name": (v.get("fullName") or "").strip() or code,
        "phone": v.get("contactMobile") or "",
        "department": v.get("department") or "",
        "designation": v.get("designation") or "",
        "joining_date": v.get("doj") or "",
        "dob": v.get("dob") or "",
        "gender": {"M": "Male", "F": "Female"}.get(v.get("gender"), v.get("gender") or ""),
        "address": addr or v.get("presentAddress") or "",
        "bank_name": v.get("bankName") or "",
        "bank_account": v.get("bankAccount") or "",
        "ifsc": v.get("ifsc") or "",
        "pan": v.get("pan") or "",
        "uan": v.get("uan") or v.get("pfNo") or "",
        "basic": _num(v.get("basic")),
        "hra": _num(v.get("hra")),
        "allowances": _num(v.get("da")) + _num(v.get("special")) + _num(v.get("bonus")),
        "da": _num(v.get("da")),
        "special": _num(v.get("special")),
        "bonus": _num(v.get("bonus")),
        "ctc_annual": _num(v.get("ctcAnnual")),
        "father_name": v.get("fatherName") or "",
        "location": v.get("location") or "",
        "project_site": v.get("projectSite") or "",
        "reporting_manager": v.get("reportingManager") or "",
        "active": (v.get("status") or "").lower() == "active",
        "source": "vendor",
    }


async def _pick_email(db, v: dict, code: str, exclude_id=None) -> str:
    email = (v.get("contactEmail") or "").strip().lower()
    if email and "@" in email:
        q = {"email": email}
        if exclude_id:
            q["_id"] = {"$ne": exclude_id}
        if not await db.users.find_one(q):
            return email
    return re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-") + "@employee.local"


async def pull_employees(db, client, headers, hash_password) -> dict:
    r = await client.get(f"{_url()}/employees", headers=headers)
    r.raise_for_status()
    created = updated = skipped = 0
    errors = []
    now = datetime.now(timezone.utc)
    for v in r.json():
        try:
            res = await _upsert_one(db, v, hash_password, now)
        except Exception as ex:
            errors.append(f"{v.get('empCode')}: {str(ex)[:120]}")
            continue
        created += res == "created"
        updated += res == "updated"
        skipped += res == "skipped"
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


async def _save_media(db, user_id: str, v: dict, now):
    upd = {k: v.get(src) for k, src in (("photo", "photoUrl"), ("signature", "signatureUrl")) if (v.get(src) or "").startswith("data:image/")}
    if upd:
        await db.employee_media.update_one({"user_id": user_id}, {"$set": upd | {"source": "vendor", "updated_at": now}}, upsert=True)


async def _upsert_one(db, v, hash_password, now) -> str:
    code = (v.get("empCode") or "").strip().upper()
    if not code or not v.get("id"):
        return "skipped"
    data = map_employee(v, code)
    existing = await db.users.find_one({"$or": [{"vendor_id": v["id"]}, {"employee_id": code}], "role": "employee"})
    if existing:
        if not existing.get("email") or existing["email"].endswith("@employee.local"):
            data["email"] = await _pick_email(db, v, code, existing["_id"])
        await db.users.update_one({"_id": existing["_id"]}, {"$set": data | {"synced_at": now}})
        await _save_media(db, str(existing["_id"]), v, now)
        return "updated"
    data.update({
        "email": await _pick_email(db, v, code), "role": "employee", "created_at": now, "synced_at": now,
        "password_hash": hash_password(initial_password(v, code)), "must_change_password": True,
        "short_code": await make_short_code(db, code),
    })
    res = await db.users.insert_one(data)
    await _save_media(db, str(res.inserted_id), v, now)
    if data["joining_date"]:
        await db.service_records.insert_one({
            "user_id": str(res.inserted_id), "date": data["joining_date"], "type": "joining",
            "title": f"Joined as {data['designation'] or 'Employee'}", "notes": data["department"], "created_at": now,
        })
    return "created"


def _months(today: date_cls):
    first = today.replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    return [(prev.year, prev.month), (today.year, today.month)]


async def pull_attendance(db, client, headers) -> tuple:
    r = await client.get(f"{_url()}/attendance", headers=headers)
    r.raise_for_status()
    docs = [d for d in r.json() if d.get("id")]
    emps = {e["vendor_id"]: str(e["_id"]) for e in await db.users.find({"vendor_id": {"$exists": True}}, {"vendor_id": 1}).to_list(5000)}
    now = datetime.now(timezone.utc)
    pulled = 0
    for d in docs:
        uid = emps.get(d.get("empId"))
        if not uid or not d.get("year") or not d.get("month"):
            continue
        await db.vendor_attendance.update_one({"user_id": uid, "year": int(d["year"]), "month": int(d["month"])},
                                              {"$set": {"days": d.get("days") or {}, "late": d.get("late") or {}, "pulled_at": now}}, upsert=True)
        pulled += 1
    return {"attendance_months_pulled": pulled}, {d["id"]: d for d in docs}


async def push_attendance(db, client, headers, today: date_cls, remote: dict = None, user_ids: list = None) -> dict:
    if remote is None:
        _, remote = await pull_attendance(db, client, headers)
    q = {"role": "employee", "vendor_id": {"$exists": True}}
    if user_ids:
        q["_id"] = {"$in": [ObjectId(u) for u in user_ids]}
    emps = await db.users.find(q, {"vendor_id": 1}).to_list(5000)
    pushed = 0
    for y, m in _months(today):
        prefix = f"{y}-{m:02d}"
        month_start = date_cls(y, m, 1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        for e in emps:
            uid = str(e["_id"])
            locked = {o["date"][8:10] for o in await db.attendance_overrides.find({"user_id": uid, "date": {"$regex": f"^{prefix}"}}, {"date": 1}).to_list(40)}
            att = [a for a in await db.attendance.find({"user_id": uid, "date": {"$regex": f"^{prefix}"}}, {"date": 1, "late": 1, "late_minutes": 1}).to_list(40) if a["date"][8:10] not in locked]
            leaves = await db.requests.find({"user_id": uid, "type": "leave", "status": "approved",
                                             "start_date": {"$lte": month_end.isoformat()}, "end_date": {"$gte": month_start.isoformat()}}).to_list(50)
            if not att and not leaves:
                continue
            doc_id = f"att_{e['vendor_id']}_{y}{m:02d}"
            doc = remote.get(doc_id) or {"id": doc_id, "empId": e["vendor_id"], "year": y, "month": m, "days": {}}
            days = dict(doc.get("days") or {})
            late = dict(doc.get("late") or {})
            changed = False
            for a in att:
                dd = a["date"][8:10]
                if days.get(dd) in (None, "", "A"):
                    days[dd] = "P"
                    changed = True
                if a.get("late") and late.get(dd) != a.get("late_minutes"):
                    late[dd] = a.get("late_minutes")
                    changed = True
            for lv in leaves:
                code = LEAVE_CODES.get(lv.get("leave_type"), "L")
                d = max(date_cls.fromisoformat(lv["start_date"]), month_start)
                while d <= min(date_cls.fromisoformat(lv["end_date"]), month_end):
                    dd = f"{d.day:02d}"
                    if not days.get(dd) and dd not in locked:
                        days[dd] = code
                        changed = True
                    d += timedelta(days=1)
            if changed:
                body = {"id": doc_id, "empId": e["vendor_id"], "year": y, "month": m, "days": days, "late": late,
                        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
                pr = await client.post(f"{_url()}/attendance", headers=headers, json=body)
                pr.raise_for_status()
                await db.vendor_attendance.update_one({"user_id": uid, "year": y, "month": m}, {"$set": {"days": days, "late": late, "pulled_at": datetime.now(timezone.utc)}}, upsert=True)
                pushed += 1
    return {"attendance_months_pushed": pushed}


async def _vendor_headers(client) -> dict:
    lr = await client.post(f"{_url()}/auth/login", json={"identifier": os.environ["VENDOR_EMAIL"], "password": os.environ["VENDOR_PASSWORD"]})
    lr.raise_for_status()
    return {"Authorization": f"Bearer {lr.json()['token']}"}


async def push_day(db, user_id: str, vendor_id: str, day: str, code: str):
    y, m, dd = int(day[:4]), int(day[5:7]), day[8:10]
    async with httpx.AsyncClient(timeout=60) as client:
        headers = await _vendor_headers(client)
        _, remote = await pull_attendance(db, client, headers)
        doc_id = f"att_{vendor_id}_{y}{m:02d}"
        doc = remote.get(doc_id) or {}
        days, late = dict(doc.get("days") or {}), dict(doc.get("late") or {})
        days[dd] = code
        if code != "P":
            late.pop(dd, None)
        body = {"id": doc_id, "empId": vendor_id, "year": y, "month": m, "days": days, "late": late,
                "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        pr = await client.post(f"{_url()}/attendance", headers=headers, json=body)
        pr.raise_for_status()
        await db.vendor_attendance.update_one({"user_id": user_id, "year": y, "month": m}, {"$set": {"days": days, "late": late, "pulled_at": datetime.now(timezone.utc)}}, upsert=True)


async def push_now(db, user_id: str, today: date_cls):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            lr = await client.post(f"{_url()}/auth/login", json={"identifier": os.environ["VENDOR_EMAIL"], "password": os.environ["VENDOR_PASSWORD"]})
            lr.raise_for_status()
            await push_attendance(db, client, {"Authorization": f"Bearer {lr.json()['token']}"}, today, user_ids=[user_id])
    except Exception:
        logger.exception("Instant attendance push failed for %s (hourly sync will retry)", user_id)


async def run_sync(db, hash_password, today: date_cls, trigger: str, run_id: str = None) -> dict:
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    if await db.sync_logs.find_one({"status": "running", "started_at": {"$gt": stale}}):
        return {"status": "skipped", "detail": "A sync is already running"}
    log = {"trigger": trigger, "run_id": run_id, "status": "running", "started_at": datetime.now(timezone.utc)}
    res = await db.sync_logs.insert_one(log)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            lr = await client.post(f"{_url()}/auth/login", json={"identifier": os.environ["VENDOR_EMAIL"], "password": os.environ["VENDOR_PASSWORD"]})
            lr.raise_for_status()
            headers = {"Authorization": f"Bearer {lr.json()['token']}"}
            result = await pull_employees(db, client, headers, hash_password)
            pulled, remote = await pull_attendance(db, client, headers)
            result |= pulled
            result |= await push_attendance(db, client, headers, today, remote)
        update = {"status": "success", "result": result}
    except httpx.ConnectError:
        logger.exception("Vendor sync failed")
        update = {"status": "failed", "error": f"Cannot connect to ERP at {_url()}. Check the ERP link (VENDOR_API_URL)."}
    except Exception as ex:
        logger.exception("Vendor sync failed")
        update = {"status": "failed", "error": str(ex)[:300]}
    update["finished_at"] = datetime.now(timezone.utc)
    await db.sync_logs.update_one({"_id": res.inserted_id}, {"$set": update})
    return update
