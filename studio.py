import csv, io, os, re, secrets
import mailer
from datetime import date
from flask import render_template, request, redirect, flash, abort, session, Response, send_from_directory
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash

SERVICES = {
 "youtube-cms": ("YouTube CMS", "▶", "YouTube channel URL", "Monthly views / notes", "Link your channel to our CMS network. Channels earning US$5K+ a month are eligible."),
 "change-requests": ("Change Requests", "✎", "Release title / UPC", "What should change?", "Ask us to edit metadata, artwork or audio, or to take down a live release."),
 "yt-claim-remove": ("YT Claim Remove", "⛔", "YouTube video URL", "Why should the claim be removed?", "Remove wrong Content ID claims from your videos."),
 "oac-spotify-tick": ("OAC & Spotify Tick", "✔", "Artist profile URL", "Notes", "Get your Official Artist Channel and the Spotify verified tick."),
 "ugc-claims": ("UGC Claims", "⚖", "Video URL", "Details", "Claim user-generated videos that use your music."),
 "channel-whitelist": ("Channel Whitelist", "🛡", "YouTube channel URL", "Notes", "Whitelist your channels so they never receive claims."),
 "profile-linking": ("Profile Linking", "🔗", "Artist profile URL", "Release to link", "Link your releases to the right artist profile on every store."),
 "distribute-lyrics": ("Distribute Lyrics", "♪", "Release / track title", "Paste the lyrics", "Send lyrics to Spotify and Apple Music."),
 "playlist-pitchment": ("Playlist Pitchment", "☰", "Release title", "Pitch / target playlists", "Pitch your release for editorial playlist consideration."),
}
KINDS = {"artists": ("artist", "Artists", "Artist name", "Spotify / Apple Music link"),
         "labels": ("label", "Labels", "Label name", "Website / notes"),
         "sub-users": ("subuser", "Sub-Users", "Member name", "Email")}

PAGES = {
 "for-artists": dict(nav="Artists", eyebrow="For independent artists", title="Release your music. Get paid for it.",
   lead="Distribution, publishing administration, royalty reporting and rights management for artists who release their own music.",
   cards=[("globe","Distribution","Release once and reach 200+ stores. Live within 48 hours, priority releases in under 24."),
          ("catalog","Publishing administration","Register your works with PROs worldwide and collect the publisher's share."),
          ("finance","Royalties & payouts","See what every stream earns, per store and per track, and withdraw from your wallet."),
          ("rights-manager","Rights protection","Stop re-uploads of your music and videos on YouTube and Facebook."),
          ("analytics","Analytics","Track your catalogue and release performance in one dashboard."),
          ("presave","Pre-save links","Build a shareable smart link for every release in one click.")],
   steps=[("Register","Create your free artist account in a minute."),("Upload","Add your audio, artwork and release details."),("Go live","We review and deliver to stores. You track it in your Studio.")]),
 "for-labels": dict(nav="Labels", eyebrow="For labels & catalogue owners", title="Run your whole catalogue from one place.",
   lead="Deliver, administer, report on and protect an entire catalogue, with an API for labels that run their own systems.",
   cards=[("catalog","Catalogue delivery","Manage every release, artist and label name from a single workspace."),
          ("sub-users","Team access","Add sub-users so your team can work without sharing your login."),
          ("finance","Royalty splits","Record splits per release and keep every payout transparent."),
          ("rights-manager","Rights Manager","OAC and Spotify tick, UGC claims, channel whitelist and profile linking."),
          ("youtube-cms","YouTube CMS","Link your channels to our CMS network for monetisation and protection."),
          ("developers","Distribution API","Pull your catalogue data into your own systems with a personal API key.")],
   steps=[("Register","Create your label account."),("Add your artists","Set up artists, labels and team members."),("Deliver","Upload releases and follow their status live.")]),
 "services": dict(nav="Services", eyebrow="The lineup", title="Pick what your music needs.",
   lead="Six services, one platform. Use one or use them all.",
   cards=[("globe","Distribution","Release once. Reach 200+ stores, with YouTube Music recordings registered for Content ID."),
          ("catalog","Publishing administration","Your songs earn twice. We register works with PROs and collect the publisher's share."),
          ("finance","Royalty reporting & payouts","Break earnings down per store and per track, then withdraw from your wallet."),
          ("rights-manager","Rights management","Protect music and videos on YouTube and Facebook from theft and re-uploads."),
          ("developers","Distribution API","Create and track releases from your own systems with your API key."),
          ("youtube-cms","Channel linking (CMS)","Link your YouTube channel to our CMS network. Channels earning US$5K+ a month are eligible.")]),
 "developers": dict(nav="API", eyebrow="Tuneflix API", title="Build on Tuneflix.",
   lead="Every account gets a personal API key. Use it to read your catalogue from your own tools.",
   code="curl -H \"Authorization: Bearer YOUR_API_KEY\" \\\n  https://YOUR-DOMAIN/api/v1/releases\n\n{ \"releases\": [ { \"id\": 1, \"title\": \"Song\", \"artist\": \"Artist\", \"status\": \"live\" } ] }",
   cards=[("developers","Simple REST + JSON","Bearer-token authentication and clean JSON responses."),
          ("settings","Your key, your control","Find and regenerate your key any time in Studio, My Settings."),
          ("analytics","Your catalogue data","Titles, artists, genres, dates and live status for every release.")]),
 "guides": dict(nav="Guides", eyebrow="Guides & FAQ", title="Questions before you register?",
   lead="Straight answers about how Tuneflix works.",
   faq=[("What is Tuneflix?","Music infrastructure for independent artists, labels and businesses: distribution to 200+ stores, publishing, royalties, rights and an API."),
        ("Who can register?","Independent artists, labels, catalogue owners and businesses. Registration is instant and free."),
        ("How much does it cost?","There is no upfront fee to join and no separate charge for API access."),
        ("Do you accept AI-generated music?","Yes. Each track goes through the same review and store checks as every other release."),
        ("Who owns my music?","You do. Ownership of your masters and compositions stays with you and the rights holders you name."),
        ("How fast does my release go live?","Within 48 hours at most on eligible stores; priority releases in under 24 hours."),
        ("Do I get API access?","Yes. Every account gets a personal API key in Studio, My Settings.")]),
}

# ---------- Release Music wizard: Release Music > Release Info > Track Info > Upload Track > Store ----------
STORES = [("gaana", "Gaana", "#e72c30"), ("jiosaavn", "JioSaavn", "#2bc5b4"), ("ytmusic", "YouTube Music", "#ff0000"), ("spotify", "Spotify", "#1db954"),
          ("tiktok", "TikTok", "#000000"), ("youtube", "YouTube (Content ID)", "#ff0000"), ("hungama", "Hungama Play", "#6a2fc9"), ("apple", "Apple Music", "#fa243c"),
          ("amazon", "Amazon Music", "#00a8e1"), ("instagram", "Instagram / Facebook", "#c13584"), ("resso", "Resso", "#f4366b"), ("wynk", "Wynk Music", "#e8223c"),
          ("deezer", "Deezer", "#a238ff"), ("tidal", "Tidal", "#111111"), ("soundcloud", "SoundCloud", "#ff5500"), ("snapchat", "Snapchat", "#d9b800")]
STORE_IDS = [x[0] for x in STORES]
GENRES = ["Bollywood", "Pop", "Hip-Hop / Rap", "Indie / Alternative", "Rock", "Electronic / Dance", "Folk", "Devotional / Spiritual", "Classical", "Ghazal / Sufi", "Regional",
          "Lo-Fi", "R&B / Soul", "Jazz", "Reggae", "Country", "Children's", "Instrumental", "Other"]
LANGS = ["Hindi", "English", "Punjabi", "Bhojpuri", "Haryanvi", "Rajasthani", "Gujarati", "Marathi", "Bengali", "Odia", "Assamese", "Tamil", "Telugu", "Kannada", "Malayalam",
         "Urdu", "Nepali", "Maithili", "Sanskrit", "Other", "No linguistic content (instrumental)"]
PRIMARY_TYPES = ["Music", "Spoken word"]
SECONDARY_TYPES = ["Original", "Cover", "Remix", "Karaoke", "Medley", "Acapella"]
ADVISORY = ["Not explicit", "Explicit", "Cleaned / radio edit"]
YESNO = ["No", "Yes"]

def setup(app, db, need, save, IMG, AUDIO, UPLOADS):
    ST = {"submitted": "IN REVIEW", "reviewing": "IN REVIEW", "live": "DELIVERED", "rejected": "REJECTED"}
    app.jinja_env.filters["lab"] = lambda s: ST.get(s, str(s).upper())
    ICONS = os.path.join(app.root_path, "static", "icons")
    def ic(name, v="", cls=""):
        n = name + ("-" + v if v else "")
        for f in (n + ".png", name + ".png", n + ".svg"):
            p = os.path.join(ICONS, f)
            if os.path.exists(p):
                return Markup('<img class="ic %s" src="/static/icons/%s?v=%d" alt="" loading="lazy">' % (cls, f, int(os.path.getmtime(p))))
        return Markup("")
    app.jinja_env.globals["ic"] = ic
    for slug_, p_ in PAGES.items():
        app.add_url_rule("/" + slug_, "page_" + slug_, (lambda p=p_: render_template("info.html", p=p)))
    csrf = app.jinja_env.globals["csrf"]
    app.jinja_env.globals["tk"] = lambda: Markup('<input type="hidden" name="csrf" value="%s">' % csrf())

    def T(t, h, ic): return dict(t=t, h=h, ic=ic)
    def svc(s): return T(SERVICES[s][0], "/service/" + s, s)
    NAV = [("Console", [T("Dashboard", "/studio", "dashboard"), T("Analytics", "/analytics", "analytics"),
            dict(t="Catalog", ic="catalog", sub=[("All Releases", "/catalog"), ("Release Music", "/catalog/new")]),
            svc("youtube-cms"), svc("change-requests"), T("Labels", "/labels", "labels")]),
           ("Artists & Rights", [T("Artists", "/artists", "artists"), T("Sub-Users", "/sub-users", "sub-users"), svc("yt-claim-remove"),
            dict(t="Rights Manager", ic="rights-manager", sub=[(SERVICES[s][0], "/service/" + s) for s in
                 ("oac-spotify-tick", "ugc-claims", "channel-whitelist", "profile-linking", "distribute-lyrics", "playlist-pitchment")])]),
           ("Premium Tools", [dict(t="Audio Converter", s="DSP & Master Formats", h="/tools/converter", ic="converter", g=1, new=1),
            dict(t="Audio Extractor", s="Extract Audio", h="/tools/extractor", ic="extractor", g=2),
            dict(t="Pre-Save Builder", s="Smart Pre-Save Links", h="/tools/presave", ic="presave", g=3),
            dict(t="Pitch Writer", s="Release Pitch Generator", h="/tools/pitch", ic="pitch", g=4)]),
           ("System & Reports", [dict(t="Finance & Reports", ic="finance", sub=[("My Wallet", "/wallet"), ("Royalty Splits", "/splits"), ("Reports", "/reports")])]),
           ("Account", [T("My Settings", "/settings", "settings")])]

    @app.context_processor
    def shell():
        uid = session.get("uid")
        def notes():
            return db().execute("SELECT 'Release '||title||': '||status AS t, created FROM releases WHERE user_id=? UNION ALL "
                                "SELECT kind||' request: '||status, created FROM reqs WHERE user_id=? ORDER BY created DESC LIMIT 5", (uid, uid)).fetchall()
        social = {k: os.environ.get(k.upper() + "_URL", "#") for k in ("instagram", "youtube", "x", "linkedin")}
        return dict(NAV=NAV, notes=notes, social=social, welcome=lambda: session.pop("welcome", None),
                    welcome_text=os.environ.get("WELCOME_TEXT", "Great to see you again. Let's get your music out to the world."), today=date.today().strftime("%b %d, %Y").upper(),
                    asset_a=int(os.path.getmtime(os.path.join(app.root_path, "static", "app.css"))))

    @app.errorhandler(400)
    @app.errorhandler(413)
    def bad(e):
        flash("File too large (max 200 MB)." if e.code == 413 else "Please try again: " + str(e.description), "err")
        return redirect(request.referrer or "/studio")

    def one(sql, *a): return db().execute(sql, a).fetchone()[0]
    def rows(sql, *a): return db().execute(sql, a).fetchall()
    def balance(uid): return one("SELECT COALESCE(SUM(amount),0) FROM wallet WHERE user_id=?", uid)
    def items(u, kind, approved_only=False):
        sql = "SELECT * FROM items WHERE user_id=? AND kind=?"
        if approved_only: sql += " AND status='approved'"
        return rows(sql + " ORDER BY id DESC", u["id"], kind)
    def link(s):
        s = (s or "").strip(); return s if re.match(r"https?://", s) else ""
    def num(s):
        try: return round(float(s), 2)
        except (TypeError, ValueError): return 0

    @app.route("/studio")
    @need()
    def studio(u):
        uid = u["id"]
        return render_template("dash.html", u=u, total=one("SELECT COUNT(*) FROM releases WHERE user_id=?", uid),
            live=one("SELECT COUNT(*) FROM releases WHERE user_id=? AND status='live'", uid),
            review=one("SELECT COUNT(*) FROM releases WHERE user_id=? AND status IN ('submitted','reviewing')", uid),
            pend=one("SELECT COUNT(*) FROM reqs WHERE user_id=? AND status='pending'", uid), bal=balance(uid),
            recent=rows("SELECT * FROM releases WHERE user_id=? ORDER BY id DESC LIMIT 6", uid))

    @app.route("/catalog")
    @need()
    def catalog(u):
        q = request.args.get("q", "").strip(); st = request.args.get("status", "")
        sql = "SELECT * FROM releases WHERE user_id=?"; a = [u["id"]]
        if q: sql += " AND (title LIKE ? OR artist LIKE ?)"; a += ["%" + q + "%"] * 2
        if st == "review": sql += " AND status IN ('submitted','reviewing')"
        elif st in ("live", "rejected"): sql += " AND status=?"; a.append(st)
        return render_template("catalog.html", u=u, rows=db().execute(sql + " ORDER BY id DESC", a).fetchall(), q=q, st=st)

    def wiz_ctx(u, v=None):
        return dict(u=u, v=v or {}, artists=items(u, "artist"), labels=items(u, "label", approved_only=True), stores=STORES, genres=GENRES, langs=LANGS,
                    ptypes=PRIMARY_TYPES, stypes=SECONDARY_TYPES, advisory=ADVISORY, yesno=YESNO, chosen=(v or {}).get("_stores") or STORE_IDS)

    @app.route("/catalog/new", methods=["GET", "POST"])
    @app.route("/release-music", methods=["GET", "POST"])
    @need()
    def new_release(u):
        if request.method != "POST": return render_template("newrel.html", **wiz_ctx(u))
        f = request.form; v = {k: f.get(k, "").strip() for k in f.keys()}; v["_stores"] = [x for x in f.getlist("stores") if x in STORE_IDS]
        def back(msg, tab=0):
            flash(msg, "err"); return render_template("newrel.html", start=tab, **wiz_ctx(u, v))
        req = [("title", "Release title", 0), ("artist", "Primary artist", 0), ("genre", "Genre", 1), ("language", "Release language", 1), ("release_date", "Release date", 1),
               ("p_line", "℗ line", 1), ("c_line", "© line", 1), ("track_title", "Track title", 2), ("primary_type", "Primary track type", 2), ("secondary_type", "Secondary track type", 2),
               ("instrumental", "Instrumental", 2), ("key_track", "Key track", 2), ("publisher", "Music publisher", 2), ("track_language", "Track language", 2),
               ("advisory", "Parental advisory", 2), ("music_director", "Music director", 2), ("lyricist", "Lyricist", 2), ("composer", "Composer", 2)]
        for k, label, tab in req:
            if not v.get(k): return back("%s is required." % label, tab)
        if v["instrumental"] not in YESNO or v["key_track"] not in YESNO: return back("Please choose Yes or No for the track questions.", 2)
        try: date.fromisoformat(v["release_date"])
        except ValueError: return back("Please choose a valid release date.", 1)
        if v.get("original_date"):
            try: date.fromisoformat(v["original_date"])
            except ValueError: return back("Please choose a valid original release date.", 1)
        if v.get("upc") and not re.match(r"^\d{12,13}$", v["upc"]): return back("UPC must be 12 or 13 digits (or leave it blank).", 1)
        if v.get("isrc") and not re.match(r"^[A-Za-z]{2}-?[A-Za-z0-9]{3}-?\d{2}-?\d{5}$", v["isrc"]): return back("ISRC looks wrong. Example: INA012300001 (or leave it blank).", 2)
        if v.get("preview_start") and not v["preview_start"].isdigit(): return back("Preview start must be a number of seconds.", 3)
        if not v["_stores"]: return back("Select at least one store.", 4)
        cover, audio = request.files.get("cover"), request.files.get("audio")
        if not cover or not cover.filename: return back("Cover art is required (JPG or PNG).", 0)
        if not audio or not audio.filename: return back("Please upload your audio file.", 3)
        cover_n = save(cover, IMG); audio_n = save(audio, AUDIO)
        db().execute("""INSERT INTO releases(user_id,title,artist,label,genre,language,release_date,cover,audio,rtype,version,featuring,subgenre,original_date,upc,p_line,c_line,description,
              track_title,primary_type,secondary_type,instrumental,key_track,publisher,track_language,advisory,film_director,music_director,lyricist,composer,producer,isrc,lyrics,preview_start,stores)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (u["id"], v["title"], v["artist"], v.get("label"), v["genre"], v["language"], v["release_date"], cover_n, audio_n, "Single", v.get("version"), v.get("featuring"),
             v.get("subgenre"), v.get("original_date"), v.get("upc"), v["p_line"], v["c_line"], v.get("description"), v["track_title"], v["primary_type"], v["secondary_type"],
             v["instrumental"], v["key_track"], v["publisher"], v["track_language"], v["advisory"], v.get("film_director"), v["music_director"], v["lyricist"], v["composer"],
             v.get("producer"), v.get("isrc"), v.get("lyrics"), v.get("preview_start"), ",".join(v["_stores"])))
        db().commit(); flash("Release submitted for review. We will deliver it to your selected stores once approved.", "ok"); return redirect("/catalog")

    @app.route("/release/<int:i>")
    @need()
    def release(u, i):
        r = one_row = db().execute("SELECT * FROM releases WHERE id=? AND (user_id=? OR ?)", (i, u["id"], u["is_admin"])).fetchone() or abort(404)
        names = {k: n for k, n, _ in STORES}
        return render_template("release.html", u=u, r=r, store_names=[names[x] for x in (r["stores"] or "").split(",") if x in names])

    @app.route("/<any('artists','labels','sub-users'):k>", methods=["GET", "POST"])
    @need()
    def items_page(u, k):
        kind, title, l1, l2 = KINDS[k]
        if request.method == "POST":
            n = request.form["name"].strip()
            if n:
                if kind == "label":
                    db().execute("INSERT INTO items(user_id,kind,name,detail,status) VALUES(?,?,?,?, 'pending')", (u["id"], kind, n, request.form.get("detail", "").strip()))
                    db().commit(); flash("Label submitted for admin approval.", "ok")
                else:
                    db().execute("INSERT INTO items(user_id,kind,name,detail) VALUES(?,?,?,?)", (u["id"], kind, n, request.form.get("detail", "").strip()))
                    db().commit(); flash(title[:-1] + " added.", "ok")
            return redirect(request.path)
        return render_template("items.html", u=u, rows=items(u, kind), title=title, l1=l1, l2=l2)

    @app.route("/del/<t>/<int:i>", methods=["POST"])
    @need()
    def delete(u, t, i):
        if t not in ("items", "splits", "presaves"): abort(404)
        db().execute("DELETE FROM %s WHERE id=? AND user_id=?" % t, (i, u["id"])); db().commit()
        flash("Deleted.", "ok"); return redirect(request.referrer or "/studio")

    @app.route("/service/<slug>", methods=["GET", "POST"])
    @need()
    def service(u, slug):
        s = SERVICES.get(slug) or abort(404)
        if request.method == "POST":
            db().execute("INSERT INTO reqs(user_id,kind,subject,detail) VALUES(?,?,?,?)", (u["id"], slug, request.form["subject"].strip(), request.form.get("detail", "").strip()))
            db().commit(); flash("Request submitted. Track its status below.", "ok"); return redirect(request.path)
        return render_template("service.html", u=u, s=s, slug=slug, pre=request.args.get("release", ""),
            rows=rows("SELECT * FROM reqs WHERE user_id=? AND kind=? ORDER BY id DESC", u["id"], slug))

    @app.route("/wallet", methods=["GET", "POST"])
    @need()
    def wallet(u):
        if request.method == "POST":
            amt = num(request.form.get("amount"))
            if amt <= 0 or amt > balance(u["id"]): flash("Enter a valid amount within your balance.", "err")
            else:
                db().execute("INSERT INTO wallet(user_id,amount,note) VALUES(?,?,?)", (u["id"], -amt, "Withdrawal requested"))
                db().execute("INSERT INTO reqs(user_id,kind,subject,detail) VALUES(?,?,?,?)", (u["id"], "withdraw", "Withdrawal Rs %.2f" % amt, str(amt)))
                db().commit(); flash("Withdrawal requested.", "ok")
            return redirect("/wallet")
        return render_template("wallet.html", u=u, bal=balance(u["id"]),
            rows=rows("SELECT * FROM wallet WHERE user_id=? ORDER BY id DESC LIMIT 100", u["id"]),
            wd=rows("SELECT * FROM reqs WHERE user_id=? AND kind='withdraw' ORDER BY id DESC LIMIT 20", u["id"]))

    @app.route("/splits", methods=["GET", "POST"])
    @need()
    def splits(u):
        if request.method == "POST":
            f = request.form; rid = f.get("release_id"); p = num(f.get("pct"))
            ok = rows("SELECT id FROM releases WHERE id=? AND user_id=?", rid, u["id"])
            if not ok or not f["name"].strip() or p <= 0 or one("SELECT COALESCE(SUM(pct),0) FROM splits WHERE release_id=?", rid) + p > 100:
                flash("Invalid split. The total for a release cannot exceed 100%.", "err")
            else:
                db().execute("INSERT INTO splits(user_id,release_id,name,pct) VALUES(?,?,?,?)", (u["id"], rid, f["name"].strip(), p)); db().commit(); flash("Split added.", "ok")
            return redirect("/splits")
        return render_template("splits.html", u=u, rels=rows("SELECT id,title FROM releases WHERE user_id=?", u["id"]),
            rows=rows("SELECT s.*,r.title FROM splits s JOIN releases r ON r.id=s.release_id WHERE s.user_id=? ORDER BY s.release_id,s.id", u["id"]))

    @app.route("/reports")
    @need()
    def reports(u):
        return render_template("reports.html", u=u, bal=balance(u["id"]), rows=rows("SELECT * FROM releases WHERE user_id=? ORDER BY id DESC", u["id"]),
            earned=one("SELECT COALESCE(SUM(amount),0) FROM wallet WHERE user_id=? AND amount>0", u["id"]))

    @app.route("/reports.csv")
    @need()
    def reports_csv(u):
        k = request.args.get("k", "releases"); out = io.StringIO(); w = csv.writer(out)
        if k == "wallet":
            w.writerow(["date", "note", "amount"])
            for r in rows("SELECT * FROM wallet WHERE user_id=? ORDER BY id", u["id"]): w.writerow([r["created"], r["note"], r["amount"]])
        else:
            k = "releases"; w.writerow(["title", "artist", "genre", "release_date", "status"])
            for r in rows("SELECT * FROM releases WHERE user_id=? ORDER BY id", u["id"]): w.writerow([r["title"], r["artist"], r["genre"], r["release_date"], r["status"]])
        return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=%s.csv" % k})

    @app.route("/analytics")
    @need()
    def analytics(u):
        uid = u["id"]
        return render_template("analytics.html", u=u,
            by=[(ST.get(r[0], r[0]), r[1]) for r in rows("SELECT status,COUNT(*) FROM releases WHERE user_id=? GROUP BY status", uid)],
            mon=rows("SELECT substr(created,1,7),COUNT(*) FROM releases WHERE user_id=? GROUP BY 1 ORDER BY 1 DESC LIMIT 6", uid),
            gen=rows("SELECT COALESCE(NULLIF(genre,''),'Unspecified'),COUNT(*) FROM releases WHERE user_id=? GROUP BY 1 ORDER BY 2 DESC LIMIT 6", uid),
            reqs=one("SELECT COUNT(*) FROM reqs WHERE user_id=?", uid))

    @app.route("/settings", methods=["GET", "POST"])
    @need()
    def settings(u):
        if request.method == "POST":
            f = request.form; a = f.get("action"); d = db()
            if a == "profile":
                d.execute("UPDATE users SET name=?,avatar=? WHERE id=?", (f["name"].strip() or u["name"], save(request.files.get("avatar"), IMG) or u["avatar"], u["id"])); flash("Profile updated.", "ok")
            elif a == "password":
                if not check_password_hash(u["password"], f["old"]) or len(f["new"]) < 6: flash("Current password is wrong or the new one is too short (min 6).", "err")
                else: d.execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(f["new"]), u["id"])); flash("Password changed.", "ok")
            elif a == "key":
                d.execute("UPDATE users SET api_key=? WHERE id=?", ("tf_" + secrets.token_urlsafe(24), u["id"])); flash("New API key generated.", "ok")
            d.commit(); return redirect("/settings")
        return render_template("settings.html", u=u)

    @app.route("/tools/<any(converter,extractor):m>")
    @need()
    def tool(u, m): return render_template("tool.html", u=u, m=m)

    @app.route("/tools/pitch")
    @need()
    def pitch(u): return render_template("pitch.html", u=u)

    @app.route("/tools/presave", methods=["GET", "POST"])
    @need()
    def presave(u):
        if request.method == "POST":
            f = request.form
            if not rows("SELECT id FROM releases WHERE id=? AND user_id=?", f.get("release_id"), u["id"]): flash("Choose a release first.", "err")
            else:
                slug = re.sub(r"[^a-z0-9]", "", secrets.token_urlsafe(8).lower())[:7]
                db().execute("INSERT INTO presaves(user_id,release_id,slug,spotify,apple,youtube,drop_date) VALUES(?,?,?,?,?,?,?)",
                    (u["id"], f["release_id"], slug, link(f.get("spotify")), link(f.get("apple")), link(f.get("youtube")), f.get("drop_date")))
                db().commit(); flash("Smart link created.", "ok")
            return redirect("/tools/presave")
        return render_template("presave.html", u=u, rels=rows("SELECT id,title FROM releases WHERE user_id=?", u["id"]),
            rows=rows("SELECT p.*,r.title FROM presaves p JOIN releases r ON r.id=p.release_id WHERE p.user_id=? ORDER BY p.id DESC", u["id"]))

    def pub(slug): return db().execute("SELECT p.*,r.title,r.artist,r.cover FROM presaves p JOIN releases r ON r.id=p.release_id WHERE p.slug=?", (slug,)).fetchone() or abort(404)

    @app.route("/s/<slug>")
    def public_presave(slug): return render_template("presave_public.html", p=pub(slug))

    @app.route("/s/<slug>/cover")
    def public_cover(slug):
        p = pub(slug)
        if not p["cover"]: abort(404)
        return send_from_directory(UPLOADS, p["cover"])

    @app.route("/admin")
    @need(admin=True)
    def admin(u):
        return render_template("admin.html", u=u, users=rows("SELECT * FROM users ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, id DESC"),
            rels=rows("SELECT r.*,u.email FROM releases r JOIN users u ON u.id=r.user_id ORDER BY r.id DESC"),
            reqs=rows("SELECT q.*,u.email FROM reqs q JOIN users u ON u.id=q.user_id ORDER BY q.id DESC LIMIT 100"),
            labels=rows("SELECT i.*,u.email FROM items i JOIN users u ON u.id=i.user_id WHERE i.kind='label' ORDER BY CASE i.status WHEN 'pending' THEN 0 ELSE 1 END, i.id DESC"))

    @app.route("/admin/credit", methods=["POST"])
    @need(admin=True)
    def admin_credit(u):
        f = request.form; t = rows("SELECT id FROM users WHERE email=?", f["email"].strip().lower()); a = num(f.get("amount"))
        if not t or not a: flash("User not found or amount invalid.", "err")
        else: db().execute("INSERT INTO wallet(user_id,amount,note) VALUES(?,?,?)", (t[0]["id"], a, f.get("note") or "Royalty credit")); db().commit(); flash("Wallet updated.", "ok")
        return redirect("/admin")

    @app.route("/admin/<what>/<int:i>", methods=["POST"])
    @need(admin=True)
    def admin_set(u, what, i):
        t = {"user": "users", "release": "releases", "req": "reqs", "label": "items"}.get(what) or abort(404); s = request.form["status"]
        if s not in ("approved", "rejected", "pending", "submitted", "reviewing", "live", "in-progress", "completed"): abort(400)
        if what == "label" and not db().execute("SELECT 1 FROM items WHERE id=? AND kind='label'", (i,)).fetchone(): abort(404)
        if what == "user":
            if i == u["id"]: flash("You cannot change your own account.", "err"); return redirect("/admin")
            tu = db().execute("SELECT * FROM users WHERE id=?", (i,)).fetchone()
            if tu and tu["status"] != s and s in ("approved", "rejected"):
                ok = s == "approved"
                mailer.send(tu["email"], "Your Tuneflix account is " + s, mailer.wrap("Account " + s,
                    "Good news! Your account has been approved. You can sign in now." if ok else "Sorry, we could not approve your application. Please contact our team.",
                    "Sign in" if ok else None, request.host_url + "login" if ok else None))
        if what == "req":
            old = db().execute("SELECT * FROM reqs WHERE id=?", (i,)).fetchone()
            if old and old["kind"] == "withdraw" and s == "rejected" and old["status"] != "rejected":
                db().execute("INSERT INTO wallet(user_id,amount,note) VALUES(?,?,?)", (old["user_id"], num(old["detail"]), "Withdrawal refunded"))
        db().execute("UPDATE %s SET status=? WHERE id=?" % t, (s, i)); db().commit(); return redirect("/admin")
