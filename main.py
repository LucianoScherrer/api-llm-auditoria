from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from typing import List
import base64
import shutil
import pandas as pd
from ollama import Client  # Cliente para API remota/cloud
from sqlalchemy import create_engine, text
import os
import uuid
from datetime import datetime
import hashlib

app = FastAPI()

# ==========================
# CONFIG OLLAMA CLOUD
# ==========================
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
if not OLLAMA_API_KEY:
    raise ValueError("OLLAMA_API_KEY não definida! Adicione no Render Environment.")

OLLAMA_MODEL = "qwen3-vl:235b-instruct-cloud"  # Fixo no modelo que você quer

# Endpoint oficial do Ollama Cloud
client = Client(
    host="https://api.ollama.com",
    headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"}
)

# ==========================
# CONFIG BANCO (sem mudanças)
# ==========================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./auditoria.db")
engine = create_engine(DATABASE_URL)

# (resto do código de tabelas, hash_senha, admin padrão, login, logout, home permanece igual)

# ==========================
# PROCESSAMENTO IA - AGORA COM CLOUD MODEL
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
        print(f"Resposta Ollama Cloud: {texto}")  # Log para debug no Render

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

# (o resto do código: upload-lote, admin, baixar-excel permanece igual)