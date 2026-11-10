from pathlib import Path
import fitz
from docx import Document

ALLOWED = {".pdf", ".docx", ".txt", ".md"}

def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        raise ValueError("Unsupported file type. Upload PDF, DOCX, TXT or Markdown.")
    if ext == ".pdf":
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text("text") for page in doc)
    elif ext == ".docx":
        import io
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    else:
        text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise ValueError("No readable text found in this document.")
    return text

def chunks(text: str, size: int = 1100, overlap: int = 160):
    text = " ".join(text.split())
    result = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        result.append(text[start:end])
        if end == len(text): break
        start = max(start + 1, end - overlap)
    return result
