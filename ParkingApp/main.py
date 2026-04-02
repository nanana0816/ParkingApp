from fastapi import FastAPI, Form, File, UploadFile, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os, csv, uuid, secrets, io
from datetime import datetime
from PIL import Image
from azure.storage.blob import BlobServiceClient

app = FastAPI()
security = HTTPBasic()

# 管理者設定
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

# Azure接続設定（Renderの環境変数から読み込み）
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_correct_username and is_correct_password):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

# HTMLレンダリング関数
def render_html(filename: str, context: dict = None):
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, "templates", filename)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if context:
        for key, value in context.items():
            content = content.replace("{{" + key + "}}", str(value)).replace("{{ " + key + " }}", str(value))
    return content

@app.get("/", response_class=HTMLResponse)
async def get_form():
    return HTMLResponse(content=render_html("index.html"))

@app.post("/submit")
async def handle_form(company: str = Form(...), name: str = Form(...), car_number: str = Form(...), photo: UploadFile = File(...)):
    request_id = str(uuid.uuid4())[:8]
    
    # 1. 画像をリサイズしてメモリ上に保存
    img = Image.open(photo.file)
        # 【ここを追加！】透明な層(RGBA)を普通の形式(RGB)に変換する
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((800, 800))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG', quality=85)
    img_byte_arr.seek(0)

    # 2. Azure Blob Storage (uploads) へ画像をアップロード
    filename = f"{request_id}.jpg"
    blob_client = blob_service_client.get_blob_client(container="uploads", blob=filename)
    blob_client.upload_blob(img_byte_arr, overwrite=True)

    # 3. CSVデータをAzure Blob Storage (database) へ更新保存
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    
    # 既存データの読み込み
    existing_data = ""
    try:
        existing_data = db_blob_client.download_blob().content_as_text()
    except:
        pass # 初回作成時など
    
    new_row = f"{request_id},{datetime.now().strftime('%Y-%m-%d %H:%M')},{company},{name},{car_number},{filename},pending\n"
    updated_data = existing_data + new_row
    db_blob_client.upload_blob(updated_data, overwrite=True)

    return RedirectResponse(url=f"/status/{request_id}", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(username: str = Depends(get_current_username)):
    # AzureからCSVを取得
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    rows = []
    try:
        content = db_blob_client.download_blob().content_as_text()
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
    except:
        pass

    table_html = ""
    for r in rows:
        if len(r) < 7: continue
        # 画像URLをAzureの公開URLに変更（本来はSASが必要ですが、まずは簡易的に）
        photo_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/uploads/{r[5]}"
        btn = f'<form action="/admin/approve/{r[0]}" method="post"><button type="submit">承認する</button></form>' if r[6] == "pending" else "✅承認済み"
        table_html += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[3]}</td><td><a href='{photo_url}' target='_blank'>📸表示</a></td><td>{r[6]}</td><td>{btn}</td></tr>"

    return HTMLResponse(content=f"<html><body><h1>FAM Admin</h1><table>{table_html}</table></body></html>")

@app.post("/admin/approve/{request_id}")
async def approve_request(request_id: str, username: str = Depends(get_current_username)):
    db_blob_client = blob_service_client.get_blob_client(container="database", blob="parking_requests.csv")
    content = db_blob_client.download_blob().content_as_text()
    rows = list(csv.reader(io.StringIO(content)))
    
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        if row[0] == request_id: row[6] = "approved"
        writer.writerow(row)
    
    db_blob_client.upload_blob(output.getvalue(), overwrite=True)
    return RedirectResponse(url="/admin", status_code=303)
# --- ここから下が最終行までの追加分です ---

@app.get("/status/{request_id}", response_class=HTMLResponse)
async def get_status(request_id: str):
    # status.html を読み込んで表示。render_html関数が定義されている前提です。
    return HTMLResponse(content=render_html("status.html", {"request_id": request_id}))