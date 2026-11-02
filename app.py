import os, re, sqlite3, secrets, uuid, time, hashlib, hmac
from functools import wraps
from flask import Flask, g, render_template, request, redirect, session, flash, abort, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
import mailer
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
def _writable(d):
    try:
        os.makedirs(os.path.join(d, "uploads"), exist_ok=True)
        t = os.path.join(d, ".w"); open(t, "w").close(); os.remove(t); return True
    except OSError: return False
DATA = os.environ.get("DATA_DIR") or os.path.join(BASE, "data")
if not _writable(DATA):
    print("WARNING: %s is not writable, using /tmp/tuneflix (data will NOT persist)" % DATA, flush=True)
    DATA = "/tmp/tuneflix"; os.makedirs(os.path.join(DATA, "uploads"), exist_ok=True)
UPLOADS = os.path.join(DATA, "uploads")
DB = os.path.join(DATA, "tuneflix.db")
REQUIRE_APPROVAL = os.environ.get("REQUIRE_APPROVAL", "1") == "1"   # 1 = new users wait for admin approval, 0 = open signup
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").lower()   # this email becomes admin + auto-approved

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config.update(MAX_CONTENT_LENGTH=200*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")))
AUDIO = {"wav", "mp3", "flac", "m4a", "aac"}; IMG = {"jpg", "jpeg", "png", "webp"}; DOC = IMG | {"pdf"}

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, timeout=30); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d: d.close()

# extra columns added on top of the original tables (safe to run on an existing database)
USER_COLS = ["acct_type", "phone", "company", "signatory", "country", "state", "city", "address", "website", "pan",
             "has_agreement", "old_distributor", "change_reason", "revenue_6m", "revenue_cur", "email_verified", "aadhaar", "aadhaar_file", "pan_file"]
REL_COLS = ["rtype", "version", "featuring", "subgenre", "original_date", "upc", "p_line", "c_line", "description",
            "track_title", "primary_type", "secondary_type", "instrumental", "key_track", "publisher", "track_language",
            "advisory", "film_director", "music_director", "lyricist", "composer", "producer", "isrc", "lyrics",
            "preview_start", "stores"]

def init():
    c = sqlite3.connect(DB, timeout=30)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, kind TEXT,
      password TEXT, status TEXT DEFAULT 'pending', is_admin INTEGER DEFAULT 0, api_key TEXT UNIQUE, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS releases(id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, artist TEXT, genre TEXT,
      release_date TEXT, cover TEXT, audio TEXT, status TEXT DEFAULT 'submitted', created TEXT DEFAULT CURRENT_TIMESTAMP);""")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, name TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS reqs(id INTEGER PRIMARY KEY, user_id INTEGER, kind TEXT, subject TEXT, detail TEXT, status TEXT DEFAULT 'pending', created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS wallet(id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, note TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS splits(id INTEGER PRIMARY KEY, user_id INTEGER, release_id INTEGER, name TEXT, pct REAL);
    CREATE TABLE IF NOT EXISTS presaves(id INTEGER PRIMARY KEY, user_id INTEGER, release_id INTEGER, slug TEXT UNIQUE, spotify TEXT, apple TEXT, youtube TEXT, drop_date TEXT);""")
    for s in ["ALTER TABLE users ADD COLUMN avatar TEXT", "ALTER TABLE releases ADD COLUMN label TEXT", "ALTER TABLE releases ADD COLUMN language TEXT", "ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'approved'"] \
            + ["ALTER TABLE users ADD COLUMN %s TEXT" % k for k in USER_COLS] + ["ALTER TABLE releases ADD COLUMN %s TEXT" % k for k in REL_COLS]:
        try: c.execute(s)
        except sqlite3.OperationalError: pass
    c.executescript("CREATE TABLE IF NOT EXISTS captcha_challenges(token_hash TEXT PRIMARY KEY, session_hash TEXT, question TEXT, answer_hash TEXT, expires REAL, attempts INTEGER DEFAULT 0, verified INTEGER DEFAULT 0);")
    c.executescript("CREATE TABLE IF NOT EXISTS resets(id INTEGER PRIMARY KEY, user_id INTEGER, token_hash TEXT, expires REAL, used INTEGER DEFAULT 0);")
    try: c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error: pass
    c.commit(); c.close()
init()

def ensure_admin():
    if not (ADMIN_EMAIL and ADMIN_PASSWORD): return
    c = sqlite3.connect(DB, timeout=30)
    try:
        h = generate_password_hash(ADMIN_PASSWORD)
        if c.execute("SELECT 1 FROM users WHERE email=?", (ADMIN_EMAIL,)).fetchone():
            c.execute("UPDATE users SET password=?,is_admin=1,status='approved' WHERE email=?", (h, ADMIN_EMAIL))
        else:
            c.execute("INSERT INTO users(name,email,kind,password,status,is_admin,api_key) VALUES(?,?,?,?,?,?,?)",
                      ("Admin", ADMIN_EMAIL, "Admin", h, "approved", 1, "tf_" + secrets.token_urlsafe(24)))
        c.commit()
    except sqlite3.Error as e: print("ensure_admin failed:", e, flush=True)
    finally: c.close()
ensure_admin()

def csrf():
    if "csrf" not in session: session["csrf"] = secrets.token_hex(16)
    return session["csrf"]
app.jinja_env.globals["csrf"] = csrf

@app.before_request
def check_csrf():
    if request.method == "POST" and request.path.startswith("/api/") is False:
        if request.form.get("csrf") != session.get("csrf"): abort(400, "Bad CSRF token")

def me():
    if "uid" not in session: return None
    return db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()

def need(admin=False):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = me()
            if not u: return redirect("/admin/login" if admin else "/login")
            if u["status"] != "approved": session.clear(); flash("Your account is not approved yet.", ""); return redirect("/login")
            if admin and not u["is_admin"]: flash("Admin access only.", "err"); return redirect("/admin/login")
            return f(u, *a, **k)
        return w
    return deco

@app.context_processor
def _v(): return {"asset_v": int(os.path.getmtime(os.path.join(BASE, "static", "style.css")))}

@app.route("/")
def index(): return render_template("index.html")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

def captcha_digest(value):
    return hmac.new(str(app.secret_key).encode(), value.encode(), hashlib.sha256).hexdigest()

def captcha_session_hash():
    if "captcha_session" not in session:
        session["captcha_session"] = secrets.token_urlsafe(24)
    return captcha_digest(session["captcha_session"])

def new_captcha():
    session_hash = captcha_session_hash()
    now = time.time()
    db().execute("DELETE FROM captcha_challenges WHERE expires<=?", (now,))
    old_token = session.pop("captcha_token", None)
    if old_token:
        db().execute("DELETE FROM captcha_challenges WHERE token_hash=?", (captcha_digest(old_token),))
    left, right = secrets.randbelow(40) + 10, secrets.randbelow(40) + 10
    token = secrets.token_urlsafe(32)
    question = "What is %d + %d?" % (left, right)
    db().execute(
        "INSERT INTO captcha_challenges(token_hash,session_hash,question,answer_hash,expires) VALUES(?,?,?,?,?)",
        (captcha_digest(token), session_hash, question, captcha_digest(str(left + right)), now + 300))
    db().commit()
    session["captcha_token"] = token
    return {"token": token, "question": question}

def current_captcha():
    token = session.get("captcha_token")
    if token:
        row = db().execute(
            "SELECT question FROM captcha_challenges WHERE token_hash=? AND session_hash=? AND expires>?",
            (captcha_digest(token), captcha_session_hash(), time.time())).fetchone()
        if row:
            return {"token": token, "question": row["question"]}
    return new_captcha()

def captcha_is_verified(token):
    if not token or not hmac.compare_digest(token, session.get("captcha_token", "")):
        return False
    row = db().execute(
        "SELECT verified FROM captcha_challenges WHERE token_hash=? AND session_hash=? AND expires>?",
        (captcha_digest(token), captcha_session_hash(), time.time())).fetchone()
    return bool(row and row["verified"])

@app.route("/request-access/captcha/verify", methods=["POST"])
def captcha_verify():
    token = request.form.get("captcha_token", "")
    if not token or not hmac.compare_digest(token, session.get("captcha_token", "")):
        return jsonify(ok=False, msg="This CAPTCHA has expired. Please refresh it."), 400
    row = db().execute(
        "SELECT answer_hash,attempts,verified FROM captcha_challenges WHERE token_hash=? AND session_hash=? AND expires>?",
        (captcha_digest(token), captcha_session_hash(), time.time())).fetchone()
    if not row:
        return jsonify(ok=False, msg="This CAPTCHA has expired. Please refresh it."), 400
    if row["verified"]:
        return jsonify(ok=True, msg="CAPTCHA verified. You can submit your registration.")
    if row["attempts"] >= 5:
        return jsonify(ok=False, msg="Too many attempts. Please refresh the CAPTCHA."), 429
    answer_hash = captcha_digest(request.form.get("answer", "").strip())
    if not hmac.compare_digest(row["answer_hash"], answer_hash):
        db().execute("UPDATE captcha_challenges SET attempts=attempts+1 WHERE token_hash=?", (captcha_digest(token),))
        db().commit()
        return jsonify(ok=False, msg="That answer is not correct. Please try again."), 400
    db().execute("UPDATE captcha_challenges SET verified=1 WHERE token_hash=?", (captcha_digest(token),))
    db().commit()
    return jsonify(ok=True, msg="CAPTCHA verified. You can submit your registration.")

@app.route("/request-access/captcha/new", methods=["POST"])
def captcha_new():
    return jsonify(ok=True, captcha=new_captcha())

@app.route("/register")
def register_alias(): return redirect("/request-access")

@app.route("/request-access", methods=["GET", "POST"])
def request_access():
    if me(): return redirect("/studio")
    if request.method == "POST":
        f = request.form; v = {k: (f.get(k) or "").strip() for k in f.keys()}
        email = v.get("email", "").lower(); v["email"] = email
        def back(msg):
            flash(msg, "err"); return render_template("register.html", v=v, step=1, captcha=current_captcha())
        acct = v.get("acct_type", "")
        if acct not in ("Individual", "Company"): return back("Please choose Individual or Company.")
        if not v.get("name"): return back("Please enter your full name.")
        if acct == "Company" and not (v.get("company") and v.get("signatory")): return back("Company name and authorized signatory are required.")
        if not EMAIL_RE.match(email): return back("Please enter a valid email address.")
        phone = re.sub(r"[\s\-()]", "", v.get("phone", ""))
        if not re.match(r"^\+?\d{7,15}$", phone): return back("Please enter a valid mobile number.")
        v["phone"] = phone
        if not (v.get("country") and v.get("city")): return back("Country and city are required.")
        aad = re.sub(r"[\s-]", "", v.get("aadhaar", "")); pan = v.get("pan", "").upper().replace(" ", ""); v["pan"] = pan
        if not re.match(r"^[2-9]\d{11}$", aad): return back("Please enter a valid 12-digit Aadhaar number.")
        if not re.match(r"^[A-Z]{5}\d{4}[A-Z]$", pan): return back("Please enter a valid PAN number (example: ABCDE1234F).")
        for key, label in (("aadhaar_file", "Aadhaar card"), ("pan_file", "PAN card")):
            fl = request.files.get(key)
            if not fl or not fl.filename: return back("Please upload your %s (JPG, PNG or PDF)." % label)
            if fl.filename.rsplit(".", 1)[-1].lower() not in DOC: return back("%s must be a JPG, PNG or PDF file." % label)
            fl.seek(0, 2); size = fl.tell(); fl.seek(0)
            if size > 5 * 1024 * 1024: return back("%s file must be smaller than 5 MB." % label)
        if len(f.get("password", "")) < 8: return back("Password must be at least 8 characters.")
        if f.get("password") != f.get("confirm"): return back("Passwords do not match.")
        has = v.get("has_agreement", "No")
        if has not in ("Yes", "No"): has = "No"
        if has == "Yes" and not v.get("change_reason"): return back("Please tell us the reason for changing your distributor.")
        rev = v.get("revenue_6m", "")
        if rev:
            try: rev = "%.2f" % max(0.0, float(rev))
            except ValueError: return back("Revenue must be a number.")
        if db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            flash("This email is already registered. Try signing in.", "err"); return redirect("/login")
        if not captcha_is_verified(f.get("captcha_token", "")):
            return back("Please complete the CAPTCHA before submitting.")
        admin = int(bool(ADMIN_EMAIL) and email == ADMIN_EMAIL)
        ok = bool(admin) or not REQUIRE_APPROVAL
        aad_file = save(request.files.get("aadhaar_file"), DOC); pan_file = save(request.files.get("pan_file"), DOC)
        display = v.get("company") if acct == "Company" and v.get("company") else v["name"]
        cur = db().execute("""INSERT INTO users(name,email,kind,password,status,is_admin,api_key,acct_type,phone,company,signatory,country,state,city,address,website,pan,
              has_agreement,old_distributor,change_reason,revenue_6m,revenue_cur,email_verified,aadhaar,aadhaar_file,pan_file) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (display, email, acct, generate_password_hash(f["password"]), "approved" if ok else "pending", admin, "tf_" + secrets.token_urlsafe(24),
             acct, phone, v.get("company"), v.get("signatory") or v["name"], v.get("country"), v.get("state"), v.get("city"), v.get("address"), v.get("website"), v.get("pan"),
             has, v.get("old_distributor"), v.get("change_reason"), rev, v.get("revenue_cur") or "INR", "0", aad, aad_file, pan_file))
        db().execute("DELETE FROM captcha_challenges WHERE token_hash=?", (captcha_digest(f.get("captcha_token", "")),)); db().commit()
        if ok:
            session.clear(); session["uid"] = cur.lastrowid; session["welcome"] = 1
            flash("Welcome to Tuneflix! Your account is ready.", "ok")
            return redirect("/admin" if admin else "/studio")
        if ADMIN_EMAIL: mailer.send(ADMIN_EMAIL, "New Tuneflix registration", mailer.wrap("New registration", "%s (%s, %s) has registered and is waiting for approval." % (display, email, acct), "Open admin panel", request.host_url + "admin"))
        session.clear(); session["reg_type"] = acct
        return redirect("/thanks")
    return render_template("register.html", v={}, step=1, captcha=new_captcha())

@app.route("/login", methods=["GET", "POST"])
def login():
    if me(): return redirect("/studio")
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
        if not u or not check_password_hash(u["password"], request.form["password"]): flash("Wrong email or password.", "err")
        elif u["status"] == "pending": return redirect("/thanks")
        elif u["status"] != "approved": flash("Your application was not approved. Please contact our team.", "err")
        else: session.clear(); session["uid"] = u["id"]; session["welcome"] = 1; return redirect("/admin" if u["is_admin"] else "/studio")
        return redirect("/login")
    return render_template("auth.html", signup=False)

@app.route("/logout")
def logout(): session.clear(); return redirect("/")

def save(file, allowed):
    if not file or not file.filename: return None
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in allowed: abort(400, "File type not allowed")
    name = uuid.uuid4().hex + "_" + secure_filename(file.filename)
    file.save(os.path.join(UPLOADS, name)); return name

@app.route("/files/<path:name>")
@need()
def files(u, name):
    owner = db().execute("SELECT user_id FROM releases WHERE audio=? OR cover=? UNION SELECT id FROM users WHERE avatar=? OR aadhaar_file=? OR pan_file=?", (name, name, name, name, name)).fetchone()
    if not owner or (owner["user_id"] != u["id"] and not u["is_admin"]): abort(404)
    return send_from_directory(UPLOADS, name)

@app.route("/api/v1/releases")
def api_releases():
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    u = db().execute("SELECT * FROM users WHERE api_key=? AND status='approved'", (key,)).fetchone()
    if not u: return jsonify(error="invalid api key"), 401
    rows = db().execute("SELECT id,title,artist,genre,release_date,status,created FROM releases WHERE user_id=?", (u["id"],)).fetchall()
    return jsonify(releases=[dict(r) for r in rows])

@app.route("/healthz")
def health(): return "ok"

import account, studio
account.setup(app, db, need)
studio.setup(app, db, need, save, IMG, AUDIO, UPLOADS)

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
