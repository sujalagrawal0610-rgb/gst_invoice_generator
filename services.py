"""Pure business logic (no Flask): money maths, validation, GST category detection."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ALLOWED_GST = (0, 5, 12, 18, 28)
CENT = Decimal("0.01")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]$")
STATUSES = ("draft", "sent", "unpaid", "paid")


def q(d):
    return Decimal(d).quantize(CENT, rounding=ROUND_HALF_UP)


def parse_decimal(raw, field, lo, hi, default=None):
    """Parse user input safely. Raises ValueError with a human readable message
    (old code did float(None) / float('nan') and crashed with HTTP 500)."""
    raw = (raw or "").strip().replace(",", "")
    if raw == "":
        if default is not None:
            return Decimal(default)
        raise ValueError(f"{field} is required")
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{field} must be a number")
    if not d.is_finite():
        raise ValueError(f"{field} must be a valid number")
    if d < Decimal(lo) or d > Decimal(hi):
        raise ValueError(f"{field} must be between {lo} and {hi}")
    return d


def clean_text(s, maxlen):
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", (s or "")).strip()
    return s[:maxlen]


def valid_email(e):
    return bool(e) and len(e) <= 254 and bool(EMAIL_RE.match(e))


# ------------------------------------------------------------------ category / GST detection
# Whole-word matching. The old code used substring matching so "open" matched "pen",
# "activity" matched "tv" and "tablet" was both Electronics and Healthcare.
_RULES = [
    ("Luxury", 28, ["gold", "silver", "rolex", "mercedes", "bmw", "audi", "lamborghini", "ferrari", "porsche",
                    "diamond", "perfume", "yacht", "private jet", "crystal", "jewellery", "jewelry", "watch rolex",
                    "cigar", "champagne"]),
    ("Healthcare", 5, ["medicine", "capsule", "syrup", "bandage", "thermometer", "inhaler", "ointment",
                       "paracetamol", "vitamin", "sanitizer", "mask", "bp monitor", "glucometer", "tablet medicine",
                       "medical", "injection", "antibiotic"]),
    ("Electronics", 18, ["pen drive", "pendrive", "power bank", "powerbank", "earphone", "earbud", "earbuds",
                         "headphone", "airpods", "mobile", "phone", "smartphone", "laptop", "tv", "television",
                         "charger", "tablet", "ipad", "smartwatch", "camera", "speaker", "mouse", "keyboard",
                         "monitor", "printer", "router", "cable", "fridge", "refrigerator", "ac", "cooler",
                         "washing machine", "microwave", "drone", "console", "playstation", "xbox"]),
    ("Stationery", 12, ["notebook", "pen", "pencil", "eraser", "scale", "marker", "calculator", "folder", "stapler",
                        "book", "diary", "register", "paper", "highlighter", "sharpener", "glue", "file"]),
    ("Apparel", 12, ["clothing", "clothes", "shirt", "pant", "pants", "t-shirt", "tshirt", "jeans", "jacket",
                     "sweater", "saree", "kurti", "shorts", "dress", "hoodie", "shoe", "shoes", "sandal", "cap"]),
    ("Food", 5, ["rice", "wheat", "atta", "flour", "sugar", "tea", "coffee", "biscuit", "oil", "milk", "dal",
                 "pulses", "spice", "snack", "namkeen"]),
]


CATEGORIES = [(name, gst) for name, gst, _ in _RULES] + [("Other", 12)]  # every category the system can assign


def _norm(s):
    return " " + re.sub(r"[^a-z0-9\-]+", " ", s.lower()).strip() + " "


def _has(norm, kw):
    for form in (kw, kw + "s", kw + "es"):
        if f" {form} " in norm:
            return True
    return False


def detect_category(name):
    norm = _norm(name or "")
    for cat, gst, kws in _RULES:
        if any(_has(norm, k) for k in kws):
            return {"category": cat, "gst_rate": gst}
    return {"category": "Other", "gst_rate": 12}


# ------------------------------------------------------------------ invoice maths
def parse_items(names, qtys, rates, discs):
    """Validate form rows and return clean item dicts. GST is ALWAYS auto-detected from the item name
    (nobody can type or pick a GST rate). Raises ValueError on bad input."""
    rows = []
    n = max(len(names), len(qtys), len(rates), len(discs))
    if n > 50:
        raise ValueError("A maximum of 50 items per invoice is allowed")

    def at(lst, i):
        return lst[i] if i < len(lst) else ""

    for i in range(n):
        name = clean_text(at(names, i), 120)
        if not name and not at(rates, i).strip():
            continue  # fully empty row
        label = f"Item {len(rows) + 1}"
        if not name:
            raise ValueError(f"{label}: name is required")
        qty = parse_decimal(at(qtys, i), f"{label} quantity", "0.001", "1000000", default="1")
        rate = parse_decimal(at(rates, i), f"{label} rate", "0", "1000000000")
        disc = parse_decimal(at(discs, i), f"{label} discount", "0", "100", default="0")
        det = detect_category(name)
        rows.append({"name": name, "category": det["category"], "qty": qty, "rate": rate,
                     "disc": disc, "gst": Decimal(det["gst_rate"])})
    if not rows:
        raise ValueError("Add at least one item to the invoice")
    return rows


def compute(rows):
    items, sub, disc_t, gst_t, total = [], Decimal(0), Decimal(0), Decimal(0), Decimal(0)
    for r in rows:
        gross = q(r["qty"] * r["rate"])
        disc = q(gross * r["disc"] / 100)
        taxable = gross - disc
        gst = q(taxable * r["gst"] / 100)
        line = taxable + gst
        items.append({**r, "gross": gross, "line_discount": disc, "line_gst": gst, "line_total": line})
        sub += gross
        disc_t += disc
        gst_t += gst
        total += line
    if total > Decimal("100000000000"):
        raise ValueError("Invoice total is too large")
    return {"items": items, "subtotal": sub, "discount_total": disc_t, "gst_total": gst_t, "total": total}


def inr_plain(v, symbol="Rs. "):
    """Indian digit grouping: 1,28,000.00"""
    d = q(Decimal(str(v or 0)))
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", whole[:-3])
        whole = head + "," + whole[-3:]
    return f"{'-' if d < 0 else ''}{symbol}{whole}.{frac}"
