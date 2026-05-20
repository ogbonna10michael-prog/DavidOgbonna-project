"""
CloudVault - Personal Cloud Storage
A mini Google Drive / Dropbox built with FastAPI + SQLite
"""

import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI, Request, Response, Depends, HTTPException,
    UploadFile, File, Form, status
)
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

DB_PATH = BASE_DIR / "cloudvault.db"
SECRET_KEY = secrets.token_hex(32)   # rotates on restart; use env var in prod
SESSION_EXPIRE_HOURS = 24
MAX_FILE_SIZE_MB = 50

app = FastAPI(title="CloudVault")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ── Database ───────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT UNIQUE NOT NULL,
            email     TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            expires_at DATETIME NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS files (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name  TEXT NOT NULL,
            size_bytes   INTEGER NOT NULL,
            mime_type    TEXT,
            uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)

init_db()

# ── Auth helpers ───────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":")
        return hashlib.sha256((salt + password).encode()).hexdigest() == h
    except Exception:
        return False

def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=SESSION_EXPIRE_HOURS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires.isoformat())
    )
    conn.commit()
    return token

def get_current_user(request: Request, conn=Depends(get_db)) -> Optional[sqlite3.Row]:
    token = request.cookies.get("session_token")
    if not token:
        return None
    row = conn.execute(
        "SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, datetime.utcnow().isoformat())
    ).fetchone()
    return row

def require_user(request: Request, conn=Depends(get_db)) -> sqlite3.Row:
    user = get_current_user(request, conn)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user

# ── Utility ────────────────────────────────────────────────────────────────────
def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def file_icon(mime: str) -> str:
    if not mime:
        return "📄"
    if mime.startswith("image/"):  return "🖼️"
    if mime.startswith("video/"):  return "🎬"
    if mime.startswith("audio/"):  return "🎵"
    if "pdf" in mime:              return "📕"
    if "zip" in mime or "tar" in mime or "gzip" in mime: return "🗜️"
    if "spreadsheet" in mime or "excel" in mime:         return "📊"
    if "word" in mime or "document" in mime:             return "📝"
    if "text/" in mime:            return "📃"
    if "json" in mime or "xml" in mime: return "🔧"
    return "📄"

# ── Routes: Pages ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, conn=Depends(get_db)):
    user = get_current_user(request, conn)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    return templates.TemplateResponse("register.html", {"request": request, "error": error})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, conn=Depends(get_db)):
    user = get_current_user(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=303)

    files = conn.execute(
        "SELECT * FROM files WHERE user_id = ? ORDER BY uploaded_at DESC",
        (user["id"],)
    ).fetchall()

    # Enrich files with display helpers
    enriched = []
    for f in files:
        enriched.append({
            "id": f["id"],
            "original_name": f["original_name"],
            "size": human_size(f["size_bytes"]),
            "size_bytes": f["size_bytes"],
            "mime_type": f["mime_type"],
            "icon": file_icon(f["mime_type"]),
            "uploaded_at": f["uploaded_at"][:16].replace("T", " "),
        })

    total_bytes = sum(f["size_bytes"] for f in files)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": dict(user),
        "files": enriched,
        "file_count": len(files),
        "total_size": human_size(total_bytes),
    })

# ── Routes: Auth ───────────────────────────────────────────────────────────────
@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    conn=Depends(get_db)
):
    # Validation
    if len(username) < 3:
        return templates.TemplateResponse("register.html",
            {"request": request, "error": "Username must be at least 3 characters."})
    if len(password) < 8:
        return templates.TemplateResponse("register.html",
            {"request": request, "error": "Password must be at least 8 characters."})
    if "@" not in email:
        return templates.TemplateResponse("register.html",
            {"request": request, "error": "Please enter a valid email address."})

    # Check uniqueness
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ? OR email = ?", (username, email)
    ).fetchone()
    if existing:
        return templates.TemplateResponse("register.html",
            {"request": request, "error": "Username or email already taken."})

    conn.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        (username, email, hash_password(password))
    )
    conn.commit()

    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    token = create_session(conn, user["id"])

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("session_token", token, httponly=True, max_age=SESSION_EXPIRE_HOURS * 3600)
    return response

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    conn=Depends(get_db)
):
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? OR email = ?", (username, username)
    ).fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html",
            {"request": request, "error": "Invalid username or password."})

    token = create_session(conn, user["id"])
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("session_token", token, httponly=True, max_age=SESSION_EXPIRE_HOURS * 3600)
    return response

@app.post("/logout")
async def logout(request: Request, conn=Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session_token")
    return response

# ── Routes: Files ──────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    conn=Depends(get_db)
):
    user = get_current_user(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=303)

    # Read & size-check
    content = await file.read()
    size = len(content)
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if size > max_bytes:
        return RedirectResponse(f"/dashboard?error=File+exceeds+{MAX_FILE_SIZE_MB}MB+limit", status_code=303)

    # Sanitize filename and store with UUID
    original_name = file.filename or "untitled"
    original_name = "".join(c for c in original_name if c.isalnum() or c in "._- ")[:255]
    ext = Path(original_name).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"

    (UPLOAD_DIR / str(user["id"])).mkdir(exist_ok=True)
    dest = UPLOAD_DIR / str(user["id"]) / stored_name
    dest.write_bytes(content)

    conn.execute(
        "INSERT INTO files (user_id, original_name, stored_name, size_bytes, mime_type) "
        "VALUES (?, ?, ?, ?, ?)",
        (user["id"], original_name, stored_name, size, file.content_type)
    )
    conn.commit()
    return RedirectResponse("/dashboard", status_code=303)

@app.get("/download/{file_id}")
async def download_file(file_id: int, request: Request, conn=Depends(get_db)):
    user = get_current_user(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=303)

    f = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user["id"])
    ).fetchone()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    path = UPLOAD_DIR / str(user["id"]) / f["stored_name"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage")

    return FileResponse(
        path,
        filename=f["original_name"],
        media_type=f["mime_type"] or "application/octet-stream"
    )

@app.post("/delete/{file_id}")
async def delete_file(file_id: int, request: Request, conn=Depends(get_db)):
    user = get_current_user(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=303)

    f = conn.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, user["id"])
    ).fetchone()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    # Remove from disk
    path = UPLOAD_DIR / str(user["id"]) / f["stored_name"]
    if path.exists():
        path.unlink()

    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    return RedirectResponse("/dashboard", status_code=303)
