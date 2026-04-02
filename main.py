from fastapi import FastAPI, Form, File, UploadFile, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os, csv, uuid, secrets
from datetime import datetime
from PIL import Image

app = FastAPI()

security = HTTPBasic()

# 管理者用のIDとパスワード
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

UPLOAD_DIR = "uploads"
DB_FILE = "parking_requests.csv"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

def render_html(filename: str, context: dict = None):
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "templates", filename)
    if not os.path.exists(path):
        return f"Error: {filename} not found at {path}"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if context:
        for key, value in context.items():
            content = content.replace("{{" + f" {key} " + "}}", str(value)).replace("{{" + key + "}}", str(value))
    return content

@app.get("/", response_class=HTMLResponse)
async def get_form():
    return HTMLResponse(content=render_html("index.html"))

@app.post("/submit")
async def handle_form(company: str = Form(...), name: str = Form(...), car_number: str = Form(...), photo: UploadFile = File(...)):
    request_id = str(uuid.uuid4())[:8]
    img = Image.open(photo.file)
    img.thumbnail((800, 800))
    filename = f"{request_id}.jpg"
    img.save(os.path.join(UPLOAD_DIR, filename), "JPEG", quality=85)
    with open(DB_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([request_id, datetime.now().strftime("%Y-%m-%d %H:%M"), company, name, car_number, filename, "pending"])
    return RedirectResponse(url=f"/status/{request_id}", status_code=303)

@app.get("/status/{request_id}", response_class=HTMLResponse)
async def check_status(request_id: str):
    user_name = "不明"
    status = "pending"
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if row[0] == request_id:
                    user_name = row[3]
                    status = row[6]
                    break
    path = os.path.join("templates", "status.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("{{ id }}", request_id).replace("{{ name }}", user_name)
    import re
    if status == "approved":
        html = re.sub(r'\{% if user\.status == "approved" %\}', '', html)
        html = re.sub(r'\{% else %\}.*?\{% endif %\}', '', html, flags=re.DOTALL)
    else:
        html = re.sub(r'\{% if user\.status == "approved" %\}.*?\{% else %\}', '', html, flags=re.DOTALL)
        html = re.sub(r'\{% endif %\}', '', html)
    return HTMLResponse(content=html)

# --- 管理者用：承認一覧画面 (ここをパスワードで保護しました) ---
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(username: str = Depends(get_current_username)): # ← ここが重要！
    rows = []
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for r in reader:
                if len(r) >= 7:
                    rows.append(r)
    
    table_html = ""
    for r in rows:
        photo_btn = f'<a href="/uploads/{r[5]}" target="_blank" style="color:#c5a059; font-weight:bold; text-decoration:none;">📸表示</a>'
        if r[6] == "pending":
            btn = f'<form action="/admin/approve/{r[0]}" method="post" style="margin:0;"><button type="submit" style="cursor:pointer; background:#1a2a3a; color:white; border:none; padding:5px 10px; border-radius:4px;">承認する</button></form>'
        else:
            btn = '<span style="color:green; font-weight:bold;">✅ 承認済み</span>'
        table_html += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[3]}</td><td>{r[4]}</td><td style='text-align:center;'>{photo_btn}</td><td>{r[6]}</td><td>{btn}</td></tr>"

    content = f"<html><body><h1>🚗 FAM 管理パネル</h1><table>{table_html}</table></body></html>"
    return HTMLResponse(content=content)

@app.post("/admin/approve/{request_id}")
async def approve_request(request_id: str, username: str = Depends(get_current_username)): # ← ここも保護
    rows = []
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        with open(DB_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in rows:
                if row[0] == request_id: row[6] = "approved"
                writer.writerow(row)
    return RedirectResponse(url="/admin", status_code=303)