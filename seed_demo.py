"""Optional: fill the database with realistic demo invoices so the dashboard/charts look alive.
Usage:  python seed_demo.py your@gmail.com"""
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import config
import db as database
import services as svc


def main(email):
    email = email.strip().lower()
    if not svc.valid_email(email):
        sys.exit("Please pass a valid e-mail: python seed_demo.py you@gmail.com")
    database.init_db()
    conn = database.connect()
    row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    uid = row["id"] if row else conn.execute("INSERT INTO users(email,is_admin,created_at) VALUES (?,0,?)",
                                            (email, database.now())).lastrowid
    random.seed(7)
    buyers = [("John Doe", "Indore, Madhya Pradesh"), ("Nike India", "Mumbai, Maharashtra"), ("Priya Sharma", "Bhopal, Madhya Pradesh"),
              ("Rahul Verma", "Gwalior, Madhya Pradesh"), ("Aisha Khan", "Jaipur, Rajasthan"), ("Dev Patel", "Ahmedabad, Gujarat")]
    catalog = ["Laptop", "Mobile Phone", "Notebook", "Pen Set", "Smartwatch", "Cotton Shirt", "Paracetamol Strip",
               "Keyboard", "Earphone", "Printer", "Rice 25kg", "Gold Chain"]
    rates = {"Gold Chain": (40000, 90000), "Laptop": (35000, 80000), "Printer": (8000, 20000)}
    now = datetime.now()
    for k in range(32):
        when = now - timedelta(days=random.randint(0, 340), hours=random.randint(0, 20))
        buyer, addr = random.choice(buyers)
        names = random.sample(catalog, random.randint(1, 3))
        rows = []
        for nm in names:
            lo, hi = rates.get(nm, (100, 15000))
            det = svc.detect_category(nm)
            rows.append({"name": nm, "category": det["category"], "qty": Decimal(random.randint(1, 4)),
                         "rate": Decimal(random.randint(lo, hi)), "disc": Decimal(random.choice([0, 0, 5, 10])),
                         "gst": Decimal(det["gst_rate"])})
        calc = svc.compute(rows)
        iid = conn.execute("""INSERT INTO invoices(invoice_no,user_id,buyer_name,buyer_address,status,
            subtotal,discount_total,gst_total,total,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (f"TMP-{k}-{random.random()}", uid, buyer, addr, "sent",
                            float(calc["subtotal"]), float(calc["discount_total"]), float(calc["gst_total"]),
                            float(calc["total"]), when.strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
        conn.execute("UPDATE invoices SET invoice_no=? WHERE id=?", (f"INV-{when.year}-{iid:05d}", iid))
        for it in calc["items"]:
            conn.execute("""INSERT INTO invoice_items(invoice_id,name,category,qty,rate,discount_pct,gst_rate,line_discount,
                line_gst,line_total) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (iid, it["name"], it["category"], float(it["qty"]), float(it["rate"]), float(it["disc"]),
                          float(it["gst"]), float(it["line_discount"]), float(it["line_gst"]), float(it["line_total"])))
    conn.commit()
    conn.close()
    print(f"Done! Added 32 demo invoices for {email}. Log in with that e-mail.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python seed_demo.py your@gmail.com")
    main(sys.argv[1])
