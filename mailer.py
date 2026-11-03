"""Tiny mail helper. Uses HTTPS APIs (work on Render free plan) or SMTP. Never raises."""
import json, os, smtplib, threading, urllib.request
from email.message import EmailMessage

def configured():
    return bool(os.environ.get("BREVO_API_KEY") or os.environ.get("RESEND_API_KEY") or os.environ.get("SMTP_HOST"))

def _post(url, body, headers):
    h = {"content-type": "application/json", "accept": "application/json", "user-agent": "Tuneflix/1.0"}
    h.update(headers)
    urllib.request.urlopen(urllib.request.Request(url, json.dumps(body).encode(), h), timeout=20).read()

def _send(to, subject, html):
    frm = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER") or ""
    name = os.environ.get("MAIL_NAME", "Tuneflix")
    if not frm:
        print("MAIL ERROR: MAIL_FROM (or SMTP_USER) is not configured", flush=True)
        return False
    try:
        if os.environ.get("BREVO_API_KEY"):
            _post("https://api.brevo.com/v3/smtp/email", {"sender": {"name": name, "email": frm}, "to": [{"email": to}],
                  "subject": subject, "htmlContent": html}, {"api-key": os.environ["BREVO_API_KEY"]})
        elif os.environ.get("RESEND_API_KEY"):
            _post("https://api.resend.com/emails", {"from": "%s <%s>" % (name, frm), "to": [to], "subject": subject, "html": html},
                  {"Authorization": "Bearer " + os.environ["RESEND_API_KEY"]})
        elif os.environ.get("SMTP_HOST"):
            m = EmailMessage(); m["From"] = "%s <%s>" % (name, frm); m["To"] = to; m["Subject"] = subject
            m.set_content("Please view this email in an HTML-capable client."); m.add_alternative(html, subtype="html")
            port = int(os.environ.get("SMTP_PORT", "587"))
            s = smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, timeout=20) if port == 465 else smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20)
            if port != 465: s.starttls()
            if os.environ.get("SMTP_USER"): s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(m); s.quit()
        else:
            return False
        return True
    except Exception as e:
        print("MAIL ERROR: provider rejected or could not deliver message to %s: %s" % (to, e), flush=True)
        return False

def send_now(to, subject, html):
    """Send before returning so callers can report actual provider acceptance."""
    if not configured():
        print("MAIL ERROR: no mail provider is configured", flush=True)
        return False
    return _send(to, subject, html)

def send(to, subject, html):
    """Send in background. Returns True if a mail provider is configured."""
    if not configured(): return False
    threading.Thread(target=_send, args=(to, subject, html), daemon=True).start()
    return True

def _head():
    """Logo banner for emails. Uses the hosted logo when the public URL is known, otherwise a text wordmark in the same colours."""
    base = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
    st = "font-family:Arial Black,Arial,sans-serif;font-size:30px;font-weight:900;font-style:italic;"
    word = '<span style="%scolor:#fff">Tune</span><span style="%scolor:#ff0010">flix</span>' % (st, st)
    inner = ('<img src="%s/static/logo.png" alt="Tuneflix" height="56" style="display:block;margin:auto;height:56px;width:auto">' % base) if base.startswith("http") else word
    return '<div style="background:#000;border-radius:10px;padding:14px;text-align:center;margin:0 0 18px">%s</div>' % inner

def wrap(title, body, btn_text=None, btn_url=None):
    b = ('<p style="margin:26px 0"><a href="%s" style="background:#e30e0e;color:#fff;padding:13px 26px;border-radius:10px;'
         'text-decoration:none;font-weight:700">%s</a></p>' % (btn_url, btn_text)) if btn_url else ""
    return ('<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:28px;border:1px solid #eee;border-radius:14px">'
            '%s<h3>%s</h3><p style="color:#444;line-height:1.6">%s</p>%s'
            '<p style="color:#999;font-size:12px">If you did not expect this email, you can ignore it.</p></div>' % (_head(), title, body, b))
