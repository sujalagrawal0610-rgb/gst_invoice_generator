"""InvoiceFlow SME - GST invoice manager (Flask + SQLite).  Run:  python app.py"""
import csv
import hmac
import io
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, make_response, redirect, render_template, request,
                   send_file, session, url_for)
from markupsafe import Markup

import config
import db as database
import mailer
import otp as otp_engine
import pdf_invoice
import services as svc

app = Flask(__name__)
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=256 * 1024,  # reject giant POST bodies
)
app.teardown_appcontext(database.close_db)
database.init_db()  # tables always exist, wherever the app is started from

PAGE_SIZE = 10


# ============================================================ helpers / template glue
def inr(v):
    try:
        d = svc.q(Decimal(str(v or 0)))
    except Exception:
        d = Decimal(0)
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        whole = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head) + "," + tail
    return f"{'-' if d < 0 else ''}\u20b9{whole}.{frac}"


app.jinja_env.filters["inr"] = inr

# Shared Tailwind class strings (same look as the original InvoiceFlow SME pages)
app.jinja_env.globals["ui"] = {
    "card": "bg-[#1d2939] rounded-2xl border border-slate-700 shadow-xl",
    "inp": "w-full px-4 py-3 bg-[#101828] border border-slate-600 rounded-lg text-white placeholder-slate-500 "
           "focus:ring-2 focus:ring-indigo-500 focus:outline-none",
    "lbl": "block text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2",
    "btn": "bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 px-5 rounded-lg transition duration-200 "
           "shadow-lg shadow-indigo-600/30 text-center inline-block cursor-pointer",
    "btn_ok": "bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-3 px-5 rounded-lg transition duration-200 "
              "shadow-lg shadow-emerald-600/30 text-center inline-block cursor-pointer",
    "btn_sm": "text-xs bg-slate-700 hover:bg-slate-600 text-slate-100 px-3 py-1.5 rounded-lg font-semibold "
              "inline-block cursor-pointer",
    "btn_in": "text-xs bg-indigo-500/10 text-indigo-300 px-3 py-1.5 rounded-lg border border-indigo-500/30 "
              "hover:bg-indigo-500/20 font-semibold inline-block cursor-pointer",
    "btn_del": "text-xs bg-rose-500/10 text-rose-400 px-3 py-1.5 rounded-lg border border-rose-500/20 "
               "hover:bg-rose-500/20 font-semibold inline-block cursor-pointer",
    "th": "p-3 text-xs text-slate-400 uppercase tracking-wider font-semibold whitespace-nowrap",
}


@app.template_filter("dt")
def fmt_dt(v):
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return v or ""


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.context_processor
def inject():
    return {"csrf_input": lambda: Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">'),
            "user": current_user(), "is_admin_user": is_admin(), "config_admins": config.ADMIN_EMAILS,
            "app_name": config.APP_NAME, "mail_ready": config.mail_configured()}


@app.before_request
def csrf_protect():
    if request.method == "POST":
        tok = request.form.get("_csrf", "")
        if not tok or not hmac.compare_digest(tok, session.get("_csrf", "")):
            abort(400, "Your session expired or the form is invalid. Please go back and try again.")


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


def current_user():
    if "_user" in g:
        return g._user
    u = None
    uid = session.get("uid")
    if uid:
        u = database.get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            session.clear()
    g._user = u
    return u


def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not current_user():
            flash("Please log in to continue.", "info")
            return redirect(url_for("home"))
        return f(*a, **kw)
    return w


def is_admin():
    u = current_user()
    return bool(u and session.get("is_admin") and u["email"] in config.ADMIN_EMAILS)


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not is_admin():
            if current_user():
                abort(403)
            flash("Admin login required.", "info")
            return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return w


def page_args():
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


def get_invoice_or_404(inv_id):
    row = database.get_db().execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
    if not row or (row["user_id"] != current_user()["id"] and not is_admin()):
        abort(404)
    return row


def month_series(db, where="", params=()):
    """Last 12 months of invoiced totals (zero-filled) for the chart."""
    today = date.today()
    months, (y, m) = [], (today.year, today.month)
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    rows = db.execute(f"""SELECT strftime('%Y-%m', created_at) ym, SUM(total) s, COUNT(*) c FROM invoices
                          WHERE created_at >= ? {where} GROUP BY ym""",
                      (f"{months[0][0]}-{months[0][1]:02d}-01", *params)).fetchall()
    by = {r["ym"]: r for r in rows}
    out = []
    for y, m in months:
        r = by.get(f"{y}-{m:02d}")
        out.append({"label": date(y, m, 1).strftime("%b"), "full": date(y, m, 1).strftime("%b %Y"),
                    "value": round(r["s"] or 0, 2) if r else 0, "count": r["c"] if r else 0})
    return out


# ============================================================ auth
@app.route("/")
def home():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("login.html", admin=False)


@app.route("/admin-login")
@app.route("/admin-auth")
def admin_login():
    if is_admin():
        return redirect(url_for("admin_panel"))
    return render_template("login.html", admin=True)


def _start_otp(email, purpose):
    """Create + e-mail an OTP. Returns an error string or None."""
    db = database.get_db()
    code, err = otp_engine.create(db, email, purpose)
    if err:
        return err
    if config.mail_configured():
        ok, msg = mailer.send_otp_email(email, code, purpose)
        if not ok:
            otp_engine.discard(db, email, purpose)  # never leave a code nobody received
            return msg
    else:  # development convenience only when no mail is configured
        print(f"\n[DEV MODE - mail not configured] OTP for {email}: {code}\n")
    return None


@app.route("/login/request", methods=["POST"])
def login_request():
    """The OTP is ALWAYS e-mailed. For the admin portal the admin check happens AFTER the code is verified."""
    purpose = "admin" if request.form.get("admin") == "1" else "login"
    email = svc.clean_text(request.form.get("email"), 254).lower()
    back = "admin_login" if purpose == "admin" else "home"
    if not svc.valid_email(email):
        flash("Please enter a valid e-mail address.", "error")
        return redirect(url_for(back))
    err = _start_otp(email, purpose)
    if err:
        flash(err, "error")
        return redirect(url_for(back))
    session["pending"] = {"email": email, "purpose": purpose}
    flash(f"Verification code sent to {email}." if config.mail_configured()
          else "Dev mode: mail is not configured, the code is printed in the terminal.", "success")
    return redirect(url_for("verify"))


@app.route("/verify", methods=["GET", "POST"])
def verify():
    p = session.get("pending")
    if not p:
        return redirect(url_for("home"))
    if request.method == "GET":
        return render_template("verify.html", email=p["email"], admin=p["purpose"] == "admin")
    code = re.sub(r"\D", "", request.form.get("otp", ""))
    ok, err = otp_engine.verify(database.get_db(), p["email"], p["purpose"], code)
    if not ok:
        flash(err, "error")
        return redirect(url_for("verify"))
    email, admin = p["email"], p["purpose"] == "admin"
    # ---- OTP is correct. NOW check admin rights ----
    if admin and email not in config.ADMIN_EMAILS:
        session.pop("pending", None)
        flash(f"Access denied: {email} is not an admin account. Please use the normal user login.", "error")
        return redirect(url_for("admin_login"))
    db = database.get_db()
    row = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if row:
        uid = row["id"]
        db.execute("UPDATE users SET last_login=?, is_admin=? WHERE id=?",
                   (database.now(), 1 if email in config.ADMIN_EMAILS else 0, uid))
    else:
        uid = db.execute("INSERT INTO users(email,is_admin,created_at,last_login) VALUES (?,?,?,?)",
                         (email, 1 if email in config.ADMIN_EMAILS else 0, database.now(), database.now())).lastrowid
    db.commit()
    session.clear()  # new session after login
    session.permanent = True
    session["uid"] = uid
    session["is_admin"] = 1 if admin else 0
    flash("Login successful.", "success")
    return redirect(url_for("admin_panel" if admin else "dashboard"))


@app.route("/verify/resend", methods=["POST"])
def verify_resend():
    p = session.get("pending")
    if not p:
        return redirect(url_for("home"))
    err = _start_otp(p["email"], p["purpose"])
    flash(err or "A new code has been sent.", "error" if err else "success")
    return redirect(url_for("verify"))


@app.route("/verify/cancel", methods=["POST"])
def verify_cancel():
    admin = (session.get("pending") or {}).get("purpose") == "admin"
    session.pop("pending", None)
    return redirect(url_for("admin_login" if admin else "home"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


# ============================================================ dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    db, uid = database.get_db(), current_user()["id"]
    stats = db.execute("""SELECT COUNT(*) n, COALESCE(SUM(total),0) total, COALESCE(SUM(gst_total),0) gst
        FROM invoices WHERE user_id=?""", (uid,)).fetchone()
    recent = db.execute("""SELECT i.*, (SELECT name FROM invoice_items WHERE invoice_id=i.id ORDER BY id LIMIT 1) first_item,
        (SELECT COUNT(*) FROM invoice_items WHERE invoice_id=i.id) item_count FROM invoices i
        WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 8""", (uid,)).fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent,
                           series=month_series(db, "AND user_id=?", (uid,)), nav="dashboard")


# ============================================================ invoices
def _list_invoices(base_where, params, qs, page):
    db = database.get_db()
    where, p = [base_where], list(params)
    if qs:
        where.append("(invoice_no LIKE ? OR buyer_name LIKE ? OR buyer_email LIKE ? OR EXISTS "
                     "(SELECT 1 FROM invoice_items it WHERE it.invoice_id=i.id AND it.name LIKE ?))")
        p += [f"%{qs}%"] * 4
    w = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) c FROM invoices i WHERE {w}", p).fetchone()["c"]
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(page, pages)
    rows = db.execute(f"""SELECT i.*, (SELECT COUNT(*) FROM invoice_items WHERE invoice_id=i.id) item_count,
        (SELECT email FROM users WHERE id=i.user_id) owner FROM invoices i WHERE {w}
        ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""", (*p, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    return rows, total, page, pages


@app.route("/invoices")
@login_required
def invoices():
    qs = svc.clean_text(request.args.get("q"), 60)
    rows, total, page, pages = _list_invoices("user_id=?", (current_user()["id"],), qs, page_args())
    return render_template("invoices.html", rows=rows, total=total, page=page, pages=pages, q=qs,
                           nav="invoices", endpoint="invoices")


@app.route("/invoices/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    db, u = database.get_db(), current_user()
    if request.method == "POST":
        try:
            buyer_name = svc.clean_text(request.form.get("buyer_name"), 100)
            buyer_addr = svc.clean_text(request.form.get("buyer_address"), 300)
            buyer_email = svc.clean_text(request.form.get("buyer_email"), 254).lower()
            if not buyer_name:
                raise ValueError("Buyer name is required")
            if not buyer_addr:
                raise ValueError("Buyer address is required")
            if buyer_email and not svc.valid_email(buyer_email):
                raise ValueError("Buyer e-mail is not valid")
            rows = svc.parse_items(*(request.form.getlist(k) for k in
                                     ("item_name", "item_qty", "item_rate", "item_disc")))
            calc = svc.compute(rows)
            cur = db.execute("""INSERT INTO invoices(invoice_no,user_id,buyer_name,buyer_email,buyer_address,
                status,subtotal,discount_total,gst_total,total,notes,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (f"TMP-{secrets.token_hex(6)}", u["id"], buyer_name, buyer_email, buyer_addr, "sent",
                              float(calc["subtotal"]), float(calc["discount_total"]), float(calc["gst_total"]),
                              float(calc["total"]), svc.clean_text(request.form.get("notes"), 500), database.now()))
            inv_id = cur.lastrowid
            db.execute("UPDATE invoices SET invoice_no=? WHERE id=?", (f"INV-{date.today().year}-{inv_id:05d}", inv_id))
            for it in calc["items"]:
                db.execute("""INSERT INTO invoice_items(invoice_id,name,category,qty,rate,discount_pct,gst_rate,
                    line_discount,line_gst,line_total) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (inv_id, it["name"], it["category"], float(it["qty"]), float(it["rate"]), float(it["disc"]),
                            float(it["gst"]), float(it["line_discount"]), float(it["line_gst"]), float(it["line_total"])))
            db.commit()
            flash("Invoice created.", "success")
            return redirect(url_for("invoice_view", inv_id=inv_id))
        except ValueError as e:
            db.rollback()
            flash(str(e), "error")

    prefill = {"rows": []}
    if request.method == "GET":
        if request.args.get("from", "").isdigit():
            src = db.execute("SELECT * FROM invoices WHERE id=? AND user_id=?",
                             (int(request.args["from"]), u["id"])).fetchone()
            if src:
                prefill.update(buyer_name=src["buyer_name"], buyer_email=src["buyer_email"],
                               buyer_address=src["buyer_address"], notes=src["notes"])
                prefill["rows"] = [dict(name=i["name"], qty=i["qty"], rate=i["rate"], disc=i["discount_pct"])
                                   for i in db.execute("SELECT * FROM invoice_items WHERE invoice_id=?", (src["id"],))]
    else:  # re-show what the user typed after a validation error
        names, qtys, rates, discs = (request.form.getlist(k) for k in ("item_name", "item_qty", "item_rate", "item_disc"))
        for i, n in enumerate(names[:50]):
            at = lambda l: l[i] if i < len(l) else ""
            prefill["rows"].append(dict(name=n, qty=at(qtys), rate=at(rates), disc=at(discs)))
        prefill.update(buyer_name=request.form.get("buyer_name", ""), buyer_email=request.form.get("buyer_email", ""),
                       buyer_address=request.form.get("buyer_address", ""), notes=request.form.get("notes", ""))
    return render_template("invoice_new.html", prefill=prefill, nav="new")


@app.route("/invoices/<int:inv_id>")
@login_required
def invoice_view(inv_id):
    inv = get_invoice_or_404(inv_id)
    items = database.get_db().execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id", (inv_id,)).fetchall()
    return render_template("invoice_view.html", inv=inv, items=items, nav="invoices")


@app.route("/invoices/<int:inv_id>/pdf")
@login_required
def invoice_pdf(inv_id):
    inv = get_invoice_or_404(inv_id)
    items = database.get_db().execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id", (inv_id,)).fetchall()
    return send_file(pdf_invoice.build_pdf(inv, items), mimetype="application/pdf",
                     as_attachment=request.args.get("dl") == "1", download_name=f"{inv['invoice_no']}.pdf")


@app.route("/invoices/<int:inv_id>/delete", methods=["POST"])
@login_required
def invoice_delete(inv_id):
    get_invoice_or_404(inv_id)
    db = database.get_db()
    db.execute("DELETE FROM invoices WHERE id=?", (inv_id,))
    db.commit()
    flash("Invoice deleted.", "info")
    return redirect(url_for("admin_panel") if is_admin() and request.form.get("from") == "admin"
                    else url_for("invoices"))


@app.route("/api/detect")
@login_required
def api_detect():
    return jsonify(svc.detect_category(svc.clean_text(request.args.get("name"), 120)))


# ============================================================ admin
@app.route("/admin-dashboard")
@app.route("/admin")
@admin_required
def admin_panel():
    db = database.get_db()
    qs = svc.clean_text(request.args.get("q"), 60)
    rows, total, page, pages = _list_invoices("1=1", (), qs, page_args())
    stats = db.execute("SELECT COUNT(*) n, COALESCE(SUM(total),0) total, COALESCE(SUM(gst_total),0) gst FROM invoices").fetchone()
    users = db.execute("""SELECT u.*, (SELECT COUNT(*) FROM invoices WHERE user_id=u.id) inv_n,
        (SELECT COALESCE(SUM(total),0) FROM invoices WHERE user_id=u.id) billed FROM users u ORDER BY u.id DESC""").fetchall()
    got = {(r["category"] or "Other"): r for r in db.execute(
        """SELECT category, COUNT(*) c, COALESCE(SUM(line_total),0) s FROM invoice_items GROUP BY category""")}
    grand = sum(r["s"] for r in got.values()) or 1
    cats = [{"name": n, "gst": g, "count": got[n]["c"] if n in got else 0, "amount": got[n]["s"] if n in got else 0,
             "pct": round((got[n]["s"] if n in got else 0) / grand * 100, 1)} for n, g in svc.CATEGORIES]
    cats.sort(key=lambda c: -c["amount"])  # ALL categories are always listed, even with 0 sales
    return render_template("admin.html", rows=rows, total=total, page=page, pages=pages, q=qs, stats=stats,
                           users=users, cats=cats, series=month_series(db), nav="admin", endpoint="admin_panel",
                           user_n=len(users))


@app.route("/admin/export.csv")
@admin_required
def admin_export():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["invoice_no", "user_email", "buyer", "subtotal", "discount", "gst", "total", "created_at"])

    def safe(v):  # stop spreadsheet formula injection
        v = "" if v is None else str(v)
        return "'" + v if v[:1] in "=+-@" else v

    for r in database.get_db().execute("SELECT i.*, u.email owner FROM invoices i JOIN users u ON u.id=i.user_id ORDER BY i.id"):
        w.writerow([safe(r["invoice_no"]), safe(r["owner"]), safe(r["buyer_name"]), r["subtotal"],
                    r["discount_total"], r["gst_total"], r["total"], r["created_at"]])
    resp = make_response(out.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=invoices.csv"
    return resp


# ============================================================ errors
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(413)
def client_error(e):
    return render_template("error.html", code=e.code, title=e.name, message=getattr(e, "description", "")), e.code


@app.errorhandler(Exception)
def server_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return client_error(e)
    app.logger.exception("Unhandled error")
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error occurred. Nothing was lost - please try again."), 500


if __name__ == "__main__":
    print(f"\n  {config.APP_NAME} running at http://{config.HOST}:{config.PORT}")
    print("  OTP mode:", "REAL GMAIL" if config.mail_configured() else "DEV (terminal) - set MAIL_USERNAME/MAIL_PASSWORD in .env")
    print("  Admin emails:", ", ".join(sorted(config.ADMIN_EMAILS)) or "none - set ADMIN_EMAILS in .env", "\n")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False, threaded=True)
