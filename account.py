import hashlib, hmac, os, re, secrets, time
from flask import render_template, request, redirect, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import mailer

def setup(app, db, need):
    sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
    def base_url(): return os.environ.get("BASE_URL", "").rstrip("/") or request.host_url.rstrip("/")

    def make_link(uid):
        t = secrets.token_urlsafe(32); d = db()
        d.execute("DELETE FROM resets WHERE user_id=?", (uid,))
        d.execute("INSERT INTO resets(user_id,token_hash,expires) VALUES(?,?,?)", (uid, sha(t), time.time() + 3600)); d.commit()
        return base_url() + "/reset/" + t

    @app.route("/thanks")
    def thanks(): return render_template("thanks.html", company=session.get("reg_type") == "Company")

    # ---- email OTP for registration (same flow as the reference page: Generate -> enter code -> Verify -> Submit) ----
    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
    otp_hash = lambda email, code: hashlib.sha256((app.secret_key + "|" + email + "|" + code).encode()).hexdigest()

    @app.route("/request-access/otp", methods=["POST"])
    def otp_send():
        email = request.form.get("email", "").strip().lower()
        if not EMAIL_RE.match(email): return jsonify(ok=False, msg="Enter a valid email address."), 400
        if db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return jsonify(ok=False, msg="This email is already registered. Please sign in."), 409
        now = time.time(); r = db().execute("SELECT * FROM email_otps WHERE email=?", (email,)).fetchone()
        sends, win = (r["sends"] or 0, r["window_start"] or 0) if r else (0, 0)
        if r and now - (r["sent_at"] or 0) < 30: return jsonify(ok=False, msg="Please wait 30 seconds before asking for a new code."), 429
        if now - win > 3600: sends, win = 0, now
        if sends >= 5: return jsonify(ok=False, msg="Too many codes requested. Please try again in an hour."), 429
        code = "%06d" % secrets.randbelow(1000000)
        db().execute("INSERT INTO email_otps(email,code_hash,expires,attempts,verified,sent_at,sends,window_start) VALUES(?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,expires=excluded.expires,attempts=0,verified=0,sent_at=excluded.sent_at,sends=excluded.sends,window_start=excluded.window_start",
                     (email, otp_hash(email, code), now + 600, 0, 0, now, sends + 1, win))
        db().commit()
        sent = mailer.send(email, "Your Tuneflix verification code",
            mailer.wrap("Verify your email", "Your verification code is <b style='font-size:26px;letter-spacing:6px'>%s</b><br>It is valid for 10 minutes." % code))
        if not sent: print("[EMAIL OTP - mail not configured] %s -> %s" % (email, code), flush=True)
        return jsonify(ok=True, msg="We have sent a 6-digit verification code to %s. Please check your inbox and spam folder." % email)

    @app.route("/request-access/verify", methods=["POST"])
    def otp_verify():
        email = request.form.get("email", "").strip().lower(); code = re.sub(r"\D", "", request.form.get("code", ""))
        r = db().execute("SELECT * FROM email_otps WHERE email=?", (email,)).fetchone()
        if not r or r["expires"] < time.time(): return jsonify(ok=False, msg="This code has expired. Please click Regenerate Code."), 400
        if (r["attempts"] or 0) >= 5: return jsonify(ok=False, msg="Too many wrong attempts. Please click Regenerate Code."), 429
        if not hmac.compare_digest(r["code_hash"] or "", otp_hash(email, code)):
            db().execute("UPDATE email_otps SET attempts=attempts+1 WHERE email=?", (email,)); db().commit()
            return jsonify(ok=False, msg="That code is not correct. Please try again."), 400
        db().execute("UPDATE email_otps SET verified=1, expires=? WHERE email=?", (time.time() + 1800, email)); db().commit()
        return jsonify(ok=True, msg="Your email verification is successful. Please click Submit to complete your registration.")

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot():
        if request.method == "POST":
            u = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
            if u:
                link = make_link(u["id"])
                sent = mailer.send(u["email"], "Reset your Tuneflix password",
                    mailer.wrap("Reset your password", "We received a request to reset your password. This link is valid for 1 hour.", "Reset password", link))
                if not sent: print("[RESET LINK - mail not configured] %s -> %s" % (u["email"], link), flush=True)
            flash("If this email is registered, a password reset link has been sent. Please check your inbox and spam folder.", "ok")
            return redirect("/login")
        return render_template("forgot.html")

    @app.route("/reset/<token>", methods=["GET", "POST"])
    def reset(token):
        r = db().execute("SELECT * FROM resets WHERE token_hash=? AND used=0 AND expires>?", (sha(token), time.time())).fetchone()
        if not r:
            flash("This reset link is invalid or has expired. Please request a new one.", "err"); return redirect("/forgot")
        if request.method == "POST":
            p = request.form["password"]
            if len(p) < 6 or p != request.form["confirm"]:
                flash("Passwords must match and be at least 6 characters.", "err"); return redirect(request.path)
            db().execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(p), r["user_id"]))
            db().execute("UPDATE resets SET used=1 WHERE id=?", (r["id"],)); db().commit()
            session.clear(); flash("Password changed successfully. Please sign in.", "ok"); return redirect("/login")
        return render_template("reset.html")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            u = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
            if u and u["is_admin"] and check_password_hash(u["password"], request.form["password"]):
                session.clear(); session["uid"] = u["id"]; session["welcome"] = 1; return redirect("/admin")
            flash("Wrong admin email or password.", "err"); return redirect("/admin/login")
        return render_template("admin_login.html")

    @app.route("/admin/resetlink/<int:i>", methods=["POST"])
    @need(admin=True)
    def admin_resetlink(u, i):
        t = db().execute("SELECT email FROM users WHERE id=?", (i,)).fetchone()
        if t: flash("Reset link for %s (valid 1 hour): %s" % (t["email"], make_link(i)), "ok")
        return redirect("/admin")

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def err(e):
        code = getattr(e, "code", 500)
        msg = {403: "You do not have access to this page.", 404: "Page not found."}.get(code, "Something went wrong on our side. Please try again.")
        return render_template("err.html", code=code, msg=msg), code
