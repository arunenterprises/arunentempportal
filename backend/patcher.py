import asyncio
import io
import json
import os
import re
import signal
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from bson import ObjectId, Binary
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from credentials import check_password

APP_ROOT = Path(__file__).resolve().parent.parent
ALLOWED = ("backend/", "frontend/build/")
BLOCKED = {"backend/.env", "frontend/.env"}
CHUNK_MAX = 2 * 1024 * 1024
PATCH_MAX = 100 * 1024 * 1024
STORE_PART = 8 * 1024 * 1024
ID_RE = re.compile(r"^[a-f0-9]{32}$")
PIP_INDEX = "https://d33sy5i8bnduwe.cloudfront.net/simple/"


class ApplyIn(BaseModel):
    upload_id: str
    password: str


class PasswordIn(BaseModel):
    password: str


def _now():
    return datetime.now(timezone.utc).isoformat()


def _out(d: dict) -> dict:
    return {**{k: v for k, v in d.items() if k not in ("_id", "install_log")}, "id": str(d["_id"])}


def _check_id(upload_id: str) -> str:
    if not ID_RE.match(upload_id or ""):
        raise HTTPException(400, "Invalid upload id")
    return upload_id


def _read_patch(data: bytes):
    if not data:
        raise HTTPException(404, "Patch file not found. Please upload again.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        meta = json.loads(z.read("patch.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise HTTPException(400, "This is not a valid patch file (patch.json missing or damaged).")
    if not str(meta.get("version") or "").strip():
        raise HTTPException(400, "patch.json must have a version")
    files = [n for n in z.namelist() if not n.endswith("/") and n != "patch.json"]
    if not files:
        raise HTTPException(400, "Patch has no files")
    for n in files:
        p = PurePosixPath(n)
        if p.is_absolute() or ".." in p.parts or not n.startswith(ALLOWED) or n in BLOCKED or "__pycache__" in p.parts:
            raise HTTPException(400, f"File not allowed in patch: {n}")
    return z, meta, files


def _summary(meta: dict, files: list) -> dict:
    return {"version": str(meta["version"]), "name": meta.get("name") or "", "notes": meta.get("notes") or "",
            "files_count": len(files), "backend_files": sum(f.startswith("backend/") for f in files),
            "website_files": sum(f.startswith("frontend/build/") for f in files),
            "installs_packages": "backend/requirements.txt" in files}


def _backup(files: list):
    buf, existed = io.BytesIO(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as b:
        for n in files:
            t = APP_ROOT / n
            if t.is_file():
                b.write(t, n)
                existed.append(n)
    return buf.getvalue(), [n for n in files if n not in existed]


def _write_files(z: zipfile.ZipFile, files: list):
    for n in files:
        t = APP_ROOT / n
        t.parent.mkdir(parents=True, exist_ok=True)
        tmp = t.with_name(t.name + ".patchtmp")
        tmp.write_bytes(z.read(n))
        os.replace(tmp, t)


def _restore(backup: bytes, new_files: list):
    with zipfile.ZipFile(io.BytesIO(backup)) as b:
        for n in b.namelist():
            t = APP_ROOT / n
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(b.read(n))
    for n in new_files:
        (APP_ROOT / n).unlink(missing_ok=True)


def _schedule_restart(needed: bool) -> bool:
    if not needed or os.environ.get("PATCH_AUTO_RESTART") != "true":
        return False
    asyncio.get_running_loop().call_later(2, os.kill, os.getpid(), signal.SIGTERM)
    return True


def patch_router(db, guard) -> APIRouter:
    r = APIRouter(prefix="/admin/patches")

    async def load_upload(upload_id: str) -> bytes:
        parts = await db.patch_chunks.find({"upload_id": _check_id(upload_id)}).sort("index", 1).to_list(1000)
        return b"".join(bytes(p["data"]) for p in parts)

    async def save_backup(key: str, data: bytes):
        for i in range(0, max(len(data), 1), STORE_PART):
            await db.patch_backups.insert_one({"key": key, "index": i, "data": Binary(data[i:i + STORE_PART])})

    async def load_backup(key: str) -> bytes:
        parts = await db.patch_backups.find({"key": key}).sort("index", 1).to_list(1000)
        return b"".join(bytes(p["data"]) for p in parts)

    async def verify(user: dict, password: str):
        if not await check_password(db, user["_id"], password):
            raise HTTPException(403, "SuperAdmin password is wrong")

    async def pip_then_restart(pid: ObjectId):
        proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "pip", "install", "-r", str(APP_ROOT / "backend/requirements.txt"),
                                                    "--extra-index-url", PIP_INDEX, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        ok = proc.returncode == 0
        await db.patches.update_one({"_id": pid}, {"$set": {"install": "done" if ok else "failed", "install_log": out.decode(errors="ignore")[-3000:]}})
        _schedule_restart(True)

    @r.get("")
    async def list_patches(user: dict = Depends(guard)):
        docs = await db.patches.find({}, {"install_log": 0, "files": 0, "new_files": 0}).sort("applied_at", -1).to_list(200)
        items = [_out(d) for d in docs]
        current = next((i["version"] for i in items if i["status"] == "applied"), None)
        return {"current_version": current, "auto_restart": os.environ.get("PATCH_AUTO_RESTART") == "true", "history": items}

    @r.post("/upload-chunk")
    async def upload_chunk(upload_id: str = Form(...), index: int = Form(...), chunk: UploadFile = File(...), user: dict = Depends(guard)):
        _check_id(upload_id)
        data = await chunk.read()
        if len(data) > CHUNK_MAX or index < 0 or index * CHUNK_MAX >= PATCH_MAX:
            raise HTTPException(413, "Patch file is too large")
        if index == 0:
            await db.patch_chunks.delete_many({"upload_id": upload_id})
        await db.patch_chunks.update_one({"upload_id": upload_id, "index": index},
                                         {"$set": {"data": Binary(data), "at": _now()}}, upsert=True)
        return {"ok": True}

    @r.get("/inspect/{upload_id}")
    async def inspect(upload_id: str, user: dict = Depends(guard)):
        _, meta, files = _read_patch(await load_upload(upload_id))
        return {**_summary(meta, files), "files": files[:300]}

    @r.post("/apply")
    async def apply(body: ApplyIn, user: dict = Depends(guard)):
        await verify(user, body.password)
        z, meta, files = _read_patch(await load_upload(body.upload_id))
        backup, new_files = _backup(files)
        try:
            _write_files(z, files)
        except OSError as e:
            _restore(backup, new_files)
            raise HTTPException(500, f"Could not write files, nothing changed: {e}")
        finally:
            z.close()
        await save_backup(body.upload_id, backup)
        info = _summary(meta, files)
        doc = {**info, "files": files, "new_files": new_files, "backup": body.upload_id, "status": "applied",
               "install": "running" if info["installs_packages"] else "none", "applied_at": _now(), "applied_by": user.get("name")}
        res = await db.patches.insert_one(doc)
        await db.patch_chunks.delete_many({"upload_id": body.upload_id})
        if info["installs_packages"]:
            asyncio.create_task(pip_then_restart(res.inserted_id))
            restarting = os.environ.get("PATCH_AUTO_RESTART") == "true"
        else:
            restarting = _schedule_restart(info["backend_files"] > 0)
        return {"ok": True, "version": info["version"], "restarting": restarting}

    @r.post("/{patch_id}/undo")
    async def undo(patch_id: str, body: PasswordIn, user: dict = Depends(guard)):
        await verify(user, body.password)
        latest = await db.patches.find_one({"status": "applied"}, sort=[("applied_at", -1)])
        if not latest or str(latest["_id"]) != patch_id:
            raise HTTPException(400, "Only the latest installed patch can be undone")
        backup = await load_backup(latest["backup"])
        if not backup:
            raise HTTPException(404, "Backup is missing, cannot undo")
        _restore(backup, latest.get("new_files", []))
        await db.patches.update_one({"_id": latest["_id"]}, {"$set": {"status": "undone", "undone_at": _now(), "undone_by": user.get("name")}})
        restarting = _schedule_restart(latest.get("backend_files", 0) > 0)
        return {"ok": True, "restarting": restarting}

    return r
