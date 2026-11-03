import hashlib, os, secrets, time
from flask import render_template, request, redirect, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import mailer

def setup(app, db, need):
    sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
    def base_url():
        return (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or request.host_url).rstrip("/")

    def make_link(uid):
        t = secrets.token_urlsafe(32); d = db()
        d.execute("DELETE FROM resets WHERE user_id=?", (uid,))
        d.execute("INSERT INTO resets(user_id,token_hash,expires) VALUES(?,?,?)", (uid, sha(t), time.time() + 3600)); d.commit()
        return base_url() + "/reset/" + t

    @app.route("/thanks")
    def thanks(): return render_template("thanks.html", company=session.get("reg_type") == "Company")

    @app.route("/forgot", methods=["GET", "POST"])
    def forgot():
        if request.method == "POST":
            u = db().execute("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
            if u:
                link = make_link(u["id"])
                body = ("We received a request to reset your password. This link is valid for 1 hour. "
                        "If the button does not work, open this link: <a href='%s'>%s</a>" % (link, link))
                sent = mailer.send_now(u["email"], "Reset your Tuneflix password",
                    mailer.wrap("Reset your password", body, "Reset password", link))
                if sent:
                    flash("Reset email sent. Check your inbox and spam folder; the link expires in 1 hour.", "ok")
                else:
                    flash("We could not send the reset email right now. Please try again shortly or contact support.", "err")
            else:
                flash("If this email is registered, a password reset link will be sent. Please check your inbox and spam folder.", "ok")
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
