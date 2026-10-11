"""FINOVA — Flask backend (serves the SPA in /static and the JSON API)."""
import json
import os
import re
import secrets
import sqlite3
import time
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from io import BytesIO

import ai
import engine
import narrative

try:  # optional: load .env locally (Render uses dashboard env vars)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE / "instance"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "uploads").mkdir(exist_ok=True)
DB_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "finova.db"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("RENDER") is not None,
                  MAX_CONTENT_LENGTH=6 * 1024 * 1024, PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14)

FAQ = json.loads((BASE / "data" / "faq.json").read_text(encoding="utf-8"))
KB = ai.build_kb(FAQ)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, age INTEGER, gender TEXT,
  country TEXT, province TEXT, phone TEXT, occupation TEXT, created REAL);
CREATE TABLE IF NOT EXISTS finance(user_id INTEGER PRIMARY KEY, data TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, data TEXT, created REAL);
CREATE TABLE IF NOT EXISTS ratings(user_id INTEGER PRIMARY KEY, accuracy INTEGER, groundedness INTEGER, usability INTEGER,
  processing INTEGER, avg REAL, comment TEXT, flagged INTEGER, updated REAL);
CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY, name TEXT, ms REAL, created REAL);
CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, user_id INTEGER, type TEXT, subject TEXT, description TEXT,
  email TEXT, attachment TEXT, created REAL);
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


with sqlite3.connect(DB_PATH) as _c:
    _c.executescript(SCHEMA)


def err(msg, code=400):
    return jsonify({"error": msg}), code


def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("uid"):
            return err("Please log in first.", 401)
        return fn(*a, **k)
    return w


def public_user(r):
    return {k: r[k] for k in ("id", "name", "email", "age", "gender", "country", "province", "phone", "occupation")}


def me():
    return db().execute("SELECT * FROM users WHERE id=?", (session.get("uid"),)).fetchone()


def pw_ok(pw):
    return len(pw) >= 8 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)


def metric(name, ms):
    db().execute("INSERT INTO metrics(name,ms,created) VALUES(?,?,?)", (name, ms, time.time()))
    db().commit()


def load_finance():
    r = db().execute("SELECT data FROM finance WHERE user_id=?", (session["uid"],)).fetchone()
    return json.loads(r["data"]) if r else None


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/api/config")
def config():
    return jsonify({"ai_enabled": ai.configured()})


@app.route("/api/faq")
def faq():
    return jsonify(FAQ)


# ------------------------------------------------------------------- auth
@app.post("/api/register")
def register():
    d = request.get_json(silent=True) or {}
    name, email, pw = str(d.get("name", "")).strip(), str(d.get("email", "")).strip().lower(), str(d.get("password", ""))
    if len(name) < 2:
        return err("Please enter your full name.")
    if not EMAIL_RE.match(email):
        return err("Please enter a valid email address.")
    if not pw_ok(pw):
        return err("Password must be at least 8 characters and include letters and numbers.")
    if pw != d.get("confirm"):
        return err("Passwords do not match.")
    try:
        cur = db().execute("INSERT INTO users(name,email,pw,created) VALUES(?,?,?,?)",
                           (name, email, generate_password_hash(pw), time.time()))
        db().commit()
    except sqlite3.IntegrityError:
        return err("An account with this email already exists.", 409)
    session.clear()
    session.permanent = True
    session["uid"] = cur.lastrowid
    return jsonify({"user": public_user(me())})


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    r = db().execute("SELECT * FROM users WHERE email=?", (str(d.get("email", "")).strip().lower(),)).fetchone()
    if not r or not check_password_hash(r["pw"], str(d.get("password", ""))):
        return err("Incorrect email or password.", 401)
    session.clear()
    session.permanent = True
    session["uid"] = r["id"]
    return jsonify({"user": public_user(r)})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def whoami():
    return jsonify({"user": public_user(me()) if session.get("uid") and me() else None})


@app.post("/api/forgot/verify")
def forgot_verify():
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()
    r = db().execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if not r:
        return err("No account was found for this email.", 404)
    session["reset_uid"], session["reset_exp"] = r["id"], time.time() + 600
    return jsonify({"ok": True})


@app.post("/api/forgot/reset")
def forgot_reset():
    d = request.get_json(silent=True) or {}
    if not session.get("reset_uid") or session.get("reset_exp", 0) < time.time():
        return err("Your verification expired. Please verify your email again.", 403)
    if not pw_ok(str(d.get("password", ""))):
        return err("Password must be at least 8 characters and include letters and numbers.")
    if d.get("password") != d.get("confirm"):
        return err("Passwords do not match.")
    db().execute("UPDATE users SET pw=? WHERE id=?", (generate_password_hash(d["password"]), session["reset_uid"]))
    db().commit()
    session.pop("reset_uid", None)
    return jsonify({"ok": True})


@app.put("/api/profile")
@login_required
def profile():
    d = request.get_json(silent=True) or {}
    name, email = str(d.get("name", "")).strip(), str(d.get("email", "")).strip().lower()
    if len(name) < 2 or not EMAIL_RE.match(email):
        return err("Please enter a valid name and email.")
    try:
        age = int(d["age"]) if str(d.get("age", "")).strip() else None
    except ValueError:
        return err("Age must be a whole number.")
    if age is not None and not 1 <= age <= 120:
        return err("Age must be between 1 and 120.")
    gender = d.get("gender") if d.get("gender") in ("Male", "Female", "Other") else None
    try:
        db().execute("UPDATE users SET name=?,email=?,age=?,gender=?,country=?,province=?,phone=?,occupation=? WHERE id=?",
                     (name, email, age, gender, str(d.get("country", ""))[:80], str(d.get("province", ""))[:80],
                      re.sub(r"[^\d+\s-]", "", str(d.get("phone", "")))[:20], str(d.get("occupation", ""))[:80], session["uid"]))
        db().commit()
    except sqlite3.IntegrityError:
        return err("That email is already used by another account.", 409)
    return jsonify({"user": public_user(me())})


@app.post("/api/password")
@login_required
def change_password():
    d = request.get_json(silent=True) or {}
    if not check_password_hash(me()["pw"], str(d.get("old", ""))):
        return err("Your current password is incorrect.", 403)
    if not pw_ok(str(d.get("new", ""))):
        return err("New password must be at least 8 characters and include letters and numbers.")
    if d.get("new") != d.get("confirm"):
        return err("New passwords do not match.")
    db().execute("UPDATE users SET pw=? WHERE id=?", (generate_password_hash(d["new"]), session["uid"]))
    db().commit()
    return jsonify({"ok": True})


# --------------------------------------------------------------- finance
@app.route("/api/finance", methods=["GET", "PUT"])
@login_required
def finance():
    if request.method == "PUT":
        p = engine.clean_profile(request.get_json(silent=True))
        db().execute("INSERT INTO finance(user_id,data,updated) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                     (session["uid"], json.dumps(p), time.time()))
        db().commit()
        return jsonify({"finance": p})
    return jsonify({"finance": load_finance()})


@app.get("/api/finance/template")
@login_required
def finance_template():
    return send_file(BytesIO(engine.template_xlsx()), as_attachment=True, download_name="finova_input_template.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/finance/import")
@login_required
def finance_import():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".xlsx"):
        return err("Please upload an .xlsx file.")
    try:
        return jsonify(engine.parse_xlsx(f.read()))
    except Exception:
        return err("The file could not be read. Please use the FINOVA Excel template.")


def need_finance():
    f = load_finance()
    if not f or not (f.get("income") or f.get("expenses")):
        return None
    return f


@app.get("/api/analysis")
@login_required
def analysis():
    f = need_finance()
    if not f:
        return err("Please save your financial information first.", 409)
    t = time.perf_counter()
    a = engine.analysis(f)
    ms = (time.perf_counter() - t) * 1000
    metric("analysis_engine", ms)
    a["narrative"], a["source"] = narrative.analysis(a), "rules"
    a["engine_ms"] = ms
    return jsonify(a)


@app.post("/api/whatif")
@login_required
def whatif():
    f = need_finance()
    if not f:
        return err("Please save your financial information first.", 409)
    w = engine.whatif(f, (request.get_json(silent=True) or {}).get("adjustments"))
    w["narrative"] = {"text": narrative.whatif(w, None)}
    return jsonify(w)


@app.post("/api/ai/explain")
@login_required
def ai_explain():
    d = request.get_json(silent=True) or {}
    kind, f = d.get("kind"), need_finance()
    if kind not in ai.KEYS or not f:
        return err("Unsupported request.")
    if kind == "analysis":
        data = engine.analysis(f)
        fb = narrative.analysis(data)
    elif kind == "whatif":
        data = engine.whatif(f, d.get("adjustments"))
        fb = {"text": narrative.whatif(data, None)}
    else:
        data = engine.goals_analyze(f, d.get("goals"), d.get("chosen"), d.get("assumptions"))
        fb = narrative.goals(data) if kind == "goals" else {"text": narrative.secondary(data)}
    out, source, ms = ai.explain(kind, data, fb)
    if source == "gemini":
        metric("ai_generation", ms)
    return jsonify({"content": out, "source": source, "ms": ms})


# ----------------------------------------------------------------- goals
@app.get("/api/goals/defaults")
@login_required
def goal_defaults():
    f = need_finance()
    return jsonify({"goals": engine.default_goals(engine.clean_profile(f))}) if f else err("Please save your financial information first.", 409)


@app.post("/api/goals/analyze")
@login_required
def goals_analyze():
    f = need_finance()
    if not f:
        return err("Please save your financial information first.", 409)
    d = request.get_json(silent=True) or {}
    t = time.perf_counter()
    r = engine.goals_analyze(f, d.get("goals"), d.get("chosen"), d.get("assumptions"))
    metric("goals_engine", (time.perf_counter() - t) * 1000)
    r["narrative"] = narrative.goals(r)
    r["narrative"]["secondary"] = narrative.secondary(r)
    return jsonify(r)


@app.route("/api/plans", methods=["GET", "POST"])
@login_required
def plans():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        name = str(d.get("name", "")).strip()[:60] or "Untitled plan"
        f = need_finance()
        if not f:
            return err("Please save your financial information first.", 409)
        r = engine.goals_analyze(f, d.get("goals"), d.get("chosen"), d.get("assumptions"))
        pl, pa = r["plan_baseline"], r["plan_assumed"]
        summary = {"goal": pl["name"], "target": pl["target"], "years": (pa or pl)["years"],
                   "monthly_save": (pa or pl)["monthly_save"], "annual_return": (pa or pl)["annual_return"],
                   "required_monthly": (pa or pl)["required_monthly"], "completion": (pa or pl)["completion"],
                   "months": (pa or pl)["months_at_rate"], "hypothetical": bool(pa)}
        db().execute("INSERT INTO plans(user_id,name,data,created) VALUES(?,?,?,?)",
                     (session["uid"], name, json.dumps({"goals": d.get("goals"), "chosen": d.get("chosen"),
                                                          "assumptions": d.get("assumptions"), "summary": summary}), time.time()))
        db().commit()
    rows = db().execute("SELECT id,name,data,created FROM plans WHERE user_id=? ORDER BY id DESC", (session["uid"],)).fetchall()
    return jsonify({"plans": [{"id": r["id"], "name": r["name"], **json.loads(r["data"])} for r in rows]})


@app.delete("/api/plans/<int:pid>")
@login_required
def plan_delete(pid):
    db().execute("DELETE FROM plans WHERE id=? AND user_id=?", (pid, session["uid"]))
    db().commit()
    return jsonify({"ok": True})


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/export/report")
@login_required
def export_report():
    f = need_finance()
    if not f:
        return err("Please save your financial information first.", 409)
    return send_file(BytesIO(engine.report_xlsx(f)), as_attachment=True, download_name="finova_financial_report.xlsx", mimetype=XLSX)


@app.post("/api/export/plan")
@login_required
def export_plan():
    f = need_finance()
    if not f:
        return err("Please save your financial information first.", 409)
    d = request.get_json(silent=True) or {}
    return send_file(BytesIO(engine.plan_xlsx(f, d.get("goals"), d.get("chosen"), d.get("assumptions"))),
                     as_attachment=True, download_name="finova_savings_investment_plan.xlsx", mimetype=XLSX)


# ------------------------------------------------------------ evaluation
def summary():
    rows = db().execute("SELECT * FROM ratings").fetchall()
    n = len(rows)
    mine = db().execute("SELECT * FROM ratings WHERE user_id=?", (session.get("uid"),)).fetchone()
    avg = lambda k: round(sum(r[k] for r in rows) / n, 2) if n else None
    return {"count": n, "overall": round(sum(r["avg"] for r in rows) / n, 2) if n else None,
            "criteria": {k: avg(k) for k in ("accuracy", "groundedness", "usability", "processing")},
            "flagged": sum(r["flagged"] for r in rows), "mine": dict(mine) if mine else None}


@app.route("/api/ratings", methods=["GET", "POST"])
@login_required
def ratings():
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        try:
            v = {k: int(d[k]) for k in ("accuracy", "groundedness", "usability", "processing")}
        except (KeyError, ValueError, TypeError):
            return err("Please rate all four criteria.")
        if any(not 1 <= x <= 5 for x in v.values()):
            return err("Ratings must be between 1 and 5 stars.")
        avg = sum(v.values()) / 4
        db().execute("INSERT INTO ratings(user_id,accuracy,groundedness,usability,processing,avg,comment,flagged,updated) VALUES(?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(user_id) DO UPDATE SET accuracy=excluded.accuracy, groundedness=excluded.groundedness, usability=excluded.usability, "
                     "processing=excluded.processing, avg=excluded.avg, comment=excluded.comment, flagged=excluded.flagged, updated=excluded.updated",
                     (session["uid"], v["accuracy"], v["groundedness"], v["usability"], v["processing"], avg,
                      str(d.get("comment", ""))[:1000], 1 if d.get("flagged") else 0, time.time()))
        db().commit()
    return jsonify(summary())


@app.get("/api/eval/dashboard")
@login_required
def eval_dashboard():
    st = engine.self_test()
    # groundedness: narrative figures must come from engine outputs
    sample = {"income": 25e6, "expenses": 12e6, "investments": 50e6, "assets": 120e6, "debt": 80e6, "debt_payment": 3e6,
              "years": 10, "liquidity": "medium", "risk": "medium"}
    a = engine.analysis(sample)
    nar = narrative.analysis(a)
    txt = "\n".join([nar["table"], nar["chart"], nar["guidance"], nar["recommendations"]] + list(nar["scenarios"].values()))
    ok, checked = engine.grounded_rate(txt, a)
    t = time.perf_counter()
    narrative.analysis(a)
    nar_ms = (time.perf_counter() - t) * 1000

    def avg_ms(name):
        r = db().execute("SELECT AVG(ms) m, COUNT(*) c FROM metrics WHERE name=?", (name,)).fetchone()
        return (r["m"], r["c"])
    s = summary()
    eng = avg_ms("analysis_engine")
    ai_ms = avg_ms("ai_generation")
    rows = [
        {"criterion": "Accuracy", "kpi": "Engine outputs vs independently calculated results (cash flow, net worth, 5 scenarios)",
         "target": "≥ 98%", "actual": f"{st['correct'] / st['total'] * 100:.1f}% ({st['correct']}/{st['total']} checks correct)",
         "pass": st["correct"] / st["total"] >= 0.98},
        {"criterion": "Groundedness", "kpi": "Share of money and % figures in AI narrative traceable to Python outputs",
         "target": "≥ 95%", "actual": f"{ok / checked * 100:.1f}% ({ok}/{checked} figures grounded)" if checked else "n/a",
         "pass": bool(checked) and ok / checked >= 0.95},
        {"criterion": "Usability", "kpi": "Average user usability rating (structured survey)", "target": "≥ 4.0 / 5",
         "actual": f"{s['criteria']['usability']:.2f} / 5 ({s['count']} ratings)" if s["count"] else "No ratings yet",
         "pass": bool(s["count"]) and s["criteria"]["usability"] >= 4.0},
        {"criterion": "Processing Time", "kpi": "Calculation engine: 5 scenarios, 30-year monthly simulation", "target": "≤ 1,000 ms",
         "actual": f"{(eng[0] or st['engine_ms']):.0f} ms avg ({eng[1]} live runs; self-test {st['engine_ms']:.0f} ms)", "pass": (eng[0] or st["engine_ms"]) <= 1000},
        {"criterion": "Processing Time", "kpi": "Rule-based narrative generation", "target": "≤ 500 ms", "actual": f"{nar_ms:.1f} ms", "pass": nar_ms <= 500},
        {"criterion": "Processing Time", "kpi": "AI generation latency (Gemini)", "target": "≤ 20,000 ms",
         "actual": f"{ai_ms[0]:.0f} ms avg ({ai_ms[1]} runs)" if ai_ms[1] else ("No AI runs yet" if ai.configured() else "AI key not configured"),
         "pass": None if not ai_ms[1] else ai_ms[0] <= 20000},
    ]
    return jsonify({"rows": rows, "summary": s, "ai_enabled": ai.configured()})


# ---------------------------------------------------------------- support
@app.post("/api/support")
@login_required
def support():
    f, form = request.files.get("attachment"), request.form
    typ = form.get("type", "")
    if typ not in {t["label"] for t in FAQ["support_types"]}:
        return err("Please choose an issue type.")
    subject, desc, email = form.get("subject", "").strip(), form.get("description", "").strip(), form.get("email", "").strip()
    if len(subject) < 3 or len(desc) < 10:
        return err("Please add a subject and a more detailed description.")
    if not EMAIL_RE.match(email):
        return err("Please enter a valid email so we can reply.")
    fname = None
    if f and f.filename:
        ext = Path(f.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            return err("Attachments must be screenshots (png, jpg, gif or webp).")
        fname = f"{int(time.time())}_{secrets.token_hex(4)}{ext}"
        f.save(DATA_DIR / "uploads" / fname)
    cur = db().execute("INSERT INTO tickets(user_id,type,subject,description,email,attachment,created) VALUES(?,?,?,?,?,?,?)",
                       (session["uid"], typ, subject[:150], desc[:4000], email, fname, time.time()))
    db().commit()
    return jsonify({"ok": True, "ticket": f"FIN-{cur.lastrowid:05d}"})


@app.post("/api/chat")
@login_required
def chat():
    d = request.get_json(silent=True) or {}
    msg = str(d.get("message", "")).strip()
    if not msg:
        return err("Please type a question.")
    ctx, f = "", load_finance()
    if f and (f.get("income") or f.get("expenses")):
        a = engine.analysis(f)
        slim = {"profile": a["profile"], "metrics": a["metrics"], "health": a["health"]["items"],
                "scenario_ranking": [{"scenario": s["title"], "net_cash_flow": s["net_cash_flow"], "final_net_worth": s["final_net_worth"],
                                      "assumptions": s["assumptions"]} for s in sorted(a["scenarios"], key=lambda s: s["rank"])],
                "reference_goals": a["goals"]}
        ctx = json.dumps(slim, default=str)
    t = time.perf_counter()
    text, source = ai.chat(msg, d.get("history"), KB, ctx)
    if source == "gemini":
        metric("ai_generation", (time.perf_counter() - t) * 1000)
    return jsonify({"reply": text, "source": source})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
