# SuperAdmin login aliases, staff user CRUD (/api/admin/users) and per-module permission enforcement
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
SA_PWD = "Arun2023@12"
SA_EMAIL = "arunenterprises2023@gmail.com"
RUN = uuid.uuid4().hex[:6]
MODULES = ["employees", "attendance", "requests", "leave", "payslips", "service_book", "logins"]


def login(ident, pwd):
    return requests.post(f"{API}/auth/login", json={"identifier": ident, "password": pwd})


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def perms(**kw):
    p = {m: {"view": False, "edit": False, "approve": False} for m in MODULES}
    for m, acts in kw.items():
        for a in acts:
            p[m][a] = True
    return p


@pytest.fixture(scope="module")
def sa():
    r = login("SuperAdmin", SA_PWD)
    if r.status_code != 200:
        pytest.skip(f"SA login failed {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def created(sa):
    ids = {"staff": [], "emp": []}
    yield ids
    for uid in ids["staff"]:
        requests.delete(f"{API}/admin/users/{uid}", headers=H(sa))
    for eid in ids["emp"]:
        requests.delete(f"{API}/admin/employees/{eid}", headers=H(sa))


def mk_staff(sa, created, role, p, **extra):
    body = {"name": f"TEST {role} {RUN}", "email": f"test_{role}_{RUN}{extra.pop('suffix', '')}@example.com", "mobile": "9876543210",
            "password": "Passw0rd!", "confirm_password": "Passw0rd!", "role": role, "permissions": p, "active": True}
    body.update(extra)
    r = requests.post(f"{API}/admin/users", json=body, headers=H(sa))
    if r.status_code == 200:
        created["staff"].append(r.json()["id"])
    return r, body


# --- login aliases ---
@pytest.mark.parametrize("ident", ["SuperAdmin", "Superadmin", "SUPRADMIN", "superadmin", SA_EMAIL])
def test_sa_login_aliases(ident):
    r = login(ident, SA_PWD)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "superadmin"
    assert r.json()["user"]["email"] == SA_EMAIL


# --- CRUD + validation ---
def test_users_list(sa):
    r = requests.get(f"{API}/admin/users", headers=H(sa))
    assert r.status_code == 200
    d = r.json()
    assert set(d["modules"]) == set(MODULES)
    assert any(u["role"] == "superadmin" for u in d["users"])
    assert all("password_hash" not in u and "_id" not in u for u in d["users"])


def test_validation(sa, created):
    base = {"name": "TEST v", "email": f"test_val_{RUN}@example.com", "mobile": "9876543210", "password": "Passw0rd!",
            "confirm_password": "Passw0rd!", "role": "hr", "permissions": {}}
    r = requests.post(f"{API}/admin/users", json={**base, "confirm_password": "Other123!"}, headers=H(sa))
    assert r.status_code == 400 and "match" in r.json()["detail"]
    r = requests.post(f"{API}/admin/users", json={**base, "mobile": "12ab"}, headers=H(sa))
    assert r.status_code == 400
    r = requests.post(f"{API}/admin/users", json={**base, "password": "short", "confirm_password": "short"}, headers=H(sa))
    assert r.status_code == 400
    r = requests.post(f"{API}/admin/users", json={**base, "role": "superadmin"}, headers=H(sa))
    assert r.status_code == 400
    r = requests.post(f"{API}/admin/users", json={**base, "email": SA_EMAIL}, headers=H(sa))
    assert r.status_code == 409


def test_create_edit_flow_and_enforcement(sa, created):
    # HR: employees view only, requests view+approve
    r, body = mk_staff(sa, created, "hr", perms(employees=["view"], requests=["view", "approve"]))
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["role"] == "hr" and u["permissions"]["employees"]["view"] and not u["permissions"]["employees"]["edit"]
    lst = requests.get(f"{API}/admin/users", headers=H(sa)).json()["users"]
    assert any(x["email"] == body["email"] for x in lst)
    # duplicate
    r2 = requests.post(f"{API}/admin/users", json=body, headers=H(sa))
    assert r2.status_code == 409
    # login as hr
    lr = login(body["email"], "Passw0rd!")
    assert lr.status_code == 200, lr.text
    assert lr.json()["user"]["role"] == "hr"
    assert lr.json()["user"]["permissions"]["employees"]["view"] is True
    t = lr.json()["token"]
    assert "password_hash" not in lr.json()["user"]
    # permitted
    assert requests.get(f"{API}/admin/employees", headers=H(t)).status_code == 200
    assert requests.get(f"{API}/admin/stats", headers=H(t)).status_code == 200
    assert requests.get(f"{API}/admin/requests", headers=H(t)).status_code == 200
    # no view
    for p in ["/admin/payslips", "/admin/attendance", "/admin/leave-balances", "/admin/service-records", "/admin/login-activity/logs", "/admin/appraisals", "/admin/attendance-sheet?month=2026-01"]:
        rr = requests.get(f"{API}{p}", headers=H(t))
        assert rr.status_code == 403, f"{p} {rr.status_code}"
    # no edit
    rr = requests.post(f"{API}/admin/employees", json={"employee_id": f"TEST_X{RUN}", "name": "TEST x", "email": f"test_x{RUN}@example.com"}, headers=H(t))
    assert rr.status_code == 403
    assert requests.delete(f"{API}/admin/employees/000000000000000000000000", headers=H(t)).status_code == 403
    assert requests.post(f"{API}/admin/vendor-sync", headers=H(t)).status_code == 403
    # approve permitted -> passes auth (404 for fake id)
    rr = requests.patch(f"{API}/admin/requests/000000000000000000000000", json={"status": "approved"}, headers=H(t))
    assert rr.status_code != 403, rr.text
    # users always forbidden
    assert requests.get(f"{API}/admin/users", headers=H(t)).status_code == 403
    assert requests.post(f"{API}/admin/users", json=body, headers=H(t)).status_code == 403

    # SA edits: remove requests.approve, add employees.edit
    upd = {**body, "password": "", "confirm_password": "", "role": "manager", "permissions": perms(employees=["view", "edit"], requests=["view"])}
    upd["password"] = None; upd["confirm_password"] = None
    er = requests.put(f"{API}/admin/users/{u['id']}", json=upd, headers=H(sa))
    assert er.status_code == 200, er.text
    assert er.json()["role"] == "manager" and er.json()["permissions"]["employees"]["edit"]
    # existing session still valid (no password change) and old pwd works
    me = requests.get(f"{API}/auth/me", headers=H(t))
    assert me.status_code == 200 and me.json()["role"] == "manager"
    rr = requests.patch(f"{API}/admin/requests/000000000000000000000000", json={"status": "approved"}, headers=H(t))
    assert rr.status_code == 403
    # edit permitted: create TEST employee
    emp = {"employee_id": f"TEST_RL{RUN}".upper(), "name": "TEST Role Emp", "email": f"test_rlemp_{RUN}@example.com", "password": "EmpPass123"}
    cr = requests.post(f"{API}/admin/employees", json=emp, headers=H(t))
    assert cr.status_code == 200, cr.text
    created["emp"].append(cr.json()["id"])

    # employee login unaffected and cannot access admin
    el = login(emp["employee_id"], "EmpPass123")
    assert el.status_code == 200, el.text
    assert el.json()["user"]["role"] == "employee"
    et = el.json()["token"]
    for p in ["/admin/employees", "/admin/stats", "/admin/users"]:
        assert requests.get(f"{API}{p}", headers=H(et)).status_code == 403

    # new password via edit ends sessions
    upd2 = {**upd, "password": "NewPassw0rd!", "confirm_password": "NewPassw0rd!"}
    assert requests.put(f"{API}/admin/users/{u['id']}", json=upd2, headers=H(sa)).status_code == 200
    assert requests.get(f"{API}/auth/me", headers=H(t)).status_code == 401
    assert login(body["email"], "Passw0rd!").status_code == 401
    lr2 = login(body["email"], "NewPassw0rd!")
    assert lr2.status_code == 200
    t2 = lr2.json()["token"]
    # deactivate ends sessions and blocks login
    upd3 = {**upd, "active": False}
    assert requests.put(f"{API}/admin/users/{u['id']}", json=upd3, headers=H(sa)).status_code == 200
    assert requests.get(f"{API}/auth/me", headers=H(t2)).status_code == 401
    assert login(body["email"], "NewPassw0rd!").status_code == 403

    # login logs exclude staff roles
    logs = requests.get(f"{API}/admin/login-activity/logs", headers=H(sa)).json()
    assert not any((l.get("identifier") or "").lower() == body["email"] for l in logs)

    # delete
    dr = requests.delete(f"{API}/admin/users/{u['id']}", headers=H(sa))
    assert dr.status_code == 200
    created["staff"].remove(u["id"])
    assert requests.delete(f"{API}/admin/users/{u['id']}", headers=H(sa)).status_code == 404
    assert not any(x["id"] == u["id"] for x in requests.get(f"{API}/admin/users", headers=H(sa)).json()["users"])


def test_cannot_edit_or_delete_superadmin(sa):
    users = requests.get(f"{API}/admin/users", headers=H(sa)).json()["users"]
    sid = next(x["id"] for x in users if x["role"] == "superadmin")
    assert requests.delete(f"{API}/admin/users/{sid}", headers=H(sa)).status_code == 404
    body = {"name": "x x", "email": SA_EMAIL, "role": "hr", "permissions": {}}
    assert requests.put(f"{API}/admin/users/{sid}", json=body, headers=H(sa)).status_code == 404


def test_sa_regression_admin_pages(sa):
    for p in ["/admin/employees", "/admin/stats", "/admin/requests", "/admin/payslips", "/admin/leave-balances", "/admin/login-activity/logs", "/admin/login-activity/sessions", "/admin/vendor-sync/status"]:
        r = requests.get(f"{API}{p}", headers=H(sa))
        assert r.status_code == 200, f"{p} {r.status_code}"
