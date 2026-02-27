from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles  # ← NOVO IMPORT
from typing import List
import base64
import shutil
import pandas as pd
from ollama import Client
from sqlalchemy import create_engine, text
import os
import uuid
from datetime import datetime
import hashlib

app = FastAPI()

# Monta a pasta raiz como estática → serve login.html, index.html, etc. diretamente
app.mount("/", StaticFiles(directory=".", html=True), name="static")

# ==========================
# CONFIG OLLAMA CLOUD
# ==========================
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
if not OLLAMA_API_KEY:
    raise ValueError("OLLAMA_API_KEY não definida! Adicione no Render Environment.")

OLLAMA_MODEL = "qwen3-vl:235b-instruct-cloud"

client = Client(
    host="https://api.ollama.com",
    headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"}
)

# ==========================
# CONFIG BANCO
# ==========================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./auditoria.db")
engine = create_engine(DATABASE_URL)

# ==========================
# FUNÇÃO HASH SENHA
# ==========================

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

# ==========================
# CRIAR TABELAS SE NÃO EXISTIREM
# ==========================

with engine.connect() as conn:
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        senha TEXT
    )
    """))

    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS auditoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT,
        arquivo TEXT,
        transcricao TEXT,
        pedido_identificado TEXT,
        data_requisicao TEXT,
        data_resposta TEXT
    )
    """))
    conn.commit()

# ==========================
# CRIAR USUÁRIO ADMIN PADRÃO
# ==========================

with engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM usuarios WHERE username='admin'"))
    if not result.fetchone():
        conn.execute(text("INSERT INTO usuarios (username, senha) VALUES (:u, :s)"),
                     {"u": "admin", "s": hash_senha("1234")})
        conn.commit()

# ==========================
# LOGIN
# ==========================

@app.get("/login")
def tela_login():
    return FileResponse("login.html")

@app.post("/login")
async def fazer_login(username: str = Form(...), password: str = Form(...)):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM usuarios WHERE username=:u AND senha=:s"),
            {"u": username, "s": hash_senha(password)}
        ).fetchone()

    if result:
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key="usuario", value=username)
        return response

    return {"erro": "Usuário ou senha inválidos"}

# ==========================
# LOGOUT
# ==========================

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("usuario")
    return response

# ==========================
# HOME PROTEGIDA
# ==========================

@app.get("/")
def home(request: Request):
    if not request.cookies.get("usuario"):
        return RedirectResponse(url="/login")

    return FileResponse("index.html")

# ==========================
# PROCESSAMENTO IA
# ==========================

def processar_imagem(caminho):
    try:
        with open(caminho, "rb") as img:
            image_bytes = base64.b64encode(img.read()).decode("utf-8")

        prompt = """
Você é um auditor de plano de saúde.

Responda exatamente no formato:

TRANSCRIÇÃO:
texto aqui

PEDIDO IDENTIFICADO:
texto aqui
"""

        resposta = client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_bytes]
                }
            ],
            stream=False
        )

        texto = resposta["message"]["content"]
        print(f"Resposta Ollama Cloud: {texto}")  # para debug no log do Render

        transcricao = ""
        pedido = ""

        if "TRANSCRIÇÃO:" in texto:
            bloco = texto.split("TRANSCRIÇÃO:")[1]
            if "PEDIDO IDENTIFICADO:" in bloco:
                transcricao = bloco.split("PEDIDO IDENTIFICADO:")[0].strip()
                pedido = bloco.split("PEDIDO IDENTIFICADO:")[1].strip()

        return transcricao, pedido

    except Exception as e:
        print(f"Erro Ollama Cloud: {str(e)}")
        return "Erro na transcrição com Ollama Cloud", "Erro no pedido identificado"

# ==========================
# UPLOAD LOTE
# ==========================

@app.post("/upload-lote")
async def upload_lote(request: Request, files: List[UploadFile] = File(...)):
    usuario = request.cookies.get("usuario")
    if not usuario:
        return RedirectResponse(url="/login")

    resultados = []
    os.makedirs("uploads", exist_ok=True)

    data_requisicao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for file in files:
        nome_unico = f"{uuid.uuid4()}_{file.filename}"
        caminho = os.path.join("uploads", nome_unico)

        with open(caminho, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file.file.close()

        transcricao, pedido = processar_imagem(caminho)

        data_resposta = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO auditoria 
                (usuario, arquivo, transcricao, pedido_identificado, data_requisicao, data_resposta)
                VALUES (:u, :a, :t, :p, :dr, :ds)
            """), {
                "u": usuario,
                "a": file.filename,
                "t": transcricao,
                "p": pedido,
                "dr": data_requisicao,
                "ds": data_resposta
            })
            conn.commit()

        resultados.append({
            "arquivo": file.filename,
            "transcricao": transcricao,
            "pedido_identificado": pedido,
            "data_requisicao": data_requisicao,
            "data_resposta": data_resposta
        })

    return resultados

# ==========================
# PAINEL ADMIN
# ==========================

@app.get("/admin")
def admin(request: Request):
    usuario = request.cookies.get("usuario")
    if not usuario:
        return RedirectResponse(url="/login")

    df = pd.read_sql("SELECT * FROM auditoria ORDER BY id DESC", engine)
    return df.to_dict(orient="records")

# ==========================
# EXPORTAR EXCEL
# ==========================

@app.get("/baixar-excel")
def baixar_excel(request: Request):
    usuario = request.cookies.get("usuario")
    if not usuario:
        return RedirectResponse(url="/login")

    df = pd.read_sql("SELECT * FROM auditoria", engine)
    caminho = "auditoria_export.xlsx"
    df.to_excel(caminho, index=False)
    return FileResponse(caminho, filename="auditoria.xlsx")