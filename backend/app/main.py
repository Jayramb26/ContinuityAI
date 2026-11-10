from datetime import datetime, timezone
from pathlib import Path
import os
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import select, text, inspect
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from .models import Project, SourceDocument, KnowledgeItem, ActivityEvent, BrandGuideline, BrandReview
from .schemas import ProjectCreate, ReviewUpdate, KnowledgeCreate, ActivityCreate, BrandGuidelineCreate, BrandDecision
from .ingestion import extract_text, chunks
from .knowledge import heuristic_extract, ai_extract

Base.metadata.create_all(bind=engine)

# Lightweight additive migration so existing Render SQLite databases keep their data.
with engine.begin() as conn:
    existing = {c["name"] for c in inspect(engine).get_columns("knowledge_items")}
    for name, sql_type, default in [
        ("owner", "VARCHAR(180)", "''"),
        ("due_date", "VARCHAR(20)", "''"),
        ("priority", "VARCHAR(20)", "'medium'"),
        ("work_status", "VARCHAR(30)", "'open'"),
    ]:
        if name not in existing:
            conn.execute(text(f"ALTER TABLE knowledge_items ADD COLUMN {name} {sql_type} NOT NULL DEFAULT {default}"))

app = FastAPI(title="ContinuityAI API", version="0.2.0", description="Evidence-linked project knowledge continuity and handover")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://continuityai-web.onrender.com").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])



# Brand governance: explicit rules, explainable findings, human-owned decisions.
BRAND_KINDS = {"required_term", "prohibited_term", "approved_fact", "approved_asset", "tone_rule"}
BRAND_SEVERITIES = {"info", "warning", "critical"}

def guideline_dict(g):
    return {"id": g.id, "name": g.name, "kind": g.kind, "content": g.content,
            "severity": g.severity, "active": g.active, "created_at": g.created_at.isoformat()}

def review_dict(r):
    import json
    findings = json.loads(r.findings or "[]")
    return {"id": r.id, "filename": r.filename, "content": r.content,
            "findings": findings, "status": r.status, "decision_note": r.decision_note,
            "created_at": r.created_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "finding_count": len(findings),
            "critical_count": sum(1 for f in findings if f.get("severity") == "critical")}

def evaluate_brand_content(content, guidelines):
    findings = []
    lowered = content.casefold()
    for rule in guidelines:
        phrase = rule.content.strip()
        if not phrase:
            continue
        present = phrase.casefold() in lowered
        if rule.kind == "required_term" and not present:
            findings.append({"guideline_id": rule.id, "guideline": rule.name, "kind": rule.kind,
                "severity": rule.severity, "issue": f"Required term is missing: “{phrase}”.",
                "explanation": f"The approved wording “{phrase}” does not appear in this content.",
                "recommendation": f"Include the approved term “{phrase}” where contextually appropriate."})
        elif rule.kind == "prohibited_term" and present:
            findings.append({"guideline_id": rule.id, "guideline": rule.name, "kind": rule.kind,
                "severity": rule.severity, "issue": f"Prohibited wording found: “{phrase}”.",
                "explanation": f"The content contains wording that the guideline explicitly prohibits.",
                "recommendation": f"Remove or replace “{phrase}” with approved wording."})
        elif rule.kind == "approved_fact" and not present:
            findings.append({"guideline_id": rule.id, "guideline": rule.name, "kind": rule.kind,
                "severity": rule.severity, "issue": f"Approved fact not verified: “{phrase}”.",
                "explanation": "The supplied approved fact could not be matched exactly. This may be an omission or a wording variation, not proof that the content is false.",
                "recommendation": "Verify the fact with an authoritative source and use the approved wording if applicable."})
        elif rule.kind == "approved_asset" and not present:
            findings.append({"guideline_id": rule.id, "guideline": rule.name, "kind": rule.kind,
                "severity": rule.severity, "issue": f"Approved asset reference missing: “{phrase}”.",
                "explanation": "The configured approved asset name, URL or identifier was not found in the submitted text.",
                "recommendation": "Confirm the correct approved asset is used and referenced in the final content."})
        elif rule.kind == "tone_rule":
            # Tone rules are surfaced to a human reviewer; free-form style cannot be reliably proven by keyword matching.
            findings.append({"guideline_id": rule.id, "guideline": rule.name, "kind": rule.kind,
                "severity": rule.severity, "issue": "Human tone review required.",
                "explanation": f"Guideline: {phrase}. Automated checks cannot reliably judge brand voice from this rule alone.",
                "recommendation": "Read the content against this tone guidance and record the human decision."})
    # Common absolute claims are flagged for fact-checking, never auto-rejected.
    for term in ["guaranteed", "100% safe", "number one", "best in the world", "risk-free"]:
        if term in lowered:
            findings.append({"guideline_id": None, "guideline": "Claims requiring substantiation", "kind": "claim_check",
                "severity": "warning", "issue": f"Potentially unsubstantiated claim: “{term}”.",
                "explanation": "Absolute or comparative claims may require legal or evidence review.",
                "recommendation": "Attach substantiation or soften the claim before publication."})
    return findings

@app.get("/api/brand/guidelines")
def list_brand_guidelines(db: Session = Depends(get_db)):
    rows = db.scalars(select(BrandGuideline).order_by(BrandGuideline.created_at.desc())).all()
    return [guideline_dict(x) for x in rows]

@app.post("/api/brand/guidelines")
def create_brand_guideline(payload: BrandGuidelineCreate, db: Session = Depends(get_db)):
    if payload.kind not in BRAND_KINDS:
        raise HTTPException(400, "Choose a supported guideline type")
    if payload.severity not in BRAND_SEVERITIES:
        raise HTTPException(400, "Severity must be info, warning or critical")
    if not payload.name.strip() or not payload.content.strip():
        raise HTTPException(400, "Guideline name and approved rule content are required")
    row = BrandGuideline(name=payload.name.strip(), kind=payload.kind, content=payload.content.strip(), severity=payload.severity)
    db.add(row); db.commit(); db.refresh(row)
    return guideline_dict(row)

@app.delete("/api/brand/guidelines/{guideline_id}")
def delete_brand_guideline(guideline_id: int, db: Session = Depends(get_db)):
    row = db.get(BrandGuideline, guideline_id)
    if not row:
        raise HTTPException(404, "Guideline not found")
    db.delete(row); db.commit()
    return {"deleted": guideline_id}

@app.get("/api/brand/reviews")
def list_brand_reviews(db: Session = Depends(get_db)):
    rows = db.scalars(select(BrandReview).order_by(BrandReview.created_at.desc())).all()
    return [review_dict(x) for x in rows]

@app.post("/api/brand/reviews")
async def submit_brand_content(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = Path(file.filename or "brand-content.txt").name
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is too large. Maximum upload size is 10 MB.")
    try:
        content = extract_text(filename, raw)
    except Exception as e:
        raise HTTPException(400, f"Could not read content: {e}")
    if not content.strip():
        raise HTTPException(400, "No readable text found in the submitted content")
    rules = db.scalars(select(BrandGuideline).where(BrandGuideline.active == True)).all()
    findings = evaluate_brand_content(content, rules)
    import json
    review = BrandReview(filename=filename, content=content, findings=json.dumps(findings, ensure_ascii=False),
                         status="pending")
    db.add(review); db.commit(); db.refresh(review)
    return review_dict(review)

@app.patch("/api/brand/reviews/{review_id}")
def decide_brand_review(review_id: int, payload: BrandDecision, db: Session = Depends(get_db)):
    review = db.get(BrandReview, review_id)
    if not review:
        raise HTTPException(404, "Brand review not found")
    if payload.status not in {"approved", "rejected", "changes_requested"}:
        raise HTTPException(400, "Decision must be approved, rejected or changes_requested")
    review.status = payload.status
    review.decision_note = payload.decision_note.strip()[:2000]
    review.decided_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(review)
    return review_dict(review)

\n@app.get("/api/health")
def health():
    return {"status": "ok", "app": "ContinuityAI", "version": "0.2.0"}

def project_dict(p):
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at.isoformat()}

def item_dict(i):
    return {"id": i.id, "category": i.category, "title": i.title, "detail": i.detail, "source_id": i.source_id,
            "evidence": i.evidence, "status": i.status, "verified": i.verified, "owner": i.owner or "",
            "due_date": i.due_date or "", "priority": i.priority or "medium", "work_status": i.work_status or "open",
            "created_at": i.created_at.isoformat()}

def log_event(db, project_id, message, event_type="update", item_id=None):
    db.add(ActivityEvent(project_id=project_id, item_id=item_id, event_type=event_type, message=message))

def get_project_or_404(project_id, db):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@app.post("/api/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Project name is required")
    p = Project(name=payload.name.strip(), description=payload.description.strip())
    db.add(p); db.flush()
    log_event(db, p.id, f'Workspace "{p.name}" created', "workspace_created")
    db.commit(); db.refresh(p)
    return project_dict(p)

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    return [project_dict(p) for p in db.scalars(select(Project).order_by(Project.created_at.desc())).all()]

@app.get("/api/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = get_project_or_404(project_id, db)
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id)).all()
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id).order_by(KnowledgeItem.id.desc())).all()
    events = db.scalars(select(ActivityEvent).where(ActivityEvent.project_id == project_id).order_by(ActivityEvent.created_at.desc()).limit(50)).all()
    return {**project_dict(p),
            "documents": [{"id": d.id, "filename": d.filename, "uploaded_at": d.uploaded_at.isoformat()} for d in docs],
            "items": [item_dict(i) for i in items],
            "activity": [{"id": e.id, "event_type": e.event_type, "message": e.message, "item_id": e.item_id, "created_at": e.created_at.isoformat()} for e in events]}

@app.post("/api/projects/{project_id}/items")
def create_knowledge_item(project_id: int, payload: KnowledgeCreate, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    if payload.category not in {"decision", "task", "risk", "question"}:
        raise HTTPException(400, "Category must be decision, task, risk or question")
    if payload.priority not in {"low", "medium", "high", "critical"}:
        raise HTTPException(400, "Invalid priority")
    if payload.work_status not in {"open", "in_progress", "blocked", "done"}:
        raise HTTPException(400, "Invalid work status")
    item = KnowledgeItem(project_id=project_id, category=payload.category, title=payload.title.strip(),
        detail=payload.detail, owner=payload.owner.strip(), due_date=payload.due_date,
        priority=payload.priority, work_status=payload.work_status, evidence=payload.evidence,
        status="needs_review", verified=False)
    if not item.title:
        raise HTTPException(400, "Title is required")
    db.add(item); db.flush()
    log_event(db, project_id, f'{payload.category.title()} added: {item.title}', "item_created", item.id)
    db.commit(); db.refresh(item)
    return item_dict(item)

@app.post("/api/projects/{project_id}/activity")
def add_activity(project_id: int, payload: ActivityCreate, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Activity message is required")
    event = ActivityEvent(project_id=project_id, event_type=payload.event_type[:50], message=message[:2000])
    db.add(event); db.commit(); db.refresh(event)
    return {"id": event.id, "event_type": event.event_type, "message": event.message, "created_at": event.created_at.isoformat()}

@app.post("/api/projects/{project_id}/upload")
async def upload_document(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    filename = Path(file.filename or "upload.txt").name
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is too large. Maximum upload size is 10 MB.")
    try:
        content = extract_text(filename, raw)
    except Exception as e:
        raise HTTPException(400, f"Could not read document: {e}")
    doc = SourceDocument(project_id=project_id, filename=filename, content=content)
    db.add(doc); db.flush()
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
    log_event(db, project_id, f'Uploaded "{filename}" and extracted {len(extracted)} candidate knowledge items', "source_uploaded")
    db.commit(); db.refresh(doc)
    return {"document": {"id": doc.id, "filename": doc.filename, "characters": len(content), "chunks": len(chunks(content))},
            "extracted_count": len(extracted), "extraction_mode": extraction_mode}

@app.patch("/api/items/{item_id}")
def review_item(item_id: int, payload: ReviewUpdate, db: Session = Depends(get_db)):
    item = db.get(KnowledgeItem, item_id)
    if not item:
        raise HTTPException(404, "Knowledge item not found")
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in {None, "needs_review", "approved", "rejected", "unknown"}:
        raise HTTPException(400, "Invalid review status")
    if "priority" in changes and changes["priority"] not in {None, "low", "medium", "high", "critical"}:
        raise HTTPException(400, "Invalid priority")
    if "work_status" in changes and changes["work_status"] not in {None, "open", "in_progress", "blocked", "done"}:
        raise HTTPException(400, "Invalid work status")
    for key, value in changes.items():
        if value is not None and hasattr(item, key):
            setattr(item, key, value)
    if changes.get("status") == "approved":
        item.verified = True
    log_event(db, item.project_id, f'Updated "{item.title}" · review: {item.status} · work: {item.work_status}', "item_updated", item.id)
    db.commit(); db.refresh(item)
    return item_dict(item)

@app.get("/api/projects/{project_id}/handover")
def handover(project_id: int, db: Session = Depends(get_db)):
    p = get_project_or_404(project_id, db)
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id)).all()
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id)).all()
    events = db.scalars(select(ActivityEvent).where(ActivityEvent.project_id == project_id).order_by(ActivityEvent.created_at.desc()).limit(30)).all()
    approved = [i for i in items if i.status == "approved"]
    gaps = [i for i in items if i.status in {"needs_review", "unknown"}]
    categories = {c: [item_dict(i) for i in approved if i.category == c] for c in ["decision", "task", "risk", "question"]}
    tasks = [i for i in items if i.category == "task"]
    risks = [i for i in items if i.category == "risk"]
    unassigned = [i for i in tasks if not (i.owner or "").strip()]
    overdue = [i for i in tasks if i.due_date and i.due_date < datetime.now(timezone.utc).date().isoformat() and i.work_status != "done"]
    blocked = [i for i in items if i.work_status == "blocked"]
    open_tasks = [i for i in tasks if i.work_status != "done"]
    coverage = sum(bool(categories[c]) for c in categories)
    readiness = round((coverage / 4) * 45 + (len(approved) / max(1, len(items))) * 25 +
                      (len(tasks) - len(unassigned)) / max(1, len(tasks)) * 15 +
                      (len(tasks) - len(overdue)) / max(1, len(tasks)) * 15)
    next_steps = []
    if gaps: next_steps.append(f"Review {len(gaps)} candidate knowledge items")
    if unassigned: next_steps.append(f"Assign owners to {len(unassigned)} task(s)")
    if overdue: next_steps.append(f"Resolve {len(overdue)} overdue task(s)")
    if blocked: next_steps.append(f"Unblock {len(blocked)} blocked item(s)")
    if not next_steps: next_steps.append("Review the latest activity and confirm the handover is current")
    return {"project": project_dict(p), "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(docs), "approved_count": len(approved), "review_count": len(gaps),
        "readiness": max(0, min(100, readiness)), "categories": categories, "gaps": [item_dict(i) for i in gaps],
        "tasks": [item_dict(i) for i in tasks], "risks": [item_dict(i) for i in risks],
        "unassigned_tasks": [item_dict(i) for i in unassigned], "overdue_tasks": [item_dict(i) for i in overdue],
        "blocked_items": [item_dict(i) for i in blocked], "open_tasks": [item_dict(i) for i in open_tasks],
        "activity": [{"id": e.id, "event_type": e.event_type, "message": e.message, "created_at": e.created_at.isoformat()} for e in events],
        "next_steps": next_steps}

@app.get("/api/projects/{project_id}/handover.md")
def handover_markdown(project_id: int, db: Session = Depends(get_db)):
    data = handover(project_id, db)
    lines = [f"# Handover: {data['project']['name']}", "", data['project']['description'], "",
        f"Generated: {data['generated_at']}", f"Readiness checklist: {data['readiness']}%",
        f"Sources: {data['source_count']} | Approved: {data['approved_count']} | Needs review: {data['review_count']}", ""]
    for cat, title in [("decision", "Key decisions"), ("task", "Tasks and actions"), ("risk", "Risks and dependencies"), ("question", "Open questions")]:
        lines += [f"## {title}"]
        group = data["categories"][cat]
        if not group: lines.append("- No approved items yet.")
        for x in group:
            owner = f" | Owner: {x['owner']}" if x["owner"] else " | Owner: UNASSIGNED"
            due = f" | Due: {x['due_date']}" if x["due_date"] else ""
            lines.append(f"- **{x['title']}** — {x['detail']} [Work: {x['work_status']} | Priority: {x['priority']}{owner}{due}] (Source: document #{x['source_id']}; evidence: “{x['evidence']}”)")
        lines.append("")
    lines += ["## Unfinished work and ownership"]
    if not data["open_tasks"]: lines.append("- No unfinished tasks recorded.")
    for x in data["open_tasks"]:
        lines.append(f"- {x['title']} | Owner: {x['owner'] or 'UNASSIGNED'} | Status: {x['work_status']} | Priority: {x['priority']} | Due: {x['due_date'] or 'Not set'}")
    lines += ["", "## Risks requiring attention"]
    if not data["risks"]: lines.append("- No risks recorded.")
    for x in data["risks"]:
        lines.append(f"- {x['title']} | Priority: {x['priority']} | Owner: {x['owner'] or 'UNASSIGNED'} | Status: {x['work_status']}")
    lines += ["", "## Unassigned tasks"]
    for x in data["unassigned_tasks"]: lines.append(f"- {x['title']}")
    lines += ["", "## Blocked and overdue items"]
    for x in data["blocked_items"] + data["overdue_tasks"]: lines.append(f"- {x['title']} ({x['work_status']}, {x['due_date'] or 'no due date'})")
    lines += ["", "## Items requiring human review"]
    for x in data["gaps"]: lines.append(f"- [{x['status']}] {x['title']} (source document #{x['source_id']})")
    lines += ["", "## Recent project activity"]
    for x in data["activity"][:20]: lines.append(f"- {x['created_at']}: {x['message']}")
    lines += ["", "## Recommended next actions"] + [f"- {x}" for x in data["next_steps"]]
    return Response(content="\n".join(lines), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="continuityai-handover-{project_id}.md"'})
