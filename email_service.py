"""
AdatTracker Pro - Email Dispatcher Service
Supports Console (local testing), Standard SMTP (Gmail, SES, Mailgun, Brevo), and Resend API.
"""

import smtplib
import json
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple

from config import (
    EMAIL_BACKEND,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASS,
    SMTP_TLS,
    FROM_EMAIL,
    FROM_NAME,
    RESEND_API_KEY,
    OTP_EXPIRY_MINUTES
)

def send_otp_email(to_email: str, otp_code: str, username: str = "", purpose: str = "login") -> Tuple[bool, str]:
    """
    Sends the 6-digit OTP to the user's email address using the configured email backend.
    Returns: (success: bool, message: str)
    """
    subject = f"Your AdatTracker Verification Code: {otp_code}"
    
    # 1. Console Backend (Default for Local Dev / Testing)
    if EMAIL_BACKEND == "console":
        print("\n" + "═" * 60)
        print(f" ✉️  [ADATTRACKER EMAIL SIMULATOR — {purpose.upper()}]")
        print(f" 👉 Recipient : {to_email}")
        if username:
            print(f" 👉 Username  : @{username}")
        print(f" 🔑 OTP Code  : >>> {otp_code} <<<")
        print(f" ⏳ Expires   : {OTP_EXPIRY_MINUTES} minutes")
        print("═" * 60 + "\n")
        return True, "OTP logged to console."

    # 2. Resend API Backend
    if EMAIL_BACKEND == "resend" and RESEND_API_KEY:
        try:
            html_body = generate_html_email(otp_code, username, purpose)
            payload = {
                "from": f"{FROM_NAME} <{FROM_EMAIL}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body
            }
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                    "User-Agent": "AdatTracker/2.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    return True, "Email dispatched via Resend."
        except Exception as e:
            print(f"❌ Resend API error: {e}")
            return False, f"Failed to send email via Resend: {str(e)}"

    # 3. Standard SMTP Backend (Gmail, Mailgun, Amazon SES, Brevo, Custom SMTP)
    if EMAIL_BACKEND == "smtp":
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
            msg["To"] = to_email

            text_body = (
                f"Hello {username or 'there'},\n\n"
                f"Your AdatTracker verification code is: {otp_code}\n\n"
                f"This code will expire in {OTP_EXPIRY_MINUTES} minutes.\n"
                f"If you did not request this code, please ignore this email.\n\n"
                f"— The AdatTracker Team"
            )
            html_body = generate_html_email(otp_code, username, purpose)

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            if SMTP_PORT == 465:
                # SSL Connection
                server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
            else:
                # Standard Connection / STARTTLS
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
                if SMTP_TLS:
                    server.starttls()

            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)

            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
            server.quit()
            return True, "Email dispatched via SMTP."
        except Exception as e:
            print(f"❌ SMTP Dispatch Error: {e}")
            return False, f"SMTP error: {str(e)}"

    # Fallback to console warning if misconfigured
    print(f"⚠️ Warning: Unknown EMAIL_BACKEND '{EMAIL_BACKEND}'. OTP code for {to_email} is: {otp_code}")
    return True, "Fallback console logged."

def generate_html_email(otp_code: str, username: str, purpose: str) -> str:
    """Generates a responsive OLED-styled HTML verification email."""
    title_text = "Welcome to AdatTracker" if purpose == "signup" else "AdatTracker Login"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{title_text}</title>
    </head>
    <body style="margin:0;padding:0;background-color:#050508;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#e2e8f0;">
      <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:520px;margin:40px auto;background:#0c0e17;border:1px solid rgba(139,92,246,0.25);border-radius:16px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,0.8);">
        <tr>
          <td style="padding:32px 32px 16px;text-align:center;">
            <div style="display:inline-block;width:44px;height:44px;background:linear-gradient(135deg,#7c3aed,#4f46e5);border-radius:12px;line-height:44px;font-size:22px;color:#fff;">
              ⚡
            </div>
            <h1 style="color:#ffffff;font-size:22px;font-weight:800;margin:16px 0 6px;">{title_text}</h1>
            <p style="color:#94a3b8;font-size:13px;margin:0;">Passwordless Verification Code</p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px;text-align:center;">
            <p style="color:#cbd5e1;font-size:14px;line-height:1.5;margin:0 0 20px;">
              Hello <strong>{username or 'there'}</strong>,<br>
              Enter the 6-digit code below to securely authenticate your session:
            </p>
            <div style="background:rgba(124,58,237,0.12);border:1px solid rgba(139,92,246,0.4);border-radius:12px;padding:18px 24px;display:inline-block;margin:0 auto 20px;">
              <span style="font-family:'Courier New',Courier,monospace;font-size:32px;font-weight:900;letter-spacing:8px;color:#a78bfa;">
                {otp_code}
              </span>
            </div>
            <p style="color:#64748b;font-size:12px;margin:0;">
              ⏳ This code is single-use and expires in <strong>{OTP_EXPIRY_MINUTES} minutes</strong>.<br>
              If you didn't request this code, you can safely ignore this email.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:24px 32px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
            <p style="color:#475569;font-size:11px;margin:0;">
              AdatTracker Pro • Self-Hosted Habit & Ritual Engine
            </p>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
