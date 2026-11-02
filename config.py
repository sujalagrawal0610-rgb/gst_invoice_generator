"""Central configuration. Every secret comes from the .env file - never hardcode passwords in code."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env():
    p = BASE_DIR / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def env(key, default=""):
    return os.environ.get(key, default)


def _secret_key():
    """Use SECRET_KEY from .env, else create one once and keep it in .secret_key
    so sessions survive restarts (old code lost every login on restart)."""
    k = env("SECRET_KEY")
    if k:
        return k
    f = BASE_DIR / ".secret_key"
    if f.exists():
        return f.read_text().strip()
    k = secrets.token_hex(32)
    f.write_text(k)
    return k


SECRET_KEY = _secret_key()
DB_PATH = str(BASE_DIR / env("DB_FILE", "invoice_app.db"))  # absolute path: works from any folder

HOST = env("HOST", "127.0.0.1")
PORT = int(env("PORT", "5001") or 5001)  # 5000 is used by AirPlay on macOS -> avoid
DEBUG = env("FLASK_DEBUG", "0") == "1"

MAIL_SERVER = env("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(env("MAIL_PORT", "587") or 587)
MAIL_USERNAME = env("MAIL_USERNAME")
MAIL_PASSWORD = env("MAIL_PASSWORD").replace(" ", "")  # Google shows app passwords with spaces
MAIL_FROM_NAME = env("MAIL_FROM_NAME", "InvoiceFlow")
ADMIN_EMAILS = {e.strip().lower() for e in env("ADMIN_EMAILS").split(",") if e.strip()}

OTP_TTL_MIN = int(env("OTP_TTL_MIN", "5") or 5)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SEC = 30
OTP_MAX_SENDS_PER_10MIN = 5

APP_NAME = "InvoiceFlow"


def mail_configured():
    return bool(MAIL_USERNAME and MAIL_PASSWORD)
