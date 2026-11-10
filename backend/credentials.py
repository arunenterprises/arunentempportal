import bcrypt
from datetime import datetime, timezone

COLL = "auth_credentials"


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def set_password(db, user_id, plain: str):
    await db[COLL].update_one({"user_id": str(user_id)}, {"$set": {"password_hash": _hash(plain), "updated_at": datetime.now(timezone.utc)}}, upsert=True)


async def check_password(db, user_id, plain: str) -> bool:
    doc = await db[COLL].find_one({"user_id": str(user_id)}, {"password_hash": 1})
    if not doc:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), doc["password_hash"].encode("utf-8"))
    except ValueError:
        return False


async def migrate_from_users(db) -> int:
    # One-time move of password hashes out of user profiles into the separate credentials store.
    await db[COLL].create_index("user_id", unique=True)
    moved = 0
    async for u in db.users.find({"password_hash": {"$exists": True}}, {"password_hash": 1}):
        await db[COLL].update_one({"user_id": str(u["_id"])}, {"$setOnInsert": {"password_hash": u["password_hash"], "updated_at": datetime.now(timezone.utc)}}, upsert=True)
        await db.users.update_one({"_id": u["_id"]}, {"$unset": {"password_hash": ""}})
        moved += 1
    return moved
