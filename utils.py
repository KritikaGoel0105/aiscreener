# utils.py — Resume Parsing, Embeddings, Contact Extraction, Azure Uploads

import re
import fitz  # PyMuPDF
import numpy as np
import tiktoken
import functools
from azure.storage.blob import BlobClient
from sklearn.metrics.pairwise import cosine_similarity
from constants import AZURE_CONFIG, MODEL_CONFIG
from openai import AzureOpenAI

# ==========================
# 📄 Resume Text Extractor
# ==========================
def parse_resume(file_bytes):
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            text = ""
            for page in doc:
                text += page.get_text()
        return text.strip()
    except:
        return "Error reading resume"

# ==========================
# 📎 Chunk Text for GPT or Embedding
# ==========================
def chunk_text(text, max_tokens=3000, overlap=200):
    enc = tiktoken.encoding_for_model("gpt-4")
    tokens = enc.encode(text)
    chunks = []
    i = 0
    while i < len(tokens):
        chunk = tokens[i:i + max_tokens]
        chunks.append(enc.decode(chunk))
        i += max_tokens - overlap
    return chunks

def get_text_chunks(text, max_tokens=800, overlap=100):
    enc = tiktoken.encoding_for_model("gpt-4")
    tokens = enc.encode(text)
    chunks = []
    i = 0
    while i < len(tokens):
        chunk = tokens[i:i + max_tokens]
        chunks.append(enc.decode(chunk))
        i += max_tokens - overlap
    return chunks

# ==========================
# 🧠 Embedding + Similarity
# ==========================
def get_embedding(text):
    client = AzureOpenAI(
        api_key=AZURE_CONFIG["openai_key"],
        api_version=AZURE_CONFIG["api_version"],
        azure_endpoint=AZURE_CONFIG["azure_endpoint"]
    )
    try:
        response = client.embeddings.create(
            input=[text],
            model=MODEL_CONFIG["embedding_model"]
        )
        return response.data[0].embedding
    except:
        return [0.0] * 1536  # fallback vector

@functools.lru_cache(maxsize=10)
def get_embedding_cached(text):
    return tuple(get_embedding(text))  # lru_cache requires hashable input

def get_cosine_similarity(vec1, vec2):
    try:
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        return cosine_similarity([vec1], [vec2])[0][0]
    except:
        return 0.0

# ==========================
# 📬 Contact Info Extractor with Name Fallback
# ==========================
def extract_contact_info(text):
    name = "N/A"
    email_match = re.search(r"[\w\.-]+@[\w\.-]+", text)
    phone_match = re.search(r"\+?\d[\d\s\-]{8,}", text)

    email = email_match.group(0) if email_match else "N/A"
    phone = phone_match.group(0).replace(" ", "").replace("-", "") if phone_match else "N/A"

    # Try name from first 10 lines (fallback if GPT fails)
    lines = text.splitlines()
    for line in lines[:10]:
        line_clean = line.strip()
        if len(line_clean.split()) <= 5 and any(
            kw.lower() in line_clean.lower() for kw in ["name", "curriculum", "cv", "resume"]
        ):
            name = re.sub(r"(name|cv|resume|curriculum vitae)[:\-]?", "", line_clean, flags=re.I).strip()
            break

    # If still not found, fallback to first non-empty capitalized line
    if name == "N/A":
        for line in lines[:10]:
            if line.strip() and line.strip()[0].isupper() and len(line.strip().split()) <= 5:
                name = line.strip()
                break

    return {
        "name": name or "N/A",
        "email": email,
        "phone": phone
    }

# ==========================
# ☁️ Azure Uploads (Resumes, PDFs, CSVs)
# ==========================
def upload_to_blob(file_bytes, file_name, container):
    blob = BlobClient.from_connection_string(
        conn_str=AZURE_CONFIG["connection_string"],
        container_name=container,
        blob_name=file_name
    )
    blob.upload_blob(file_bytes, overwrite=True)

def save_summary_to_blob(pdf_bytes, file_name, container):
    blob = BlobClient.from_connection_string(
        conn_str=AZURE_CONFIG["connection_string"],
        container_name=container,
        blob_name=file_name
    )
    blob.upload_blob(pdf_bytes, overwrite=True)

def save_csv_to_blob(df, file_name, container):
    blob = BlobClient.from_connection_string(
        conn_str=AZURE_CONFIG["connection_string"],
        container_name=container,
        blob_name=file_name
    )
    blob.upload_blob(df.to_csv(index=False), overwrite=True)
