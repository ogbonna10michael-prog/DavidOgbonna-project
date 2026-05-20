# ☁️ CloudVault — Personal Cloud Storage

A full-stack mini Dropbox built with **FastAPI + SQLite + HTML/CSS**.
Every file is deliberately simple so you can read and understand every line.

---

## 🚀 Quick Start

```bash
# 1. Clone / enter the project folder
cd cloudvault

# 2. Create a virtual environment (best practice)
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the server
uvicorn main:app --reload

# 5. Open your browser
# http://localhost:8000
```

---

## 📁 Project Structure

```
cloudvault/
├── main.py              ← All backend logic (FastAPI app)
├── requirements.txt     ← Python dependencies
├── cloudvault.db        ← SQLite database (auto-created)
├── uploads/             ← Uploaded files (auto-created, per-user folders)
└── templates/
    ├── landing.html     ← Marketing/home page
    ├── login.html       ← Sign-in form
    ├── register.html    ← Sign-up form
    └── dashboard.html   ← Main app (file manager)
```

---

## 🧠 What You'll Learn

### 1. Authentication & Sessions
**Where to look:** `hash_password()`, `verify_password()`, `create_session()`, `get_current_user()`

Key concepts:
- **Salted password hashing** — never store plain passwords. Each password gets a random salt + SHA-256 hash.
- **Session tokens** — after login, we generate a random `token` stored in the DB and set as an HTTP-only cookie.
- **HTTP-only cookies** — JavaScript cannot access them, preventing XSS theft.
- **Session expiry** — sessions expire after 24 hours automatically.

```python
# How password hashing works
salt = secrets.token_hex(16)           # random 32-char string
hash = sha256(salt + password)         # hash of salt+password
stored = f"{salt}:{hash}"             # store both together

# To verify: split stored, recompute, compare
```

---

### 2. File Uploads & Downloads
**Where to look:** `/upload` and `/download/{file_id}` routes

Key concepts:
- **UploadFile** — FastAPI's built-in file upload handler reads the file into memory.
- **UUID filenames** — we store files as `<uuid>.ext` to prevent collisions and path traversal attacks.
- **User-scoped folders** — each user's files live in `uploads/<user_id>/`, so there's no cross-user leakage.
- **FileResponse** — FastAPI serves the file with the correct `Content-Disposition` header so the browser downloads it with the original filename.

```
uploads/
  1/           ← user ID 1's files
    a3f9b2c1.pdf
    89de4021.jpg
  2/           ← user ID 2's files
    ...
```

---

### 3. Database Integration (SQLite)
**Where to look:** `init_db()`, `get_db()`, and all SQL queries

Three tables:
| Table    | Purpose                              |
|----------|--------------------------------------|
| users    | Stores accounts (no plain passwords) |
| sessions | Maps tokens to users + expiry        |
| files    | Metadata for each uploaded file      |

SQLite is file-based — perfect for learning. In production you'd swap to PostgreSQL.

```python
# Dependency injection pattern (FastAPI's way)
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets you do row["column"] instead of row[0]
    try:
        yield conn
    finally:
        conn.close()
```

---

### 4. API Development with FastAPI
**Where to look:** all `@app.get()` and `@app.post()` decorators

FastAPI is built on top of Starlette and uses Python type hints:
- `GET /` — landing page
- `POST /register` — create account
- `POST /login` — authenticate
- `POST /logout` — destroy session
- `GET /dashboard` — file manager (auth required)
- `POST /upload` — handle file upload (auth required)
- `GET /download/{file_id}` — serve file (auth required, ownership checked)
- `POST /delete/{file_id}` — delete file + disk data (auth required, ownership checked)

FastAPI auto-generates docs at `http://localhost:8000/docs` — check it out!

---

### 5. Security Practices

| What | How | Why |
|------|-----|-----|
| Password hashing | salt + SHA-256 | Never store plaintext |
| Session tokens | `secrets.token_urlsafe(32)` | Cryptographically random |
| HTTP-only cookies | `httponly=True` | Blocks JS access |
| File size limit | 50MB check before writing | Prevent disk abuse |
| UUID filenames | `uuid4().hex` | No path traversal |
| Ownership check | `WHERE id=? AND user_id=?` | Users can't touch others' files |
| Input sanitization | Filename character whitelist | Prevent bad filenames |

**What's NOT in this app (add for production):**
- HTTPS (use nginx/Caddy + Let's Encrypt)
- CSRF tokens (add `itsdangerous` or use `starlette.middleware.csrf`)
- Rate limiting (use `slowapi`)
- File type validation (check magic bytes, not just extension)
- Environment variables for `SECRET_KEY` (use `python-dotenv`)

---

### 6. Deployment

**Option A: Simple VPS (DigitalOcean, Hetzner, Render)**

```bash
# Install on server
pip install -r requirements.txt

# Run with gunicorn (production WSGI)
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**Option B: Docker**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Option C: Render / Railway** — connect your GitHub repo, set start command to:
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

> ⚠️ SQLite is a single-file DB — for multi-instance deployments, use PostgreSQL.

---

## 🔧 Extending CloudVault

Ideas for leveling up:
- **Folders** — add a `parent_folder_id` column to the files table
- **File preview** — inline image/PDF viewer using `<iframe>` or `<img>`
- **Share links** — generate a public UUID-based URL for one file
- **Storage quota** — add a `quota_bytes` limit per user
- **Search** — `WHERE original_name LIKE ?` query
- **Thumbnails** — use `Pillow` to generate image thumbnails on upload
- **Background tasks** — use FastAPI's `BackgroundTasks` to send a welcome email

---

## 🛠️ Tech Stack

| Layer     | Tech                   |
|-----------|------------------------|
| Backend   | FastAPI (Python)       |
| Database  | SQLite (via stdlib)    |
| Auth      | Sessions + cookies     |
| Templates | Jinja2                 |
| Frontend  | Pure HTML + CSS + JS   |
| Server    | Uvicorn (ASGI)         |
