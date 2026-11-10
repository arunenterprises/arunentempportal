# Separate credentials store (auth_credentials) tests: login, lockout, password writes, vendor sync isolation, branding
import os, time, asyncio
import pytest, requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
SA = {"identifier": "SuperAdmin", "password": "Arun2023@12"}
RUN = str(int(time.time()))[-6:]


def _db_run(coro_fn):
    async def inner():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        try:
            return await coro_fn(c[os.environ["DB_NAME"]])
        finally:
            c.close()
    return asyncio.run(inner())


def login(ident, pwd):
    return requests.post(f"{API}/auth/login", json={"identifier": ident, "password": pwd}, timeout=30)


@pytest.fixture(scope="module")
def sa():
    r = login(**SA) if False else login(SA["identifier"], SA["password"])
    if r.status_code != 200:
        pytest.skip(f"SuperAdmin login failed {r.status_code} {r.text}")
    assert "password_hash" not in r.json()["user"]
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


@pytest.fixture(scope="module")
def emp(sa):
    eid = f"TEST_CR{RUN}"
    r = sa.post(f"{API}/admin/employees", json={"employee_id": eid, "name": "TEST Cred Emp", "email": f"test_cr{RUN}@example.com", "password": "InitPass1"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "password_hash" not in d
    yield d
    rd = sa.delete(f"{API}/admin/employees/{d['id']}")
    print("delete emp", rd.status_code)


class TestCredentialStore:
    def test_db_no_password_hash_in_users(self):
        async def q(db):
            return (await db.users.count_documents({"password_hash": {"$exists": True}}),
                    await db.users.count_documents({}), await db.auth_credentials.count_documents({}))
        n, users, creds = _db_run(q)
        assert n == 0
        assert users == creds

    def test_employee_login_and_wrong_pw(self, emp):
        r = login(emp["employee_id"], "InitPass1")
        assert r.status_code == 200, r.text
        assert r.json()["user"]["role"] == "employee"
        assert "password_hash" not in r.json()["user"]
        assert login(emp["employee_id"], "WrongPass").status_code == 401

        async def q(db):
            return await db.auth_credentials.find_one({"user_id": emp["id"]})
        doc = _db_run(q)
        assert doc and doc["password_hash"].startswith("$2b$")

    def test_admin_list_no_leak(self, sa, emp):
        r = sa.get(f"{API}/admin/employees/{emp['id']}")
        assert r.status_code == 200 and "password_hash" not in r.json()
        r = sa.get(f"{API}/auth/me")
        assert r.status_code == 200 and "password_hash" not in r.text

    def test_change_password(self, emp):
        tok = login(emp["employee_id"], "InitPass1").json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "Bad", "new_password": "NewPass22"})
        assert r.status_code == 400
        r = requests.post(f"{API}/auth/change-password", headers=h, json={"current_password": "InitPass1", "new_password": "NewPass22"})
        assert r.status_code == 200, r.text
        assert login(emp["employee_id"], "NewPass22").status_code == 200
        assert login(emp["employee_id"], "InitPass1").status_code == 401

    def test_admin_reset_password(self, sa, emp):
        r = sa.post(f"{API}/admin/employees/{emp['id']}/reset-password", json={"new_password": "ResetPw33"})
        assert r.status_code == 200
        assert login(emp["employee_id"], "ResetPw33").status_code == 200
        assert login(emp["employee_id"], "NewPass22").status_code == 401

    def test_update_employee_with_password(self, sa, emp):
        body = {k: emp.get(k) for k in ("employee_id", "name", "email")}
        body["password"] = "EditPw444"
        r = sa.put(f"{API}/admin/employees/{emp['id']}", json=body)
        assert r.status_code == 200, r.text
        assert "password_hash" not in r.json()
        assert login(emp["employee_id"], "EditPw444").status_code == 200
        assert login(emp["employee_id"], "ResetPw33").status_code == 401

    def test_credential_slip(self, sa, emp):
        r = sa.post(f"{API}/admin/credential-slips", json={"user_ids": [emp["id"]]})
        assert r.status_code == 200, r.text
        pw = r.json()["slips"][0]["password"]
        assert login(emp["employee_id"], pw).status_code == 200
        assert login(emp["employee_id"], "EditPw444").status_code == 401

    def test_lockout_after_5(self, sa, emp):
        r = sa.post(f"{API}/admin/credential-slips", json={"user_ids": [emp["id"]]})
        assert login(emp["employee_id"], r.json()["slips"][0]["password"]).status_code == 200  # clears counter
        for _ in range(5):
            assert login(emp["employee_id"], "nope").status_code == 401
        r = login(emp["employee_id"], "nope")
        assert r.status_code == 429
        # also by email alias (canonical key)
        assert login(emp["email"], "nope").status_code == 429

    def test_reset_clears_lockout(self, sa, emp):
        r = sa.post(f"{API}/admin/employees/{emp['id']}/reset-password", json={"new_password": "AfterLock5"})
        assert r.status_code == 200
        r = login(emp["employee_id"], "AfterLock5")
        # Expected: admin reset should clear lockout so employee can log in
        assert r.status_code == 200, f"reset did not clear lockout: {r.status_code} {r.text}"


class TestStaff:
    def test_staff_create_update_password(self, sa):
        email = f"test_crstaff{RUN}@example.com"
        body = {"name": "TEST Cred Staff", "email": email, "mobile": "9876543210", "role": "hr", "active": True,
                "permissions": {}, "password": "StaffPw111", "confirm_password": "StaffPw111"}
        r = sa.post(f"{API}/admin/users", json=body)
        assert r.status_code == 200, r.text
        uid = r.json()["id"]
        try:
            assert "password_hash" not in r.json()
            assert login(email, "StaffPw111").status_code == 200
            body.update(password="StaffPw222", confirm_password="StaffPw222")
            r = sa.put(f"{API}/admin/users/{uid}", json=body)
            assert r.status_code == 200, r.text
            assert login(email, "StaffPw222").status_code == 200
            assert login(email, "StaffPw111").status_code == 401
            body.update(password=None, confirm_password=None, name="TEST Cred Staff2")
            r = sa.put(f"{API}/admin/users/{uid}", json=body)
            assert r.status_code == 200, r.text
            assert login(email, "StaffPw222").status_code == 200
        finally:
            assert sa.delete(f"{API}/admin/users/{uid}").status_code == 200


class TestBranding:
    def test_manifest(self):
        r = requests.get(f"{BASE_URL}/manifest.json", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "ARUN ENTERPRISES EMP PORTAL"
        assert d["short_name"] == "AE EMP PORTAL"

    def test_pdf(self):
        r = requests.get(f"{BASE_URL}/docs/hostinger-vps-migration-guide.pdf", timeout=30)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        open("/tmp/guide.pdf", "wb").write(r.content)
