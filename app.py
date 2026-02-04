import os
import sqlite3
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, abort, g, request, Response


app = Flask(__name__)

# --- Simple in-memory posts (your existing posts) ---
POSTS = [
    {
        "slug": "safe-school-transport-checklist",
        "title": "Safe School Transport Checklist for Parents",
        "date": "2026-02-02",
        "read_time": "3 min read",
        "category": "Safety",
        "excerpt": "A quick checklist parents can use when choosing a school shuttle service.",
        "cover": "/static/blog/blog-1.jpg",
        "content_html": """
            <p>Choosing a shuttle isn’t just about price — it’s about consistency, communication, and safety habits.</p>
            <h3>1) Confirm safety basics</h3>
            <ul>
              <li>Seatbelts for every child</li>
              <li>Clear rules: seated, no moving, no loud distractions</li>
              <li>Age-appropriate supervision and behavior expectations</li>
            </ul>
            <h3>2) Ask about driver standards</h3>
            <ul>
              <li>Professional conduct</li>
              <li>Route familiarity and punctuality</li>
              <li>Emergency contact process</li>
            </ul>
            <h3>3) Communication matters</h3>
            <p>WhatsApp updates for delays and confirmations build trust and reduce stress for parents.</p>
        """,
    },
    {
        "slug": "how-monthly-packages-save-time",
        "title": "How Monthly Packages Save Parents Time (and Stress)",
        "date": "2026-02-02",
        "read_time": "4 min read",
        "category": "Parents",
        "excerpt": "Monthly school transport packages simplify routines and reduce daily planning.",
        "cover": "/static/blog/blog-2.jpg",
        "content_html": """
            <p>When your schedule is packed, consistency becomes your biggest advantage.</p>
            <h3>Benefits of monthly packages</h3>
            <ul>
              <li>Stable pickup times and routes</li>
              <li>Less daily coordination</li>
              <li>Clear billing and predictable costs</li>
            </ul>
            <p>It also makes it easier for your child to build a calm routine.</p>
        """,
    },
    {
        "slug": "why-on-time-is-a-system",
        "title": "On-Time Isn’t Luck — It’s a System",
        "date": "2026-02-02",
        "read_time": "3 min read",
        "category": "Operations",
        "excerpt": "A simple breakdown of what makes school transport consistently punctual.",
        "cover": "/static/blog/blog-3.jpg",
        "content_html": """
            <p>On-time performance comes from repeatable processes, not guesswork.</p>
            <h3>What helps punctuality?</h3>
            <ul>
              <li>Route planning + realistic pickup windows</li>
              <li>Good communication when conditions change</li>
              <li>Consistent, disciplined routines</li>
            </ul>
            <p>When parents and drivers share the same routine, everything runs smoother.</p>
        """,
    },
]


# =========================
# Analytics (local, SQLite)
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

DB_PATH = os.path.join(INSTANCE_DIR, "analytics.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL;")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db:
        db.close()


def init_analytics_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            path TEXT NOT NULL,
            method TEXT NOT NULL,
            status INTEGER NOT NULL,
            referrer TEXT,
            ua TEXT,
            ip_hash TEXT
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_visits_ts ON visits(ts)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_visits_path ON visits(path)")
    db.commit()


def _is_trackable(path: str) -> bool:
    if not path:
        return False
    if path.startswith("/static"):
        return False
    if path.startswith("/admin"):
        return False
    return True


@app.after_request
def track_visit(response):
    try:
        init_analytics_db()

        path = request.path or "/"
        if not _is_trackable(path):
            return response

        # Local-first: uses request.remote_addr (behind nginx later we'll use X-Forwarded-For)
        ip = request.headers.get("X-Forwarded-For", "") or request.remote_addr or ""
        ip = ip.split(",")[0].strip()

        salt = os.environ.get("ANALYTICS_SALT", "dev_salt_change_me")
        ip_hash = hashlib.sha256((salt + ip).encode("utf-8")).hexdigest()[:16] if ip else None

        ref = (request.headers.get("Referer") or "")[:300]
        ua = (request.headers.get("User-Agent") or "")[:300]

        db = get_db()
        db.execute(
            "INSERT INTO visits (ts, path, method, status, referrer, ua, ip_hash) VALUES (?,?,?,?,?,?,?)",
            (
                datetime.utcnow().isoformat(timespec="seconds"),
                path,
                request.method,
                response.status_code,
                ref,
                ua,
                ip_hash,
            ),
        )
        db.commit()
    except Exception:
        # Never break the website because analytics failed
        pass

    return response


def require_admin(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        user = os.environ.get("ADMIN_USER", "admin")
        pw = os.environ.get("ADMIN_PASS", "admin123")  # change this for real use

        auth = request.authorization
        if not auth or auth.username != user or auth.password != pw:
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="JoyfullRides Admin"'})
        return f(*args, **kwargs)

    return wrapped


# ===========
# Routes
# ===========
@app.get("/")
def home():
    return render_template("index.html")


@app.get("/blog")
def blog():
    posts = sorted(POSTS, key=lambda p: p["date"], reverse=True)
    return render_template("blog.html", posts=posts)


@app.get("/soe")
def soe_blog_alias():
    posts = sorted(POSTS, key=lambda p: p["date"], reverse=True)
    return render_template("blog.html", posts=posts)


@app.get("/blog/<slug>")
def blog_post(slug: str):
    post = next((p for p in POSTS if p["slug"] == slug), None)
    if not post:
        abort(404)
    return render_template("post.html", post=post)


@app.get("/admin/analytics")
@require_admin
def admin_analytics():
    init_analytics_db()
    db = get_db()

    since_30 = (datetime.utcnow() - timedelta(days=30)).isoformat(timespec="seconds")

    total_views = db.execute("SELECT COUNT(*) c FROM visits WHERE ts >= ?", (since_30,)).fetchone()["c"]
    unique_visitors = db.execute(
        "SELECT COUNT(DISTINCT ip_hash) c FROM visits WHERE ts >= ? AND ip_hash IS NOT NULL",
        (since_30,),
    ).fetchone()["c"]

    top_pages = db.execute(
        """
        SELECT path, COUNT(*) views
        FROM visits
        WHERE ts >= ?
        GROUP BY path
        ORDER BY views DESC
        LIMIT 10
        """,
        (since_30,),
    ).fetchall()

    daily = db.execute(
        """
        SELECT substr(ts, 1, 10) day, COUNT(*) views
        FROM visits
        WHERE ts >= ?
        GROUP BY day
        ORDER BY day
        """,
        (since_30,),
    ).fetchall()

    recent = db.execute(
        """
        SELECT ts, path, status, referrer
        FROM visits
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()

    days = [r["day"] for r in daily]
    counts = [r["views"] for r in daily]

    return render_template(
        "admin_analytics.html",
        total_views=total_views,
        unique_visitors=unique_visitors,
        top_pages=top_pages,
        recent=recent,
        days=days,
        counts=counts,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)