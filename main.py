from fastapi import FastAPI, Form, File, UploadFile, Request, Depends, HTTPException # DependsとHTTPExceptionを追加
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials # 追加
import secrets # 追加

# 1. まず最初に 'app' を定義する（これが抜けていたのが原因です）
app = FastAPI()

UPLOAD_DIR = "uploads"
DB_FILE = "parking_requests.csv"
if not os.path.exists(UPLOAD_DIR): os.makedirs(UPLOAD_DIR)

# 2. 静的ファイルの公開設定
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- HTMLを読み込むためのヘルパー関数 (絶対パス指定) ---
def render_html(filename: str, context: dict = None):
    # main.pyがある場所を基準に templates フォルダを探す
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "templates", filename)
    
    if not os.path.exists(path):
        return f"Error: {filename} not found at {path}" # どこを探したか画面に出す

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if context:
        for key, value in context.items():
            content = content.replace("{{" + f" {key} " + "}}", str(value)).replace("{{" + key + "}}", str(value))
    return content
# --- 申請画面 ---
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

# --- 申請者用：状況確認画面 (バグ修正版) ---
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
    
    # テンプレートを読み込む
    path = os.path.join("templates", "status.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    # IDと名前を埋め込む
    html = html.replace("{{ id }}", request_id).replace("{{ name }}", user_name)

    # 【重要】Jinja2のタグを消しながら、中身を出し分ける
    if status == "approved":
        # 承認済み：承認待ち用のブロックをまるごと消去
        # {% else %} から {% endif %} までを非表示にする
        import re
        html = re.sub(r'\{% if user\.status == "approved" %\}', '', html)
        html = re.sub(r'\{% else %\}.*?\{% endif %\}', '', html, flags=re.DOTALL)
    else:
        # 承認待ち：承認済み用のブロックをまるごと消去
        # {% if %} から {% else %} までを非表示にする
        import re
        html = re.sub(r'\{% if user\.status == "approved" %\}.*?\{% else %\}', '', html, flags=re.DOTALL)
        html = re.sub(r'\{% endif %\}', '', html)

    return HTMLResponse(content=html)

security = HTTPBasic()

# 管理者用のIDとパスワード（ここを自由に変えてください）
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

# --- 管理者用：承認一覧画面 (パスワード保護版) ---
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(username: str = Depends(get_current_username)): # ここにDependsを追加
    rows = []
    # 1. まずCSVからデータを読み込む
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for r in reader:
                # データの数が足りない行をスキップする安全ガード
                if len(r) >= 7:
                    rows.append(r)
    
    # 2. 表の中身（HTML）を組み立てる
    table_html = "" # ここで定義しているので NameError は消えます
    for r in rows:
        # 写真を見るためのリンク
        photo_btn = f'<a href="/uploads/{r[5]}" target="_blank" style="color:#c5a059; font-weight:bold; text-decoration:none;">📸表示</a>'
        
        # 承認ボタンまたは済みマーク
        if r[6] == "pending":
            btn = f'<form action="/admin/approve/{r[0]}" method="post" style="margin:0;"><button type="submit" style="cursor:pointer; background:#1a2a3a; color:white; border:none; padding:5px 10px; border-radius:4px;">承認する</button></form>'
        else:
            btn = '<span style="color:green; font-weight:bold;">✅ 承認済み</span>'
            
        table_html += f"""
        <tr>
            <td style="padding:12px; border-bottom:1px solid #ddd;">{r[0]}</td>
            <td style="padding:12px; border-bottom:1px solid #ddd;">{r[1]}</td>
            <td style="padding:12px; border-bottom:1px solid #ddd;">{r[3]}</td>
            <td style="padding:12px; border-bottom:1px solid #ddd;">{r[4]}</td>
            <td style="padding:12px; border-bottom:1px solid #ddd; text-align:center;">{photo_btn}</td>
            <td style="padding:12px; border-bottom:1px solid #ddd;">{r[6]}</td>
            <td style="padding:12px; border-bottom:1px solid #ddd;">{btn}</td>
        </tr>
        """

    # 3. 最終的なHTMLを組み立てる (60秒で自動更新)
    content = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="60"> 
        <title>FAM Admin</title>
    </head>
    <body style="font-family:sans-serif; padding:20px; background:#f4f7f6;">
        <h1 style="color:#1a2a3a;">🚗 FAM 管理パネル (自動更新: 1分)</h1>
        <table style="width:100%; border-collapse:collapse; background:white; border-radius:8px; overflow:hidden; box-shadow:0 4px 15px rgba(0,0,0,0.1);">
            <tr style="background:#1a2a3a; color:white;">
                <th style="padding:15px; text-align:left;">ID</th>
                <th style="padding:15px; text-align:left;">日時</th>
                <th style="padding:15px; text-align:left;">氏名</th>
                <th style="padding:15px; text-align:left;">車両</th>
                <th style="padding:15px; text-align:center;">写真</th>
                <th style="padding:15px; text-align:left;">状態</th>
                <th style="padding:15px; text-align:left;">操作</th>
            </tr>
            {table_html if table_html else "<tr><td colspan='7' style='padding:30px; text-align:center;'>現在、申請はありません。</td></tr>"}
        </table>
        <p style="margin-top:20px;"><a href="/" style="color:#666; text-decoration:none;">← 申請画面へ戻る</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=content)
@app.post("/admin/approve/{request_id}")
async def approve_request(request_id: str):
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