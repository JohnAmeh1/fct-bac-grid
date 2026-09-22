"""
Run this OUTSIDE Django to confirm Mailtrap SMTP works on your machine:

    python test_mailtrap.py

If it prints "Email sent successfully!" the settings are correct.
If it prints an error, the problem is network/credentials, not Django.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

MAILTRAP_HOST     = 'live.smtp.mailtrap.io'
MAILTRAP_PORT     = 587
MAILTRAP_USER     = 'api'
MAILTRAP_PASSWORD = '6fda8db8ec83d4e24bfd6b2c4d35202e'
FROM_EMAIL        = 'hello@bacgrid.com'
TO_EMAIL          = 'johnameh29@gmail.com'   # change if needed

msg = MIMEMultipart()
msg['Subject'] = 'Mailtrap SMTP Test – FCT BAC Grid'
msg['From']    = f'FCT BAC Grid <{FROM_EMAIL}>'
msg['To']      = TO_EMAIL
msg.attach(MIMEText('If you see this, Mailtrap SMTP is working correctly!', 'plain'))

try:
    with smtplib.SMTP(MAILTRAP_HOST, MAILTRAP_PORT, timeout=15) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(MAILTRAP_USER, MAILTRAP_PASSWORD)
        server.sendmail(FROM_EMAIL, [TO_EMAIL], msg.as_string())
    print("✅  Email sent successfully!")
except smtplib.SMTPAuthenticationError as e:
    print(f"❌  Authentication failed — wrong token: {e}")
except smtplib.SMTPConnectError as e:
    print(f"❌  Could not connect to {MAILTRAP_HOST}:{MAILTRAP_PORT} — firewall/network issue: {e}")
except Exception as e:
    print(f"❌  Unexpected error: {type(e).__name__}: {e}")