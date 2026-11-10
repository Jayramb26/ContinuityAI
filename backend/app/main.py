from datetime import datetime, timezone
from pathlib import Path
import os
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Project, SourceDocument, KnowledgeItem
from .schemas import ProjectCreate, ReviewUpdate
from .ingestion import extract_text, chunks
from .knowledge import heuristic_extract, ai_extract

Base.metadata.create_all(bind=engine)
app = FastAPI(title="ContinuityAI API", version="0.1.1", description="Evidence-linked project knowledge handover")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://continuityai-web.onrender.com").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "ContinuityAI"}

def project_dict(p):
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at.isoformat()}

def item_dict(i):
    return {"id": i.id, "category": i.category, "title": i.title, "detail": i.detail, "source_id": i.source_id, "evidence": i.evidence, "status": i.status, "verified": i.verified}

@app.post("/api/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Project name is required")
    p = Project(name=payload.name.strip(), description=payload.description.strip())
    db.add(p); db.commit(); db.refresh(p)
    return project_dict(p)

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    return [project_dict(p) for p in db.scalars(select(Project).order_by(Project.created_at.desc())).all()]

@app.get("/api/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id)).all()
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id).order_by(KnowledgeItem.id.desc())).all()
    return {**project_dict(p), "documents": [{"id": d.id, "filename": d.filename, "uploaded_at": d.uploaded_at.isoformat()} for d in docs], "items": [item_dict(i) for i in items]}

@app.post("/api/projects/{project_id}/upload")
async def upload_document(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    filename = Path(file.filename or "upload.txt").name
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is too large. Maximum upload size is 10 MB.")
    try:
        content = extract_text(filename, raw)
    except Exception as e:
        raise HTTPException(400, f"Could not read document: {e}")
    doc = SourceDocument(project_id=project_id, filename=filename, content=content)
    db.add(doc); db.commit(); db.refresh(doc)
    extraction_mode = "rule_based"
    try:
        extracted = await ai_extract(content)
        if extracted is not None:
            extraction_mode = "llm_with_evidence_validation"
        else:
            extracted = heuristic_extract(content)
    except Exception:
        extracted = heuristic_extract(content)
    for x in extracted:
        db.add(KnowledgeItem(project_id=project_id, source_id=doc.id, **x))
    db.commit()
    return {"document": {"id": doc.id, "filename": doc.filename, "characters": len(content), "chunks": len(chunks(content))}, "extracted_count": len(extracted), "extraction_mode": extraction_mode}

@app.patch("/api/items/{item_id}")
def review_item(item_id: int, payload: ReviewUpdate, db: Session = Depends(get_db)):
    item = db.get(KnowledgeItem, item_id)
    if not item:
        raise HTTPException(404, "Knowledge item not found")
    if payload.status not in {"needs_review", "approved", "rejected", "unknown"}:
        raise HTTPException(400, "Invalid review status")
    item.title, item.detail, item.status, item.verified = payload.title, payload.detail, payload.status, payload.verified
    db.commit(); db.refresh(item)
    return item_dict(item)

@app.get("/api/projects/{project_id}/handover")
def handover(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id)).all()
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id)).all()
    approved = [i for i in items if i.status == "approved"]
    gaps = [i for i in items if i.status in {"needs_review", "unknown"}]
    categories = {c: [item_dict(i) for i in approved if i.category == c] for c in ["decision", "task", "risk", "question"]}
    coverage = sum(bool(categories[c]) for c in categories)
    readiness = round((coverage / 4) * 60 + (len(approved) / max(1, len(items))) * 40)
    return {"project": project_dict(p), "generated_at": datetime.now(timezone.utc).isoformat(), "source_count": len(docs), "approved_count": len(approved), "review_count": len(gaps), "readiness": readiness, "categories": categories, "gaps": [item_dict(i) for i in gaps], "next_steps": ["Review all unverified knowledge items", "Confirm task owners and deadlines", "Resolve open risks and dependencies", "Approve the handover before sharing"]}

@app.get("/api/projects/{project_id}/handover.md")
def handover_markdown(project_id: int, db: Session = Depends(get_db)):
    data = handover(project_id, db)
    lines = [f"# Handover: {data['project']['name']}", "", data['project']['description'], "", f"Generated: {data['generated_at']}", f"Readiness checklist: {data['readiness']}%", f"Sources: {data['source_count']} | Approved: {data['approved_count']} | Needs review: {data['review_count']}"]
    for cat, title in [("decision", "Key decisions"), ("task", "Tasks and actions"), ("risk", "Risks and dependencies"), ("question", "Open questions")]:
        lines += ["", f"## {title}"]
        group = data['categories'][cat]
        if not group:
            lines.append("- No approved items yet.")
        for x in group:
            lines.append(f"- **{x['title']}** — {x['detail']} _(Source: document #{x['source_id']}; evidence: “{x['evidence']}”)_")
    lines += ["", "## Items requiring review"]
    for x in data['gaps']:
        lines.append(f"- [{x['status']}] {x['title']} (source document #{x['source_id']})")
    lines += ["", "## Recommended next actions"] + [f"- {x}" for x in data['next_steps']]
    return Response(content="\n".join(lines), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="continuityai-handover-{project_id}.md"'})
