"""Real e-mail delivery of OTPs through Gmail SMTP (App Password)."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import config


def _ssl_context():
    """macOS python.org builds often ship without root certificates -> SSLCertVerificationError.
    certifi brings its own trusted certificate list, so mail works on every machine."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _html(code, purpose, ttl):
    what = "administrator login" if purpose == "admin" else "login"
    return f"""<!doctype html><html><body style="margin:0;background:#0e0e10;padding:32px 12px;font-family:Segoe UI,Arial,sans-serif">
<table align="center" width="440" cellpadding="0" cellspacing="0" style="background:#17171b;border-radius:18px;overflow:hidden;border:1px solid #2a2a31">
<tr><td style="background:#6d44f5;padding:22px 28px;color:#fff;font-size:20px;font-weight:700">{config.APP_NAME}.</td></tr>
<tr><td style="padding:28px;color:#d9d9e0;font-size:14px;line-height:1.6">
<p style="margin:0 0 14px">Use this code to complete your {what}:</p>
<p style="margin:0 0 18px;text-align:center;font-size:36px;letter-spacing:10px;font-weight:800;color:#fff;background:#0e0e10;border-radius:12px;padding:16px 0">{code}</p>
<p style="margin:0;color:#9a9aa6;font-size:12px">This code expires in {ttl} minutes. If you did not request it, you can safely ignore this e-mail - never share this code with anyone.</p>
</td></tr></table></body></html>"""


def send_otp_email(to_email, code, purpose="login"):
    """Returns (ok: bool, error_message: str)."""
    if not config.mail_configured():
        return False, "mail-not-configured"
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your {config.APP_NAME} verification code"
    msg["From"] = formataddr((config.MAIL_FROM_NAME, config.MAIL_USERNAME))
    msg["To"] = to_email
    msg.set_content(f"Your {config.APP_NAME} verification code is {code}\n"
                    f"It expires in {config.OTP_TTL_MIN} minutes. Do not share it with anyone.")
    msg.add_alternative(_html(code, purpose, config.OTP_TTL_MIN), subtype="html")
    try:
        if config.MAIL_PORT == 465:
            with smtplib.SMTP_SSL(config.MAIL_SERVER, 465, timeout=15, context=_ssl_context()) as s:
                s.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT, timeout=15) as s:
                s.ehlo()
                s.starttls(context=_ssl_context())
                s.ehlo()
                s.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
                s.send_message(msg)
        return True, ""
    except ssl.SSLCertVerificationError:
        return False, ("Your computer's SSL certificates are missing. Run:  pip install --upgrade certifi  "
                       "(Mac: also run 'Install Certificates.command' from your Python folder in Applications).")
    except smtplib.SMTPAuthenticationError:
        return False, ("Gmail rejected the login. Use a 16-character Google App Password "
                       "(not your normal Gmail password) in MAIL_PASSWORD.")
    except smtplib.SMTPRecipientsRefused:
        return False, "That e-mail address was refused by the mail server."
    except (smtplib.SMTPException, OSError) as e:
        return False, f"Could not send e-mail ({type(e).__name__}). Check internet / SMTP settings."
