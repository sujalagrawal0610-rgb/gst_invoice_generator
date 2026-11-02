# InvoiceFlow SME – GST Invoice Manager (v3)

Flask + SQLite. Billie-style dark/purple dashboard, real Gmail OTP login, multi-item GST invoices, clients, search, PDF re-download, admin panel.

> UI Tailwind CDN use karta hai (tumhare original pages jaisa), isliye browser me internet chahiye.
> v3 me Gmail SSL fix (`certifi`) aur original dark-navy design wapas aa gaya hai.

## 🚀 Quick start (2 minutes)

**Windows:** double-click `run.bat`
**Mac:** double-click `run.command`  (ya terminal me `./run.sh`)
**Manual:**
```bash
python -m venv venv
venv\Scripts\activate          # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # Mac/Linux: cp .env.example .env
python app.py
```
Browser me kholo: **http://127.0.0.1:5001**
(Port 5001 isliye hai kyunki Mac par 5000 AirPlay use karta hai – wahi purana "crash" ho sakta tha. `.env` me `PORT=` se badal sakte ho.)

## 📧 Real Gmail OTP setup (ek baar)

1. Jis Gmail se OTP **bhejna** hai, usme **2-Step Verification ON** karo → https://myaccount.google.com/security
2. https://myaccount.google.com/apppasswords kholo → App name `InvoiceFlow` → **Create** → 16 character ka password milega.
3. `.env` file kholo aur bharo:
   ```
   MAIL_USERNAME=tumhara_sender@gmail.com
   MAIL_PASSWORD=abcd efgh ijkl mnop      # App Password (normal Gmail password NAHI)
   ADMIN_EMAILS=admin1@gmail.com,admin2@gmail.com
   ```
4. App restart karo. Ab login par **jis bhi email se login karoge uske inbox me 6-digit OTP aayega** (Spam bhi dekh lena).

Agar `.env` me mail set nahi hai to app **Dev mode** me chalta hai (OTP terminal me print hota hai) taaki development na ruke. Mail set hone par terminal fallback band ho jata hai – fail hone par saaf error dikhta hai.

> ⚠️ `.env` kisi ko mat bhejo / GitHub par mat daalo. Purane code me jo Gmail password tha wo leak ho chuka hai – Google account me use badal do.

## ✨ Features
- Gmail OTP login: user + Admin portal. **OTP hamesha mail par jata hai**; admin portal me OTP verify hone ke BAAD check hota hai ki email admin hai ya nahi (nahi hai to simple "Access denied" message)
- Dashboard: stats, **All Invoices** cards, 12-month chart
- **Multi-item invoices**: quantity, per-item discount, **GST sirf auto** (item name se detect, koi manually select nahi kar sakta)
- Invoices page: search, pagination, **PDF dobara download**, duplicate invoice
- PDF: original **SME TAX INVOICE** format (navy header, Billed To, table, totals) – multi-item + multi-page support
- Admin panel: users, saare invoices, category chart, CSV export, delete
- Purana `invoice_app.db` automatically migrate ho jata hai

## 🐞 Top 10 crash/security bugs – fixed
| # | Bug (purana code) | Fix |
|---|---|---|
| 1 | Gmail password + secret key code me hardcoded | Sab `.env` se; secret key auto-generate |
| 2 | `debug=True` (remote code execution risk) | Default off (`FLASK_DEBUG=1` sirf dev me) |
| 3 | `/rate-input`, `/generate-invoice` bina login; email URL/form se → koi bhi kisi ke naam se invoice | Server-side session login, ownership checks, email kabhi URL me nahi |
| 4 | 4-digit OTP, no expiry, reuse, brute-force, restart par gayab | 6-digit, hashed in DB, 5 min expiry, 5 attempts, single-use, resend cooldown, rate-limit |
| 5 | Mail fail → chupchap terminal OTP; admin OTP kabhi mail nahi hota | Real mail dono ke liye; fail par clear error |
| 6 | `float(None/nan/inf/-5)` → HTTP 500 crash | Decimal validation + friendly error |
| 7 | Sab users ka PDF ek hi `static/invoice.pdf` → race / data leak | PDF in-memory, per request |
| 8 | Lamba address/Unicode PDF se bahar / garbled | Wrapping, multi-page, safe fonts |
| 9 | Relative DB path, DB lock, connection leak, tables missing | Absolute path, WAL, per-request close, auto-init + migration |
| 10 | `"open"` me `"pen"`, `"tablet"` double category → galat GST; float paisa | Whole-word detection, Decimal maths |

Extra: CSRF protection, logout POST, security headers, CSV-injection safe export, XSS-safe templates, nice 400/403/404/500 pages, double-submit guard.

## 🧪 Tests
```bash
python tests/test_app.py      # 68 checks, temporary DB use hota hai
```

## 🎨 Demo data (optional, charts bharne ke liye)
```bash
python seed_demo.py tumhara@gmail.com
```

## 📁 Structure
```
app.py          routes            services.py   GST/money logic     otp.py     OTP engine
db.py           schema+migration  mailer.py     Gmail SMTP          pdf_invoice.py  PDF
templates/ static/ fonts/         invoice_app.db (aapka data)       tests/
```

## 🔧 Troubleshooting
- **"Gmail rejected the login"** → App Password use karo, 2-Step ON hona chahiye, spaces chalenge.
- **OTP mail nahi aaya** → Spam check; `.env` save kiya? app restart kiya?
- **Hindi naam PDF me `?` dikhe** → `fonts/` me `NotoSansDevanagari-Regular.ttf` jaisa font daal sakte ho (free, Google Fonts). Kuch bhi crash/garble nahi hota.
- **Port busy** → `.env` me `PORT=5002`.
