"""OTP engine: 6-digit, hashed in DB, expiring, attempt-limited, rate-limited, single use."""
import hashlib
import hmac
import secrets
import time

import config


def _hash(email, purpose, code):
    return hmac.new(config.SECRET_KEY.encode(), f"{email}|{purpose}|{code}".encode(), hashlib.sha256).hexdigest()


def create(db, email, purpose):
    """Returns (code, error). error is a human message when rate-limited."""
    t = time.time()
    last = db.execute("SELECT created_at FROM otps WHERE email=? AND purpose=? ORDER BY id DESC LIMIT 1",
                      (email, purpose)).fetchone()
    if last and t - last["created_at"] < config.OTP_RESEND_COOLDOWN_SEC:
        wait = int(config.OTP_RESEND_COOLDOWN_SEC - (t - last["created_at"])) + 1
        return None, f"Please wait {wait}s before requesting another code."
    recent = db.execute("SELECT COUNT(*) c FROM otps WHERE email=? AND created_at>?", (email, t - 600)).fetchone()["c"]
    if recent >= config.OTP_MAX_SENDS_PER_10MIN:
        return None, "Too many codes requested. Try again in a few minutes."
    code = f"{secrets.randbelow(10 ** 6):06d}"
    # keep the row that proves the cooldown, replace the usable code
    db.execute("DELETE FROM otps WHERE email=? AND purpose=?", (email, purpose))
    db.execute("INSERT INTO otps(email,purpose,code_hash,expires_at,created_at) VALUES (?,?,?,?,?)",
               (email, purpose, _hash(email, purpose, code), t + config.OTP_TTL_MIN * 60, t))
    db.commit()
    return code, None


def discard(db, email, purpose):
    db.execute("DELETE FROM otps WHERE email=? AND purpose=?", (email, purpose))
    db.commit()


def verify(db, email, purpose, code):
    """Returns (ok, error_message)."""
    row = db.execute("SELECT * FROM otps WHERE email=? AND purpose=? ORDER BY id DESC LIMIT 1",
                     (email, purpose)).fetchone()
    if not row:
        return False, "No active code. Please request a new one."
    if time.time() > row["expires_at"]:
        discard(db, email, purpose)
        return False, "This code has expired. Please request a new one."
    if row["attempts"] >= config.OTP_MAX_ATTEMPTS:
        discard(db, email, purpose)
        return False, "Too many wrong attempts. Please request a new code."
    code = (code or "").strip()
    if hmac.compare_digest(row["code_hash"], _hash(email, purpose, code)):
        discard(db, email, purpose)  # single use
        return True, ""
    db.execute("UPDATE otps SET attempts=attempts+1 WHERE id=?", (row["id"],))
    db.commit()
    left = config.OTP_MAX_ATTEMPTS - row["attempts"] - 1
    return False, f"Incorrect code. {left} attempt(s) left." if left > 0 else "Incorrect code. Request a new one."
