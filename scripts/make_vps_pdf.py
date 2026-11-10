from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, Table, TableStyle, Image, KeepTogether

OUT = "/app/frontend/public/docs/hostinger-vps-migration-guide.pdf"
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=22, textColor=colors.HexColor("#0f172a"), spaceAfter=4)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#1e3a8a"), spaceBefore=12, spaceAfter=6)
P = ParagraphStyle("P", parent=ss["BodyText"], fontName="Helvetica", fontSize=11.5, leading=16, textColor=colors.HexColor("#0b0f19"))
SM = ParagraphStyle("SM", parent=P, fontSize=10.5, leading=14, textColor=colors.HexColor("#111827"))
CODE = ParagraphStyle("CODE", fontName="Courier-Bold", fontSize=10, leading=13.5, textColor=colors.HexColor("#000000"), backColor=colors.HexColor("#e5e7eb"),
                      borderColor=colors.HexColor("#9ca3af"), borderWidth=0.6, borderPadding=7, leftIndent=6, rightIndent=6, spaceBefore=5, spaceAfter=9)
NOTE = ParagraphStyle("NOTE", parent=P, backColor=colors.HexColor("#fde68a"), borderPadding=7, spaceBefore=5, spaceAfter=9)

story = []
def h(t): story.append(Paragraph(t, H2))
def p(t): story.append(Paragraph(t, P))
def c(t): story.append(Preformatted(t.strip("\n"), CODE, maxLineLength=74, newLineChars="    "))
def note(t): story.append(Paragraph(t, NOTE))

story.append(Table([[Image("/app/frontend/public/arun-logo.jpg", width=22 * mm, height=15.5 * mm),
                     Paragraph("<b>ARUN ENTERPRISES Employee Portal</b><br/>Hostinger VPS Migration Guide (Step by Step)", ParagraphStyle("t", parent=P, fontSize=13, leading=17))]],
                   colWidths=[28 * mm, None], style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
story.append(Spacer(1, 4))
story.append(Paragraph("Stack: React (frontend) + FastAPI / Python (backend) + MongoDB. Is guide se aap portal ko apne Hostinger VPS par chala sakte hain. "
                       "Jahan <b>[brackets]</b> hain, wahan apni value bhariye.", SM))

h("Step 0 - Pehle se taiyaari (checklist)")
for t in [
    "Hostinger VPS: Ubuntu 22.04 / 24.04, kam se kam 2 vCPU, 4 GB RAM, 50 GB disk (KVM 2 plan ya upar).",
    "Portal ka domain: <b>https://emp.arunenterprisespryg.in</b>. Dhyan dein: <b>erp.arunenterprisespryg.in</b> par aapka main ERP chal raha hai, use mat badaliye.",
    "Code: Emergent chat mein <b>'Save to GitHub'</b> se code apne GitHub repo mein bhejiye (ya code download kijiye).",
    "Purana data (employees, attendance, requests, payslips): live database ka export Emergent support se maangiye (mongodump / JSON). Bina export ke naya server khaali database se shuru hoga.",
    "Saari secret values (passwords, keys) ek surakshit jagah likh lijiye. Inki list Step 5 mein hai.",
]:
    p("&bull; " + t)

h("Step 1 - DNS: subdomain ko VPS se jodiye")
p("Domain provider (Hostinger hPanel -> Domains -> DNS Zone) mein naya record banaiye:")
story.append(Table([["Type", "Name", "Value", "TTL"], ["A", "emp", "[VPS IP address]", "3600"]], colWidths=[20 * mm, 30 * mm, 60 * mm, 20 * mm],
                   style=[("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                          ("FONTSIZE", (0, 0), (-1, -1), 9)]))
story.append(Spacer(1, 4))

h("Step 2 - VPS mein login aur zaroori software")
p("Hostinger hPanel -> VPS -> SSH details se login kijiye (Windows par PowerShell / PuTTY):")
c("""
ssh root@[VPS_IP]
apt update && apt upgrade -y
timedatectl set-timezone Asia/Kolkata
apt install -y git nginx python3 python3-venv python3-pip certbot python3-certbot-nginx ufw curl gnupg
# Node.js 20 + Yarn
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs && npm install -g yarn
""")

h("Step 3 - MongoDB 7 install")
c("""
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \\
  > /etc/apt/sources.list.d/mongodb-org-7.0.list
apt update && apt install -y mongodb-org
systemctl enable --now mongod
mongosh --eval "db.runCommand({ ping: 1 })"
""")
p("MongoDB sirf server ke andar (127.0.0.1) sunta rahe; bahar ke liye port 27017 mat kholiye.")

h("Step 4 - Code server par laiye")
c("""
adduser --disabled-password --gecos "" portal
mkdir -p /opt/portal && chown portal:portal /opt/portal
sudo -u portal git clone https://github.com/[aapka-user]/[repo].git /opt/portal/app
""")

h("Step 5 - Backend setup (FastAPI)")
c("""
cd /opt/portal/app/backend
sudo -u portal python3 -m venv /opt/portal/venv
sudo -u portal /opt/portal/venv/bin/pip install -r requirements.txt \\
  --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
sudo -u portal nano /opt/portal/app/backend/.env
""")
p("<b>backend/.env</b> mein ye keys bhariye (har value double quotes mein):")
env_rows = [["Key", "Kya daalna hai"],
            ["MONGO_URL", "mongodb://127.0.0.1:27017"],
            ["DB_NAME", "[arun_portal]"],
            ["CORS_ORIGINS", "https://emp.arunenterprisespryg.in"],
            ["JWT_SECRET", "lamba random text (openssl rand -hex 32)"],
            ["ADMIN_EMAIL / ADMIN_PASSWORD", "SuperAdmin ka email aur password"],
            ["ADMIN_FORCE_RESET", "false"],
            ["APP_TIMEZONE", "Asia/Kolkata"],
            ["PUNCH_IN_WINDOW / PUNCH_OUT_WINDOW", "09:10-09:30 / 18:10-18:30"],
            ["VENDOR_API_URL", "https://erp.arunenterprisespryg.in/api"],
            ["VENDOR_EMAIL / VENDOR_PASSWORD", "ERP HR login"],
            ["VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT", "punch reminder keys (purani wahi rakhiye)"],
            ["WEBHOOK_CRON_SECRET", "lamba random text"],
            ["COMPANY_NAME / ADDRESS / CONTACT / LOGO", "payslip branding (purani values)"]]
story.append(Table([[Paragraph(f"<font face='Courier-Bold' size=9 color='#000000'>{a}</font>", SM) if i else Paragraph(f"<b>{a}</b>", SM), Paragraph(b if i else f"<b>{b}</b>", SM)] for i, (a, b) in enumerate(env_rows)], colWidths=[80 * mm, 94 * mm],
                   style=[("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
story.append(Spacer(1, 4))
note("Integration proxy waali key (INTEGRATION_PROXY_URL) Emergent ki internal hai; VPS par uski zaroorat nahi.")

h("Step 5A - ERP link se API kaise banayein (VENDOR_API_URL)")
p("Aapke paas sirf ERP ka website link hota hai. API ka pata usi link ke aakhir mein <b>/api</b> jodne se banta hai:")
story.append(Table([["Aapka ERP link", "https://erp.arunenterprisespryg.in/"],
                    ["VENDOR_API_URL (API)", "https://erp.arunenterprisespryg.in/api"]], colWidths=[50 * mm, 124 * mm],
                   style=[("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
                          ("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (1, 0), (1, -1), "Courier")]))
story.append(Spacer(1, 4))
for t in [
    "backend/.env mein likhiye: <font face='Courier'>VENDOR_API_URL=\"https://erp.arunenterprisespryg.in/api\"</font> (aakhir ka / ho ya na ho, dono chalega).",
    "VENDOR_EMAIL / VENDOR_PASSWORD mein ERP ke HR login wale hi email aur password daaliye. ERP ka domain badalne par password wahi rehta hai.",
    "Kabhi ERP ka domain badle to sirf ye ek line badaliye, phir <b>systemctl restart portal-api</b> chalaiye.",
]:
    p("&bull; " + t)
p("Link sahi hai ya nahi, VPS par check kijiye. Login ka jawab 200 aaye aur usme \"token\" ho to link sahi hai:")
c("""
curl -s -o /dev/null -w "%{http_code}\\n" https://erp.arunenterprisespryg.in/api/auth/login \\
  -H "Content-Type: application/json" -d '{"identifier":"[ERP email]","password":"[ERP password]"}'
""")
p("Portal chalu hone ke baad: SuperAdmin se login -> Employees -> <b>Sync now</b>. Upar \"success\" aur employees ki ginti dikhni chahiye. "
  "\"Cannot connect to ERP\" aaye to VENDOR_API_URL dobara check kijiye.")

h("Step 5B - SuperAdmin login aur users")
for t in [
    "Login ID mein <b>SuperAdmin</b> (ya Superadmin / SUPRADMIN) ya ADMIN_EMAIL, aur password ADMIN_PASSWORD wala.",
    "Naye Admin / HR / Manager users sirf SuperAdmin banata hai: menu <b>Users</b> -> Create user (Name, Email, Mobile, Password, Confirm password, Role, har module par View / Edit / Approve).",
]:
    p("&bull; " + t)
h("Step 5C - Backend ko hamesha chalu rakhiye (systemd service)")
c("""
cat > /etc/systemd/system/portal-api.service <<'EOF'
[Unit]
Description=Arun Portal API
After=network.target mongod.service
[Service]
User=portal
WorkingDirectory=/opt/portal/app/backend
ExecStart=/opt/portal/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now portal-api
curl -s http://127.0.0.1:8001/api/push/public-key
""")

h("Step 6 - Purana data import (agar export mila ho)")
c("""
# export folder (dump/) VPS par copy kijiye:  scp -r dump root@[VPS_IP]:/root/
mongorestore --uri "mongodb://127.0.0.1:27017" --nsFrom "[purana_db].*" --nsTo "[arun_portal].*" /root/dump
systemctl restart portal-api
""")

p("Login data (passwords) alag collection <b>auth_credentials</b> mein rehta hai; ERP sync ise kabhi nahi chhoota. Restore karte waqt ye collection bhi zaroor aana chahiye, warna sabko password reset karna padega.")

h("Step 7 - Frontend build (React)")
c("""
cd /opt/portal/app/frontend
echo 'REACT_APP_BACKEND_URL="https://emp.arunenterprisespryg.in"' | sudo -u portal tee .env
sudo -u portal yarn install --frozen-lockfile
sudo -u portal yarn build          # build/ folder banega
""")

h("Step 8 - Nginx (website + /api)")
c("""
cat > /etc/nginx/sites-available/portal <<'EOF'
server {
    listen 80;
    server_name emp.arunenterprisespryg.in;
    root /opt/portal/app/frontend/build;
    index index.html;
    client_max_body_size 20M;
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 120s;
    }
    location = /sw.js { add_header Cache-Control "no-cache"; }
    location / { try_files $uri /index.html; }
}
EOF
ln -s /etc/nginx/sites-available/portal /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
""")

h("Step 9 - HTTPS (free SSL)")
c("certbot --nginx -d emp.arunenterprisespryg.in --redirect -m arunenterprises2023@gmail.com --agree-tos")
p("Camera (selfie), GPS aur notifications sirf HTTPS par chalte hain, isliye ye step zaroori hai.")

h("Step 10 - Automatic kaam (cron): sync aur punch reminders")
p("Emergent par ye kaam platform karta tha. VPS par crontab mein daaliye (<b>crontab -e</b>):")
c("""
CRON_TZ=Asia/Kolkata
S=[WEBHOOK_CRON_SECRET]
0 * * * *    curl -s -X POST -H "Authorization: Bearer $S" http://127.0.0.1:8001/api/cron/vendor-sync
10 9 * * 1-6  curl -s -X POST -H "Authorization: Bearer $S" http://127.0.0.1:8001/api/cron/punch-reminder-in
10 18 * * 1-6 curl -s -X POST -H "Authorization: Bearer $S" http://127.0.0.1:8001/api/cron/punch-reminder-out
30 2 * * *    mongodump --uri mongodb://127.0.0.1:27017 --db [arun_portal] --out /root/backup/$(date +\\%F)
""")

h("Step 11 - Firewall")
c("""
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable
""")

h("Step 12 - Check karke chalu kijiye")
for t in [
    "https://emp.arunenterprisespryg.in kholiye -> SuperAdmin se login kijiye.",
    "Employees page par <b>Sync now</b> dabaiye -> ERP ke employees aane chahiye.",
    "Ek employee se mobile par Punch In (camera + location allow) karke dekhiye; ERP attendance mein update dikhna chahiye.",
    "Payslip PDF download, Leave request aur approve check kijiye.",
    "Employees ko naya link bhejiye. Mobile app (PWA) naye link se dobara install karna hoga, aur 'Turn on reminders' phir se dabana hoga.",
    "Credential slip ka QR code apne aap naye domain ka banega.",
]:
    p("&bull; " + t)

h("Step 13 - Aage update kaise karein")
c("""
cd /opt/portal/app && sudo -u portal git pull
sudo -u portal /opt/portal/venv/bin/pip install -r backend/requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
systemctl restart portal-api
cd frontend && sudo -u portal yarn install && sudo -u portal yarn build
""")

h("Dikkat aaye to")
for t in [
    "Backend log: <b>journalctl -u portal-api -n 100</b>",
    "Nginx log: <b>tail -n 50 /var/log/nginx/error.log</b>",
    "Login nahi ho raha: backend/.env mein ADMIN_EMAIL / ADMIN_PASSWORD aur JWT_SECRET check kijiye, phir <b>systemctl restart portal-api</b>.",
    "Page khaali / 404 on refresh: Nginx mein 'try_files $uri /index.html' line check kijiye.",
    "Sync fail: VENDOR_API_URL aur ERP login sahi hai ya nahi dekhiye.",
]:
    p("&bull; " + t)

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(18 * mm, 10 * mm, "ARUN ENTERPRISES - Hostinger VPS Migration Guide")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()

SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                  title="Hostinger VPS Migration Guide", author="ARUN ENTERPRISES").build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
