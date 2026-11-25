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
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(io.BytesIO(data))
        parts = []
        # Iterate top-level paragraphs and tables in document order so content
        # stored in meeting-note/action tables is not silently discarded.
        for block in doc.iter_inner_content():
            if isinstance(block, Paragraph):
                value = block.text.strip()
                if value:
                    parts.append(value)
            elif isinstance(block, Table):
                for row in block.rows:
                    cells = [
                        " / ".join(part.strip() for part in cell.text.splitlines() if part.strip())
                        for cell in row.cells
                    ]
                    if any(cells):
                        parts.append(" | ".join(cells))
        text = "\n".join(parts)
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
