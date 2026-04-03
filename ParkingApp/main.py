from fastapi import FastAPI, Form, File, UploadFile, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os, csv, uuid, secrets, io
from datetime import datetime
from PIL import Image
from azure.storage.blob import BlobServiceClient, ContentSettings
from jinja2 import Environment, FileSystemLoader
from zoneinfo import ZoneInfo

app = FastAPI()
security = HTTPBasic()

# --- 設定値 ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin" # 実務では環境変数での管理を推奨しますが、一旦このままで稼働します
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

# Azureクライアントの初期化
try:
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
except Exception as e:
    print(f"Azure Connection Error: {e}")

# 管理者認証
def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

# Jinja2レンダリング
def render_html(filename: str, context: dict = None):
    base_dir = os.path.dirname(__file__)
    env = Environment(loader=FileSystemLoader(os.path.join(base_dir, "templates")))
    template = env.get_template(filename)
    return template.render(context or {})

# --- ユーザー用エンドポイント ---

@app.get("/", response_class=HTMLResponse)
async def get_form():
    return HTMLResponse(content=render_html("index.html"))

@app.post("/submit")
async def handle_form(company: str = Form(...), name: str = Form(...), car_number: str = Form(...), photo: UploadFile = File(...)):
    request_id = str(uuid.uuid4())[:8]
    
    # 1. 画像処理（iPhone等のRGBA/HEIC対策）
    try:
        img = Image.open(photo.file)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((800, 800))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        img_byte_arr.seek(0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image processing error: {e}")

    # 2. Azureアップロード（ブラウザ表示用Content-Type指定）
    filename = f"{request_id}.jpg"
    blob_client = blob_service_client.get_blob_client(container="uploads", blob=filename)
    blob_client.upload_blob(img_byte_arr, overwrite=True, content_settings=ContentSettings(content_type='image/jpeg'))

    # 3. CSVデータベース更新
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    existing_content = ""
    try:
        existing_content = db_blob_client.download_blob().content_as_text()
    except:
        pass # ファイルが存在しない場合は空文字から開始
    
    new_row = f"{request_id},{datetime.now().strftime('%Y-%m-%d %H:%M')},{company},{name},{car_number},{filename},pending\n"
    db_blob_client.upload_blob(existing_content + new_row, overwrite=True)

    return RedirectResponse(url=f"/status/{request_id}", status_code=303)

@app.get("/status/{request_id}", response_class=HTMLResponse)
async def get_status(request_id: str):
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    content = db_blob_client.download_blob().content_as_text()
    rows = list(csv.reader(io.StringIO(content.strip()))) # stripで末尾の空行を排除
    
    user_data = next((r for r in rows if len(r) >= 7 and r[0] == request_id), None)
    if not user_data:
        return HTMLResponse(content="Request Not Found", status_code=404)

    return HTMLResponse(content=render_html("status.html", {
        "id": request_id,
        "name": user_data[3],
        "user": {"id": user_data[0], "status": user_data[6]}
    }))

# --- 管理者用エンドポイント ---

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(username: str = Depends(get_current_username)):
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    
    # メタデータ取得
    props = db_blob_client.get_blob_properties()
    last_mod = props.last_modified.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")
    
    # CSV読み込み
    try:
        content = db_blob_client.download_blob().content_as_text()
        # 空行を飛ばして読み込む実務的な処理
        rows = [r for r in csv.reader(io.StringIO(content.strip())) if len(r) >= 7]
    except:
        rows = []
    
    return HTMLResponse(content=render_html("admin.html", {
        "requests": rows,
        "last_modified": last_mod,
        "account_name": blob_service_client.account_name
    }))

@app.post("/admin/approve/{request_id}")
async def approve_request(request_id: str, username: str = Depends(get_current_username)):
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    content = db_blob_client.download_blob().content_as_text()
    rows = list(csv.reader(io.StringIO(content.strip())))
    
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        if len(row) >= 7 and row[0] == request_id:
            row[6] = "approved"
        writer.writerow(row)
    
    db_blob_client.upload_blob(output.getvalue(), overwrite=True)
    return RedirectResponse(url="/admin", status_code=303)