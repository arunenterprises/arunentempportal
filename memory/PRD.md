# WorkPulse – Employee Portal + HR Admin

## Original problem statement
"jese apne vendor portal banaya hai thik usi tarah employee portal bhi bana dijiye taki hamara employee bhi apna detals aur service's record dekh sake aur apni attendence phi punch karsake aur jo bhi uski request hai usko wo full fill kar sake request main jese leave ,advance,payslip etc."

User choices: separate new portal; admin creates employee accounts (login with email or Employee ID + password); punch in/out with time + GPS + selfie; Admin/HR approves/rejects requests; payslip generated from salary details (PDF) OR admin uploads PDF.

## Architecture
- FastAPI (`backend/server.py`, `payslip_pdf.py` via reportlab) + MongoDB (users, service_records, attendance, requests, payslips, login_attempts)
- JWT Bearer auth (12h), bcrypt, brute-force lockout (5 fails / 15 min per identifier), admin seeded from .env
- React + shadcn, routes `/login`, `/employee/*`, `/admin/*`; selfies stored as small base64 JPEG; uploaded PDFs stored base64 (≤4MB)

## Personas
- Employee: views profile/service record, punches attendance, raises requests, downloads payslips
- Admin/HR: manages employees, service records, attendance verification, approvals, payroll

## Implemented (2026-10-17)
- Login (email/Employee ID), change password
- Employee: dashboard with live clock + punch card, stats, latest payslip; selfie+GPS punch dialog (camera or upload fallback); attendance history by month; profile + service timeline; requests (leave/advance/payslip/other) with cancel & status filters; payslip list + PDF download
- Admin: dashboard stats, employees CRUD (active/inactive), service records add/delete, attendance monitor with selfie viewer + map links, request approve/reject with comment, payslip generate (earnings/deductions) & PDF upload; publishing auto-approves matching payslip requests
- Tested: iteration_1 (backend 26/27 → brute-force fixed, frontend 100%)

## Implemented (2026-10-17, iteration 2)
- Branding: ARUN ENTERPRISES logo/name in sidebar, login page redesigned like vendor portal (address, toll free, email, web), payslip PDF header with logo + address
- Vendor Portal link (https://arunenterprises.online/api): employees pulled from vendor HR keyed on empCode (= employee_id, primary key; vendor_id stored); attendance punches + approved leaves pushed back into vendor monthly attendance docs (att_{empId}_{YYYYMM}; P only fills empty/A days, leaves CL/SL/EL/LWP/HL fill empty days). Admin "Sync now" button + hourly cron (.emergent/crons.yml -> /api/cron/vendor-sync)
- Synced employees: initial password = DOB DDMMYYYY (else mobile); change-password banner
- Tested: iteration_2 backend 37/37, frontend 100%

## Implemented (2026-10-17, iteration 3)
- Punch screen: Front Camera + Location permission mandatory (Permission Required + Retry), non-editable live punch time + GPS, 30s countdown then auto capture & submit (manual "Submit now" also)
- Punch windows enforced on server (IST): In 09:10-09:30, Out 18:10-18:30 (backend/.env PUNCH_IN_WINDOW / PUNCH_OUT_WINDOW); dashboard shows windows and disables button outside window

## Implemented (2026-10-17, iteration 4)
- Late Mark: punch-in allowed from in-start until out-window end; after in-window end -> late=true + late_minutes; badges on employee dashboard/attendance tables, "Late today" admin stat; pushed to vendor as "P" + extra `late` {day: minutes} field (vendor UI has no Late code)
- Missed Punch request (in/out/both, date, actual times) with validations; HR approve creates/updates attendance as manual punch (tagged "Missed punch · HR approved"), late computed
- Vendor push leave codes corrected to vendor grid codes: L (leave), H (half day)

## Implemented (2026-10-17, iteration 5)
- Admin: reset employee password (dialog; employee must change after login), Live/Unlive portal access switch (portal_enabled, independent of vendor HR status; blocks login + existing sessions)
- Admin self password change (key icon in sidebar/mobile header); in-app password persists across restarts (password_set_in_app); recovery via ADMIN_FORCE_RESET="true" in backend/.env + restart
- Employee photo & signature (employee_media collection) synced from vendor photoUrl/signatureUrl; preview + zoom on admin detail and employee profile; admin upload (PNG/JPEG/WEBP, base64 validated)
- Tested: iteration_4 backend 11/11, frontend 100%

## Implemented (2026-10-17, iteration 6)
- Admin employee detail layout: profile panel (photo/signature column + Job / Personal & contact / Bank & statutory groups), Salary breakup panel (Basic, HRA, DA, Special, Bonus, gross month/year, CTC if present), full-width Service record with collapsible add form
- Vendor sync now stores da, special, bonus, ctc_annual separately

## Implemented (2026-10-17, iteration 7)
- Employee detail redesign: dark hero card (photo, name, code, badges, actions, quick facts), profile + salary breakup in left column, sticky service record on right
- Credential slips: POST /api/admin/credential-slips sets a new random 8-char password per selected employee (must_change_password) and returns slips once; bulk dialog on Employees page (pre-selects employees who never changed password) + single "Print slip" on detail page; print CSS prints only slips (logo, company, portal URL, code, password, instructions)

## Implemented (2026-10-17, iteration 8)
- Leave balance: yearly quota per employee (CL/SL/EL) with optional apply-to-all (confirm), +/- adjustments with reason & history; available = quota + adjustments - approved; Half Day = 0.5 CL; enforced on request & approval only when configured; employee sees cards on dashboard + availability in leave form
- Service Book admin tab (/admin/service-book): employee picker, header summary, service entries, performance appraisals (6 criteria 1-5 stars, score, grade, recommendation), leave balance; employee sees appraisals on Profile
- Tested: iteration_5 backend 15/15, frontend 100%

## Implemented (2026-10-17, iteration 9)
- Employee record redesign (shared EmployeeRecord used by /admin/employees/:id and Service Book tab): hero (photo, name, badges) + separate action toolbar (Portal Live/Unlive, Edit details, Reset password, Print slip, Delete) + facts row; tabs: Profile, Salary & Leave, Service Book, Appraisals, Attendance (month, present/late/hours), Requests, Payslips

## Implemented (2026-10-17, iteration 10)
- Attendance monthly sheet (Admin > Attendance > Monthly sheet): employees x days grid merging HR Management (vendor) attendance (pulled into vendor_attendance during sync) + portal punches + approved leaves; codes P/A/L/H/W/HL, late dot, portal-punch marker, totals; "Pull from HR Management" button
- Instant push: portal punch-in/out and approved leave/missed-punch of vendor-linked employees push immediately to vendor (background), hourly sync as fallback

## Implemented (2026-10-17, iteration 11)
- Monthly sheet "Export Excel (CSV)" button: UTF-8 BOM CSV (attendance-sheet-YYYY-MM.csv) with Employee Code, Name, per-day codes (Late suffix), P/A/L/H/HL/W totals, Late Days, Paid Days = P+L+HL+W+H/2

## Implemented (2026-10-17, iteration 12)
- Sheet cell edit: click any day in Monthly sheet -> popover with P/A/L/H/W/HL + optional reason. PUT /api/admin/attendance-sheet/cell saves to attendance_overrides (wins over HR/portal/leave in sheet, blue dot) and pushes that day instantly to vendor attendance (push_day). Hourly push_attendance skips overridden days so admin edits aren't reverted.

## Implemented (2026-10-18, iteration 13)
- Admin > Attendance header toggle "Show attendance to employees" (db.settings _id=portal.employee_sheet_visible; GET/PUT /api/admin/settings/employee-sheet). When ON, employee My attendance page shows calendar sheets for previous + current month (GET /api/attendance/my-sheet, same merged data as admin sheet via sheet_row helper). Default OFF.

## Implemented (2026-10-18, iteration 14)
- Testing agent iteration_6: employee-sheet toggle + previous/current month calendar 100% backend/frontend in preview. Production confirmed serving latest build (live issue = browser cache + prod switch defaults OFF).
- Admin Dashboard layout: compact horizontal stat cards (StatCard `compact` prop), 2/3/5 responsive grid, Pending approvals wrapped in Panel to match Today's attendance.

## Implemented (2026-10-18, iteration 15)
- Login Activity (Admin > Logins, /admin/login-activity): db.login_sessions (sid in JWT, last_seen updated max 1/min, logout ends session -> token 401) + db.login_logs (login/logout/failed with IP, user agent, detail). "Logged in now" cards (Online = active <=15 min, Idle = not logged out), filterable logs (date/employee/event). Frontend logout calls /api/auth/logout; 4-min heartbeat while tab visible.
- IP = cf-connecting-ip, else X-Forwarded-For 3rd from right (client, Cloudflare, ingress) so a spoofed header is ignored. Sessions list hides deleted/inactive/portal-disabled employees; deleting an employee cascades login_sessions/login_logs/attendance_overrides.
- Testing agent iteration_7: frontend 100%, backend 11/12. Its single issue (stale sessions) is fixed, plus IP spoof hardening.

## Implemented (2026-10-18, iteration 16)
- Admin > Requests now has tabs "Requests" | "Leave Balance". Leave Balance tab (LeaveBalanceManager.jsx): all employees' CL/SL/EL available/allotted, per-employee Live/Unlive switch (users.leave_balance_live), All Live/All Unlive (with confirm), Edit dialog (quota + adjustments), Download sheet/template CSV, Upload CSV (Employee Code, CL, SL, EL, Live Yes/No) -> POST /api/admin/leave-balances/upload with per-row error report.
- Unlive: GET /api/leave-balance returns {live:false}; employee dashboard hides the balance panel and the request form shows no balance; quota still enforced, with a generic "Contact HR" error.
- Leave request cards in admin show the employee's balance strip (red if pending is more than available).
- Testing agent iteration 8 (summary only, no JSON): backend 14/14, frontend 100%. Fixed after the test: empty user_ids now returns 400, confirm on bulk live, available shown never below 0, quota fields disabled until loaded.

## Implemented (2026-10-18, iteration 17)
- Short code (5-6 alphanumeric, e.g. AE0005 from serial) per employee: shortcode.py, auto on create/vendor sync, bulk "Create Short ID" (green) on Employees page, per-employee edit/auto in detail hero, login with short code/full code/email, shown next to employee code everywhere (lists, sheet, requests, payslips, logins, slips, profile, dropdowns, CSVs). Unique index; check_unique rejects employee_id = other short code. Real employees have NO short code until admin clicks Create Short ID.
- Employees table: name is a link, employee ID bold, new "Short Code / ID" column, Vendor HR tag removed.
- Credential slips: nothing pre-selected + confirm before resetting passwords (after testing agent accidentally reset 9 real passwords; it restored them to the original vendor initial passwords).
- Attendance monthly sheet mobile: per-employee cards with a 7-column day grid (editable), table on md+.
- PWA: manifest.json, icon-192/512 from logo, sw.js, title "ARUN ENTERPRISES | Employee Portal" -> installable on Android (Add to Home screen / Install app).
- Testing agent iteration_9: backend 26/26, frontend 100%.

## Implemented (2026-10-18, iteration 18)
- Credential slip redesign: dark box with big Login ID (short code) + password, QR code (qrcode.react) to <origin>/login, install steps.
- Punch reminders via Web Push (pywebpush, VAPID keys in backend/.env): employee dashboard "Punch reminders" panel (Turn on / Test / Turn off), sw.js push + notificationclick, /api/push/* endpoints, db.push_subscriptions (unique endpoint, re-linked to current user on mount, unlinked on logout).
- Crons (.emergent/crons.yml): punch-in-reminder 9:10 and punch-out-reminder 18:10 Asia/Kolkata Mon-Sat -> /api/cron/punch-reminder-in|out (Bearer WEBHOOK_CRON_SECRET, idempotent run_id unique index). Sends only to employees not yet punched in / punched in but not out, skipping approved leave.
- Admin password changed to Arun2023@12 (preview DB hash + .env ADMIN_PASSWORD). The seed doesn't override when password_set_in_app is true, so on production change it from the app (key icon).
- Testing agent iteration_10: backend 18/18, frontend 100% of testable flows (real push delivery can't be tested headless). Fixed after the test: shared-device subscription and race-free cron dedupe.

## Implemented (2026-10-18, iteration 19)
- SuperAdmin + staff roles: existing ADMIN_EMAIL user migrated to role superadmin; login alias SuperAdmin/Superadmin/SUPRADMIN (any case). Roles admin/hr/manager created only by SuperAdmin at Admin > Users (/admin/users): name, email, mobile, password + confirm, role, per-module View/Edit/Approve (approve = requests only). Backend admin_user maps path->module, method->action (GET view, PATCH requests approve, else edit); /admin/users is superadmin-only. Frontend: role badge in shell, nav/routes filtered by can(), edit/approve buttons and detail tabs gated. Lockout key is now canonical per user. Payslip PDF needs payslips.view for staff.
- Employees sync bar renamed "Arun Enterprises Main ERP Link" (links to https://erp.arunenterprisespryg.in). Old vendor API (arunenterprises.online) no longer answers (SSL handshake failure); the ERP now runs at https://erp.arunenterprisespryg.in/api with the same login and data. VENDOR_API_URL must be updated (requested via the secrets card). The sync error message is now friendly.
- Hostinger VPS migration guide PDF: /docs/hostinger-vps-migration-guide.pdf (generator /app/scripts/make_vps_pdf.py). Now includes Step 5A (ERP link -> API: add /api, VENDOR_API_URL, curl check, Sync now) and Step 5B (SuperAdmin login + users); the systemd part is now Step 5C.
- Testing agent iteration_12: backend 10/10. Fixed after the test: lockout bypass, dashboard 403 overlay, missing permission gating. Gating fixes re-checked only by compile, not by a retest.

## Implemented (2026-11-10, iteration 20)
- Login credentials isolated: password hashes moved from users into a separate auth_credentials collection (backend/credentials.py: set_password, check_password, migrate_from_users at startup). ERP sync only touches profile fields. Deleting an employee or staff user removes its credentials; reset password and slips clear the user:{id} lockout key. A separate Mongo database was NOT used because production allows only DB_NAME.
- Title/manifest: "ARUN ENTERPRISES EMP PORTAL" (short "AE EMP PORTAL"). SuperAdmin name from env ADMIN_NAME="Ashish Srivastava" (set at startup when the name is default). Sidebar shows the full name + designation/department (employees) or the role badge (staff).
- Migration PDF regenerated: 5 pages, larger and darker text (body 11.5pt, code Courier-Bold 10pt black on grey), domain emp.arunenterprisespryg.in, auth_credentials note.
- Testing agent iteration_13: backend 11/12, frontend 100%. Fixed after the test: credentials cleanup on delete, and lockout cleared on reset (only checked by restart + screenshot, not retested).

## Implemented (2026-11-10, iteration 22)
- CORS middleware removed from backend/server.py (frontend and /api share one domain; CORS_ORIGINS env key left in .env but unused).
- VPS guide PDF (scripts/make_vps_pdf.py) regenerated, 6 pages: portal backend on port 8002 (systemd, nginx proxy_pass, cron, checks); ERP stays on 8001 untouched; separate /opt/portal folder, portal user, arun_portal DB, own nginx file; CORS_ORIGINS removed from env table; troubleshooting for port conflicts and 502.

## Implemented (2026-11-10, iteration 21)
- SuperAdmin record in DB now always stores name (from ADMIN_NAME), role "superadmin" and designation "SuperAdmin" at every startup (server.py startup seed). AppShell hides designation line when it equals the role badge. Verified via DB query, login API and screenshot.


## Backlog
- P1: Leave balance/quotas per type; mobile card layout for attendance table; set company name (COMPANY_NAME env, currently placeholder)
- P1: Attendance monthly report export (CSV/Excel)
- P2: Office geofence check on punch; forgot-password via email; selfie served via separate endpoint for large data

## Next tasks
- Replace `[Your Company Name]` in backend/.env COMPANY_NAME
