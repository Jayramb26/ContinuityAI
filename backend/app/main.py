from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import os
import hashlib
import secrets
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from sqlalchemy import select, text, inspect
from sqlalchemy.orm import Session
from .database import SessionLocal
from .database import Base, engine, get_db
from .models import Project, SourceDocument, KnowledgeItem, ActivityEvent, BrandGuideline, BrandReview, ProjectMilestone, HandoverShare, ProjectMember, UserAccount, WorkspaceInvitation, TaskDependency, HandoverAcknowledgement
from .schemas import ProjectCreate, ReviewUpdate, KnowledgeCreate, ActivityCreate, BrandGuidelineCreate, BrandDecision, MilestoneCreate, MilestoneUpdate
from .ingestion import extract_text, chunks
from .knowledge import heuristic_extract, ai_extract
from .intelligence import analyze_project, answer_project_question
from .auth import issue_token, verify_token, hash_password, verify_password

Base.metadata.create_all(bind=engine)
UserAccount.__table__.create(bind=engine, checkfirst=True)
WorkspaceInvitation.__table__.create(bind=engine, checkfirst=True)
HandoverAcknowledgement.__table__.create(bind=engine, checkfirst=True)

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

    existing_sources = {c["name"] for c in inspect(engine).get_columns("source_documents")}
    if "last_reviewed_at" not in existing_sources:
        conn.execute(text("ALTER TABLE source_documents ADD COLUMN last_reviewed_at DATETIME"))

    # Existing demo workspaces remain accessible to the configured owner after membership enforcement.
    legacy_owner = os.getenv("DEMO_EMAIL", "").strip().lower()
    if legacy_owner:
        conn.execute(text("""
            INSERT INTO project_members (project_id, email, role, added_by, created_at)
            SELECT p.id, :email, 'owner', :email, CURRENT_TIMESTAMP
            FROM projects p
            WHERE NOT EXISTS (
                SELECT 1 FROM project_members pm WHERE pm.project_id = p.id
            )
        """), {"email": legacy_owner})

    existing_projects = {c["name"] for c in inspect(engine).get_columns("projects")}
    if "assigned_successor_email" not in existing_projects:
        conn.execute(text("ALTER TABLE projects ADD COLUMN assigned_successor_email VARCHAR(180) NOT NULL DEFAULT ''"))
    if "acceptance_due_date" not in existing_projects:
        conn.execute(text("ALTER TABLE projects ADD COLUMN acceptance_due_date VARCHAR(20) NOT NULL DEFAULT ''"))

    existing_events = {c["name"] for c in inspect(engine).get_columns("activity_events")}
    if "actor" not in existing_events:
        conn.execute(text("ALTER TABLE activity_events ADD COLUMN actor VARCHAR(180) NOT NULL DEFAULT 'demo-owner'"))

app = FastAPI(title="ContinuityAI API", version="0.3.0", description="Knowledge handover and human-reviewed brand governance")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,https://continuityai-web.onrender.com").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def root():
    return {
        "message": "ContinuityAI API is running",
        "status": "ok",
        "health": "/api/health",
        "docs": "/docs",
    }

@app.middleware("http")
async def demo_access_control(request: Request, call_next):
    """Require project membership and enforce workspace-specific roles."""
    path = request.url.path
    public_paths = {"/api/health", "/api/auth/config", "/api/auth/login", "/api/invitations/accept"}
    shared_public = path.startswith("/api/shared/")
    if path.startswith("/api/") and path not in public_paths and not shared_public and request.method != "OPTIONS":
        secret = os.getenv("AUTH_SECRET", "")
        if secret:
            authorization = request.headers.get("Authorization", "")
            token = authorization.split(" ", 1)[1].strip() if authorization.lower().startswith("bearer ") else ""
            claims = verify_token(token, secret)
            if not claims:
                return JSONResponse(status_code=401, content={"detail": "Sign in to access this workspace."})
            request.state.auth = claims
            email = str(claims.get("sub", "")).strip().lower()
            project_id = None
            match = re.match(r"^/api/projects/(\d+)(?:/|$)", path)
            if match:
                project_id = int(match.group(1))
            else:
                patterns = [(r"^/api/items/(\d+)(?:/dependencies(?:/\d+)?)?$", KnowledgeItem), (r"^/api/milestones/(\d+)$", ProjectMilestone), (r"^/api/sources/(\d+)/review$", SourceDocument)]
                for pattern, model in patterns:
                    found = re.match(pattern, path)
                    if found:
                        with SessionLocal() as lookup:
                            row = lookup.get(model, int(found.group(1)))
                            project_id = row.project_id if row else None
                        break
            if project_id is not None:
                with SessionLocal() as lookup:
                    member = lookup.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.email == email))
                if not member:
                    return JSONResponse(status_code=404, content={"detail": "You do not have access to this workspace."})
                request.state.workspace_role = member.role
                if path.endswith("/handover-assignment") and member.role != "owner":
                    return JSONResponse(status_code=403, content={"detail": "Only workspace owners can assign the handover successor."})
                if (path.endswith("/members") or "/members/" in path or "/invitations" in path) and member.role != "owner":
                    return JSONResponse(status_code=403, content={"detail": "Only workspace owners can manage members."})
                if member.role == "viewer" and request.method not in {"GET", "HEAD", "OPTIONS"} and not (request.method == "POST" and (path.endswith("/ask") or path.endswith("/acknowledgements"))):
                    return JSONResponse(status_code=403, content={"detail": "Viewer access is read-only in this workspace."})
            elif path == "/api/projects" and request.method == "POST" and claims.get("role") == "viewer":
                return JSONResponse(status_code=403, content={"detail": "Viewer accounts cannot create workspaces."})
            if path.startswith("/api/brand/") and request.method not in {"GET", "HEAD", "OPTIONS"} and claims.get("role") != "owner":
                return JSONResponse(status_code=403, content={"detail": "Only demo owners can manage brand governance."})
    return await call_next(request)


@app.get("/api/auth/config")
def auth_config():
    return {"auth_enabled": bool(os.getenv("AUTH_SECRET"))}


@app.post("/api/auth/login")
def auth_login(payload: dict, db: Session = Depends(get_db)):
    secret = os.getenv("AUTH_SECRET", "")
    if not secret:
        raise HTTPException(503, "Authentication is not configured")
    UserAccount.__table__.create(bind=engine, checkfirst=True)
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not email or not password:
        raise HTTPException(400, "Email and password are required.")
    account = db.scalar(select(UserAccount).where(UserAccount.email == email))
    if account and verify_password(password, account.password_hash):
        return {"access_token": issue_token(email, secret, role="viewer"), "token_type": "bearer", "expires_in": 28800, "role": "viewer"}
    # Keep the shared judge demo and optional role-specific demo accounts working.
    accounts = [
        ("DEMO_EMAIL", "DEMO_PASSWORD", "owner"),
        ("DEMO_EDITOR_EMAIL", "DEMO_EDITOR_PASSWORD", "editor"),
        ("DEMO_VIEWER_EMAIL", "DEMO_VIEWER_PASSWORD", "viewer"),
    ]
    for email_key, password_key, role in accounts:
        configured_email = os.getenv(email_key, "").strip().lower()
        configured_password = os.getenv(password_key, "")
        if configured_email and configured_password and secrets.compare_digest(email, configured_email) and secrets.compare_digest(password, configured_password):
            return {"access_token": issue_token(email, secret, role=role), "token_type": "bearer", "expires_in": 28800, "role": role}
    raise HTTPException(401, "Incorrect email or password")


@app.post("/api/projects/{project_id}/invitations")
def create_workspace_invitation(project_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    email = str(payload.get("email", "")).strip().lower()
    role = str(payload.get("role", "viewer")).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email address.")
    if role not in {"editor", "viewer"}:
        raise HTTPException(400, "Invitations can grant editor or viewer access only.")
    existing_member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.email == email))
    if existing_member:
        raise HTTPException(409, "This person is already a workspace member. Update their role in Team access.")
    now = datetime.now(timezone.utc)
    pending = db.scalars(select(WorkspaceInvitation).where(
        WorkspaceInvitation.project_id == project_id,
        WorkspaceInvitation.email == email,
        WorkspaceInvitation.accepted_at.is_(None),
        WorkspaceInvitation.revoked_at.is_(None)
    )).all()
    for old in pending:
        old.revoked_at = now
    token = secrets.token_urlsafe(32)
    actor = str((getattr(request.state, "auth", None) or {}).get("sub", ""))
    invitation = WorkspaceInvitation(project_id=project_id, email=email, role=role,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_by=actor, expires_at=now + timedelta(days=7))
    db.add(invitation)
    log_event(db, project_id, f"Workspace invitation created for {email} as {role}", "invitation_created", actor=actor)
    db.commit()
    db.refresh(invitation)
    return {"id": invitation.id, "email": email, "role": role, "token": token,
        "expires_at": invitation.expires_at.isoformat(), "expires_in_days": 7}


@app.get("/api/projects/{project_id}/invitations")
def list_workspace_invitations(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    rows = db.scalars(select(WorkspaceInvitation).where(
        WorkspaceInvitation.project_id == project_id,
        WorkspaceInvitation.accepted_at.is_(None),
        WorkspaceInvitation.revoked_at.is_(None)
    ).order_by(WorkspaceInvitation.created_at.desc())).all()
    return [{"id": row.id, "email": row.email, "role": row.role,
        "created_by": row.created_by, "created_at": row.created_at.isoformat(),
        "expires_at": row.expires_at.isoformat()} for row in rows]


@app.delete("/api/projects/{project_id}/invitations/{invitation_id}")
def revoke_workspace_invitation(project_id: int, invitation_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.scalar(select(WorkspaceInvitation).where(
        WorkspaceInvitation.id == invitation_id,
        WorkspaceInvitation.project_id == project_id))
    if not row:
        raise HTTPException(404, "Invitation not found.")
    if row.accepted_at:
        raise HTTPException(409, "This invitation has already been accepted.")
    row.revoked_at = datetime.now(timezone.utc)
    actor = str((getattr(request.state, "auth", None) or {}).get("sub", ""))
    log_event(db, project_id, f"Workspace invitation for {row.email} revoked", "invitation_revoked", actor=actor)
    db.commit()
    return {"status": "revoked"}


@app.post("/api/invitations/accept")
def accept_workspace_invitation(payload: dict, db: Session = Depends(get_db)):
    secret = os.getenv("AUTH_SECRET", "")
    if not secret:
        raise HTTPException(503, "Authentication is not configured")
    token = str(payload.get("token", "")).strip()
    password = str(payload.get("password", ""))
    if not token:
        raise HTTPException(400, "Invitation token is required.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    invitation = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == token_hash))
    if not invitation or invitation.revoked_at or invitation.accepted_at:
        raise HTTPException(404, "This invitation is invalid, revoked, or already used.")
    expiry = invitation.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(410, "This invitation has expired. Ask the workspace owner for a new one.")
    account = db.scalar(select(UserAccount).where(UserAccount.email == invitation.email))
    if not account:
        if len(password) < 12:
            raise HTTPException(400, "Create a password with at least 12 characters.")
        account = UserAccount(email=invitation.email, password_hash=hash_password(password))
        db.add(account)
    elif not password or not verify_password(password, account.password_hash):
        raise HTTPException(401, "Enter the existing account password to accept this invitation.")
    member = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == invitation.project_id,
        ProjectMember.email == invitation.email))
    if member:
        member.role = invitation.role
    else:
        db.add(ProjectMember(project_id=invitation.project_id, email=invitation.email,
            role=invitation.role, added_by=invitation.created_by))
    invitation.accepted_at = datetime.now(timezone.utc)
    log_event(db, invitation.project_id, f"{invitation.email} accepted a workspace invitation as {invitation.role}",
        "invitation_accepted", actor=invitation.email)
    db.commit()
    access_token = issue_token(invitation.email, secret, role="viewer")
    return {"status": "accepted", "email": invitation.email, "role": invitation.role,
        "access_token": access_token, "token_type": "bearer", "expires_in": 28800}


@app.get("/api/auth/me")
def auth_me(request: Request):
    claims = getattr(request.state, "auth", None)
    if not claims:
        raise HTTPException(401, "No active authenticated session")
    return {"email": claims["sub"], "role": claims.get("role", "viewer")}




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


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "ContinuityAI", "version": "0.3.0"}

def project_dict(p):
    return {"id": p.id, "name": p.name, "description": p.description, "assigned_successor_email": p.assigned_successor_email or "", "acceptance_due_date": p.acceptance_due_date or "", "created_at": p.created_at.isoformat()}

def item_dict(i):
    return {"id": i.id, "category": i.category, "title": i.title, "detail": i.detail, "source_id": i.source_id,
            "evidence": i.evidence, "status": i.status, "verified": i.verified, "owner": i.owner or "",
            "due_date": i.due_date or "", "priority": i.priority or "medium", "work_status": i.work_status or "open",
            "created_at": i.created_at.isoformat()}

def log_event(db, project_id, message, event_type="update", item_id=None, actor="demo-owner"):
    db.add(ActivityEvent(project_id=project_id, item_id=item_id, event_type=event_type, message=message, actor=actor))

def get_project_or_404(project_id, db):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project

@app.post("/api/projects")
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Project name is required")
    p = Project(name=payload.name.strip(), description=payload.description.strip())
    db.add(p); db.flush()
    claims = getattr(request.state, "auth", None) or {}
    owner_email = str(claims.get("sub", os.getenv("DEMO_EMAIL", "demo-owner"))).strip().lower()
    db.add(ProjectMember(project_id=p.id, email=owner_email, role="owner", added_by=owner_email))
    log_event(db, p.id, f'Workspace "{p.name}" created', "workspace_created", actor=owner_email)
    db.commit(); db.refresh(p)
    return project_dict(p)

@app.patch("/api/projects/{project_id}/handover-assignment")
def update_handover_assignment(project_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    require_share_owner(request)
    project = get_project_or_404(project_id, db)
    email = str(payload.get("email", "")).strip().lower()
    due_date = str(payload.get("acceptance_due_date", "")).strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid successor email address.")
    if email and not db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.email == email)):
        raise HTTPException(400, "The designated successor must already be a member of this workspace.")
    if due_date:
        try: datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError: raise HTTPException(400, "Acceptance deadline must use YYYY-MM-DD.")
    project.assigned_successor_email = email
    project.acceptance_due_date = due_date
    claims = getattr(request.state, "auth", None) or {}
    message = f"Handover successor assigned to {email}" if email else "Designated handover successor cleared"
    if due_date: message += f" · acceptance due {due_date}"
    log_event(db, project_id, message, "handover_assignment_updated", actor=claims.get("sub", "demo-owner"))
    db.commit(); db.refresh(project)
    return {"project": project_dict(project), "message": "Handover assignment saved."}


@app.get("/api/projects")
def list_projects(request: Request, db: Session = Depends(get_db)):
    if not os.getenv("AUTH_SECRET"):
        rows = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    else:
        email = str((getattr(request.state, "auth", None) or {}).get("sub", "")).strip().lower()
        ids = db.scalars(select(ProjectMember.project_id).where(ProjectMember.email == email)).all()
        rows = db.scalars(select(Project).where(Project.id.in_(ids)).order_by(Project.created_at.desc())).all() if ids else []
    return [project_dict(p) for p in rows]

@app.get("/api/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = get_project_or_404(project_id, db)
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id)).all()
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id).order_by(KnowledgeItem.id.desc())).all()
    events = db.scalars(select(ActivityEvent).where(ActivityEvent.project_id == project_id).order_by(ActivityEvent.created_at.desc()).limit(50)).all()
    return {**project_dict(p),
            "documents": [{"id": d.id, "filename": d.filename, "uploaded_at": d.uploaded_at.isoformat()} for d in docs],
            "items": [item_dict(i) for i in items],
            "activity": [{"id": e.id, "event_type": e.event_type, "message": e.message, "actor": e.actor, "item_id": e.item_id, "created_at": e.created_at.isoformat()} for e in events]}

def member_dict(row):
    return {"id": row.id, "email": row.email, "role": row.role, "added_by": row.added_by,
            "created_at": row.created_at.isoformat()}


@app.get("/api/projects/{project_id}/members")
def list_project_members(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    rows = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.created_at.asc())).all()
    return [member_dict(row) for row in rows]


@app.post("/api/projects/{project_id}/members")
def add_project_member(project_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    email = str(payload.get("email", "")).strip().lower()
    role = str(payload.get("role", "viewer")).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email address.")
    if role not in {"editor", "viewer"}:
        raise HTTPException(400, "New members can be editors or viewers.")
    configured = {os.getenv(key, "").strip().lower() for key in ["DEMO_EMAIL", "DEMO_EDITOR_EMAIL", "DEMO_VIEWER_EMAIL"] if os.getenv(key, "").strip()}
    if email not in configured:
        raise HTTPException(400, "This email has no configured ContinuityAI login. Configure a demo account before assigning workspace access; no email invitation is sent.")
    row = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.email == email))
    claims = getattr(request.state, "auth", None) or {}
    if row:
        row.role = role
        action = "updated"
    else:
        row = ProjectMember(project_id=project_id, email=email, role=role, added_by=claims.get("sub", ""))
        db.add(row)
        action = "added"
    log_event(db, project_id, f"Workspace member {email} {action} as {role}", f"member_{action}", actor=claims.get("sub", ""))
    db.commit(); db.refresh(row)
    return member_dict(row)


@app.patch("/api/projects/{project_id}/members/{member_id}")
def update_project_member(project_id: int, member_id: int, payload: dict, db: Session = Depends(get_db)):
    row = db.get(ProjectMember, member_id)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "Workspace member not found.")
    role = str(payload.get("role", "")).strip().lower()
    if role not in {"editor", "viewer"}:
        raise HTTPException(400, "Role must be editor or viewer.")
    if row.role == "owner":
        raise HTTPException(400, "The workspace owner role cannot be changed in this demo.")
    row.role = role
    log_event(db, project_id, f"Workspace member {row.email} role changed to {role}", "member_role_updated")
    db.commit(); db.refresh(row)
    return member_dict(row)


@app.delete("/api/projects/{project_id}/members/{member_id}")
def remove_project_member(project_id: int, member_id: int, db: Session = Depends(get_db)):
    row = db.get(ProjectMember, member_id)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "Workspace member not found.")
    if row.role == "owner":
        raise HTTPException(400, "The workspace owner cannot be removed.")
    email = row.email
    db.delete(row)
    log_event(db, project_id, f"Workspace member {email} removed", "member_removed")
    db.commit()
    return {"removed": member_id}


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


def task_dependency_dict(row, db):
    task = db.get(KnowledgeItem, row.item_id)
    prerequisite = db.get(KnowledgeItem, row.depends_on_item_id)
    if not task or not prerequisite:
        return None
    return {"id": row.id, "item_id": row.item_id, "depends_on_item_id": row.depends_on_item_id,
        "task_title": task.title, "prerequisite_title": prerequisite.title,
        "prerequisite_status": prerequisite.work_status, "satisfied": prerequisite.work_status == "done"}


def would_create_dependency_cycle(project_id, item_id, prerequisite_id, db):
    pending, visited = [prerequisite_id], set()
    while pending:
        current = pending.pop()
        if current == item_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(db.scalars(select(TaskDependency.depends_on_item_id).where(
            TaskDependency.project_id == project_id, TaskDependency.item_id == current
        )).all())
    return False


@app.post("/api/items/{item_id}/dependencies")
def add_task_dependency(item_id: int, payload: dict, db: Session = Depends(get_db)):
    item = db.get(KnowledgeItem, item_id)
    if not item or item.category != "task":
        raise HTTPException(404, "Task not found.")
    try:
        prerequisite_id = int(payload.get("depends_on_item_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Choose a valid prerequisite task.")
    prerequisite = db.get(KnowledgeItem, prerequisite_id)
    if not prerequisite or prerequisite.category != "task" or prerequisite.project_id != item.project_id:
        raise HTTPException(400, "Prerequisite must be another task in this workspace.")
    if prerequisite.id == item.id:
        raise HTTPException(400, "A task cannot depend on itself.")
    existing = db.scalar(select(TaskDependency).where(
        TaskDependency.item_id == item.id, TaskDependency.depends_on_item_id == prerequisite.id))
    if existing:
        raise HTTPException(409, "This task dependency already exists.")
    if would_create_dependency_cycle(item.project_id, item.id, prerequisite.id, db):
        raise HTTPException(400, "This dependency would create a circular task chain.")
    row = TaskDependency(project_id=item.project_id, item_id=item.id, depends_on_item_id=prerequisite.id)
    db.add(row)
    log_event(db, item.project_id, f'Task "{item.title}" now depends on "{prerequisite.title}"', "task_dependency_added", item.id)
    db.commit(); db.refresh(row)
    return task_dependency_dict(row, db)


@app.delete("/api/items/{item_id}/dependencies/{dependency_id}")
def remove_task_dependency(item_id: int, dependency_id: int, db: Session = Depends(get_db)):
    item = db.get(KnowledgeItem, item_id)
    if not item or item.category != "task":
        raise HTTPException(404, "Task not found.")
    row = db.scalar(select(TaskDependency).where(
        TaskDependency.id == dependency_id, TaskDependency.item_id == item_id,
        TaskDependency.project_id == item.project_id))
    if not row:
        raise HTTPException(404, "Task dependency not found.")
    prerequisite = db.get(KnowledgeItem, row.depends_on_item_id)
    db.delete(row)
    log_event(db, item.project_id, f'Task dependency removed: "{item.title}" no longer waits for "{prerequisite.title if prerequisite else "another task"}"', "task_dependency_removed", item.id)
    db.commit()
    return {"deleted": dependency_id}


def milestone_dict(row, db):
    import json
    ids = json.loads(row.item_ids or "[]")
    linked = [db.get(KnowledgeItem, item_id) for item_id in ids]
    linked = [item for item in linked if item and item.project_id == row.project_id]
    total = len(linked)
    completed = sum(1 for item in linked if item.work_status == "done")
    return {"id": row.id, "project_id": row.project_id, "name": row.name,
        "description": row.description, "owner": row.owner or "", "due_date": row.due_date or "",
        "status": row.status, "item_ids": [item.id for item in linked],
        "linked_item_count": total, "completed_item_count": completed,
        "progress": round(completed / total * 100) if total else 0,
        "created_at": row.created_at.isoformat()}


def validate_milestone_items(project_id, item_ids, db):
    ids = list(dict.fromkeys(item_ids or []))
    if ids:
        found = db.scalars(select(KnowledgeItem).where(
            KnowledgeItem.id.in_(ids), KnowledgeItem.project_id == project_id
        )).all()
        if len(found) != len(ids):
            raise HTTPException(400, "Every linked item must belong to this project.")
    return ids


@app.get("/api/projects/{project_id}/milestones")
def list_milestones(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    rows = db.scalars(select(ProjectMilestone).where(
        ProjectMilestone.project_id == project_id
    ).order_by(ProjectMilestone.due_date.asc(), ProjectMilestone.id.asc())).all()
    return [milestone_dict(row, db) for row in rows]


@app.post("/api/projects/{project_id}/milestones")
def create_milestone(project_id: int, payload: MilestoneCreate, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    if not payload.name.strip():
        raise HTTPException(400, "Milestone name is required.")
    if payload.status not in {"planned", "in_progress", "blocked", "completed"}:
        raise HTTPException(400, "Invalid milestone status.")
    ids = validate_milestone_items(project_id, payload.item_ids, db)
    import json
    row = ProjectMilestone(project_id=project_id, name=payload.name.strip(),
        description=payload.description.strip(), owner=payload.owner.strip(),
        due_date=payload.due_date.strip(), status=payload.status, item_ids=json.dumps(ids))
    db.add(row); db.flush()
    log_event(db, project_id, f'Milestone created: {row.name}', "milestone_created")
    db.commit(); db.refresh(row)
    return milestone_dict(row, db)


@app.patch("/api/milestones/{milestone_id}")
def update_milestone(milestone_id: int, payload: MilestoneUpdate, db: Session = Depends(get_db)):
    row = db.get(ProjectMilestone, milestone_id)
    if not row:
        raise HTTPException(404, "Milestone not found.")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None and not changes["name"].strip():
        raise HTTPException(400, "Milestone name cannot be empty.")
    if "status" in changes and changes["status"] not in {"planned", "in_progress", "blocked", "completed"}:
        raise HTTPException(400, "Invalid milestone status.")
    if "item_ids" in changes and changes["item_ids"] is not None:
        import json
        changes["item_ids"] = json.dumps(validate_milestone_items(row.project_id, changes["item_ids"], db))
    for key, value in changes.items():
        if value is not None:
            setattr(row, key, value.strip() if isinstance(value, str) else value)
    log_event(db, row.project_id, f'Milestone updated: {row.name}', "milestone_updated")
    db.commit(); db.refresh(row)
    return milestone_dict(row, db)


@app.delete("/api/milestones/{milestone_id}")
def delete_milestone(milestone_id: int, db: Session = Depends(get_db)):
    row = db.get(ProjectMilestone, milestone_id)
    if not row:
        raise HTTPException(404, "Milestone not found.")
    project_id, name = row.project_id, row.name
    db.delete(row)
    log_event(db, project_id, f'Milestone deleted: {name}', "milestone_deleted")
    db.commit()
    return {"deleted": milestone_id}

@app.post("/api/projects/{project_id}/activity")
def add_activity(project_id: int, payload: ActivityCreate, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Activity message is required")
    event = ActivityEvent(project_id=project_id, event_type=payload.event_type[:50], message=message[:2000], actor="demo-owner")
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

@app.get("/api/projects/{project_id}/acknowledgements")
def list_handover_acknowledgements(project_id: int, request: Request, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    rows = db.scalars(select(HandoverAcknowledgement).where(
        HandoverAcknowledgement.project_id == project_id
    ).order_by(HandoverAcknowledgement.updated_at.desc())).all()
    workspace_members = db.scalars(select(ProjectMember).where(
        ProjectMember.project_id == project_id
    ).order_by(ProjectMember.created_at.asc())).all()
    current_email = str((getattr(request.state, "auth", None) or {}).get("sub", "")).strip().lower()
    latest_change = db.scalar(select(ActivityEvent).where(
        ActivityEvent.project_id == project_id,
        ~ActivityEvent.event_type.like("handover_%")
    ).order_by(ActivityEvent.created_at.desc()).limit(1))
    latest_change_at = latest_change.created_at if latest_change else None
    tracked_changes = db.scalars(select(ActivityEvent).where(
        ActivityEvent.project_id == project_id,
        ~ActivityEvent.event_type.like("handover_%")
    ).order_by(ActivityEvent.created_at.asc())).all()
    acknowledgement_items = []
    for row in rows:
        changes_after_ack = [event for event in tracked_changes if event.created_at > row.updated_at]
        stale = bool(changes_after_ack)
        acknowledgement_items.append({
            "id": row.id, "email": row.email, "status": row.status, "note": row.note,
            "is_stale": stale,
            "stale_since": changes_after_ack[0].created_at.isoformat() if stale else None,
            "stale_reason": "Tracked project activity changed after this response." if stale else "",
            "changes_after_ack": [{
                "event_type": event.event_type, "message": event.message,
                "created_at": event.created_at.isoformat()
            } for event in changes_after_ack[-10:]],
            "changes_after_ack_count": len(changes_after_ack),
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()
        })
    return {
        "current_user_email": current_email,
        "latest_change_at": latest_change_at.isoformat() if latest_change_at else None,
        "members": [{
            "email": member.email, "role": member.role, "added_at": member.created_at.isoformat()
        } for member in workspace_members],
        "items": acknowledgement_items
    }


@app.post("/api/projects/{project_id}/acknowledgements")
def submit_handover_acknowledgement(project_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    claims = getattr(request.state, "auth", None) or {}
    email = str(claims.get("sub", "")).strip().lower()
    if not email:
        raise HTTPException(401, "Sign in before responding to this handover.")
    status = str(payload.get("status", "accepted")).strip().lower()
    note = str(payload.get("note", "")).strip()
    if status not in {"accepted", "needs_follow_up"}:
        raise HTTPException(400, "Choose accepted or needs_follow_up.")
    if len(note) > 2000:
        raise HTTPException(400, "The handover note must be 2,000 characters or fewer.")
    if status == "needs_follow_up" and not note:
        raise HTTPException(400, "Add a short note describing what needs clarification.")
    row = db.scalar(select(HandoverAcknowledgement).where(
        HandoverAcknowledgement.project_id == project_id,
        HandoverAcknowledgement.email == email
    ))
    now = datetime.now(timezone.utc)
    if row:
        row.status = status
        row.note = note
        row.updated_at = now
        action = "updated"
    else:
        row = HandoverAcknowledgement(project_id=project_id, email=email, status=status, note=note)
        db.add(row)
        action = "submitted"
    label = "accepted the handover" if status == "accepted" else "requested handover clarification"
    log_event(db, project_id, f"{email} {label}" + (f": {note}" if note else ""), f"handover_{status}", actor=email)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "email": row.email, "status": row.status, "note": row.note,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
            "message": f"Handover response {action}."}


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
    dependency_rows = db.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id).order_by(TaskDependency.id.asc())).all()
    task_dependencies = [value for value in (task_dependency_dict(row, db) for row in dependency_rows) if value]
    waiting_tasks = {value["item_id"] for value in task_dependencies if not value["satisfied"]}
    assigned_email = (p.assigned_successor_email or "").strip().lower()
    successor_ack = db.scalar(select(HandoverAcknowledgement).where(HandoverAcknowledgement.project_id == project_id, HandoverAcknowledgement.email == assigned_email)) if assigned_email else None
    latest_project_change = db.scalar(select(ActivityEvent).where(ActivityEvent.project_id == project_id, ~ActivityEvent.event_type.like("handover_%")).order_by(ActivityEvent.created_at.desc()).limit(1))
    ack_is_stale = bool(successor_ack and latest_project_change and
        (latest_project_change.created_at.replace(tzinfo=timezone.utc) if latest_project_change.created_at.tzinfo is None else latest_project_change.created_at) >
        (successor_ack.updated_at.replace(tzinfo=timezone.utc) if successor_ack.updated_at.tzinfo is None else successor_ack.updated_at))
    deadline = (p.acceptance_due_date or "").strip()
    deadline_passed = bool(deadline and deadline < datetime.now(timezone.utc).date().isoformat())
    if not assigned_email: assignment_status = "unassigned"
    elif successor_ack and successor_ack.status == "accepted" and not ack_is_stale: assignment_status = "accepted"
    elif ack_is_stale: assignment_status = "review_required"
    elif deadline_passed: assignment_status = "overdue"
    else: assignment_status = "awaiting_acceptance"
    handover_assignment = {
        "email": assigned_email, "acceptance_due_date": deadline, "status": assignment_status,
        "is_overdue": deadline_passed and assignment_status != "accepted",
        "acknowledged_at": successor_ack.updated_at.isoformat() if successor_ack else None,
        "acknowledgement_status": successor_ack.status if successor_ack else None
    }
    milestone_rows = db.scalars(select(ProjectMilestone).where(ProjectMilestone.project_id == project_id).order_by(ProjectMilestone.due_date.asc())).all()
    milestones = [milestone_dict(row, db) for row in milestone_rows]
    today = datetime.now(timezone.utc).date().isoformat()
    overdue_milestones = [m for m in milestones if m["due_date"] and m["due_date"] < today and m["status"] != "completed"]
    coverage = sum(bool(categories[c]) for c in categories)
    # Keep the readiness score explainable: every point belongs to a visible factor.
    dependency_score = (round((len(task_dependencies) - sum(not dep["satisfied"] for dep in task_dependencies)) /
                              max(1, len(task_dependencies)) * 10) if task_dependencies else 10)
    readiness_breakdown = {
        "knowledge_coverage": {"label": "Knowledge coverage", "score": round(coverage / 4 * 40), "max": 40,
                               "detail": f"{coverage} of 4 knowledge categories have approved items"},
        "human_approval": {"label": "Human approval", "score": round(len(approved) / max(1, len(items)) * 25), "max": 25,
                           "detail": f"{len(approved)} of {len(items)} knowledge items are approved"},
        "task_ownership": {"label": "Task ownership", "score": round((len(tasks) - len(unassigned)) / max(1, len(tasks)) * 10), "max": 10,
                           "detail": f"{len(tasks) - len(unassigned)} of {len(tasks)} tasks have an owner"},
        "schedule_health": {"label": "Schedule health", "score": round((len(tasks) - len(overdue)) / max(1, len(tasks)) * 10), "max": 10,
                            "detail": f"{len(tasks) - len(overdue)} of {len(tasks)} tasks are not overdue"},
        "dependency_health": {"label": "Dependency health", "score": dependency_score, "max": 10,
                              "detail": (f"{sum(dep['satisfied'] for dep in task_dependencies)} of {len(task_dependencies)} prerequisites are complete"
                                         if task_dependencies else "No explicit task dependencies recorded")},
        "blocker_health": {"label": "Blocker health", "score": round((len(items) - len(blocked)) / max(1, len(items)) * 5), "max": 5,
                           "detail": f"{len(items) - len(blocked)} of {len(items)} items are not blocked"},
    }
    readiness = sum(part["score"] for part in readiness_breakdown.values())
    next_steps = []
    if gaps: next_steps.append(f"Review {len(gaps)} candidate knowledge items")
    if unassigned: next_steps.append(f"Assign owners to {len(unassigned)} task(s)")
    if overdue: next_steps.append(f"Resolve {len(overdue)} overdue task(s)")
    if blocked: next_steps.append(f"Unblock {len(blocked)} blocked item(s)")
    if overdue_milestones: next_steps.append(f"Review {len(overdue_milestones)} overdue milestone(s)")
    if waiting_tasks: next_steps.append(f"Resolve {len(waiting_tasks)} task(s) waiting on prerequisites")
    if not next_steps: next_steps.append("Review the latest activity and confirm the handover is current")
    return {"project": project_dict(p), "handover_assignment": handover_assignment, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(docs), "approved_count": len(approved), "review_count": len(gaps),
        "readiness": max(0, min(100, readiness)), "readiness_breakdown": readiness_breakdown,
        "categories": categories, "gaps": [item_dict(i) for i in gaps],
        "tasks": [item_dict(i) for i in tasks], "risks": [item_dict(i) for i in risks],
        "unassigned_tasks": [item_dict(i) for i in unassigned], "overdue_tasks": [item_dict(i) for i in overdue],
        "blocked_items": [item_dict(i) for i in blocked], "open_tasks": [item_dict(i) for i in open_tasks],
        "milestones": milestones, "overdue_milestones": overdue_milestones,
        "task_dependencies": task_dependencies,
        "waiting_tasks": [item_dict(i) for i in tasks if i.id in waiting_tasks],
        "activity": [{"id": e.id, "event_type": e.event_type, "message": e.message, "actor": e.actor, "created_at": e.created_at.isoformat()} for e in events],
        "next_steps": next_steps}


def require_share_owner(request: Request):
    if os.getenv("AUTH_SECRET"):
        claims = getattr(request.state, "auth", None) or {}
        if getattr(request.state, "workspace_role", claims.get("role")) != "owner":
            raise HTTPException(403, "Only workspace owners can create or revoke handover links.")


def active_share_from_token(token: str, db: Session):
    if not token or len(token) > 200:
        raise HTTPException(404, "Handover link is invalid or unavailable.")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    share = db.scalar(select(HandoverShare).where(HandoverShare.token_hash == digest))
    if not share or share.revoked_at:
        raise HTTPException(404, "Handover link is invalid or unavailable.")
    expires = share.expires_at.replace(tzinfo=timezone.utc) if share.expires_at.tzinfo is None else share.expires_at
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(410, "This handover link has expired.")
    return share


@app.post("/api/projects/{project_id}/shares")
def create_handover_share(project_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    require_share_owner(request)
    project = get_project_or_404(project_id, db)
    try:
        hours = int(payload.get("expires_in_hours", 72))
    except (TypeError, ValueError):
        raise HTTPException(400, "Expiry must be a whole number of hours.")
    if hours < 1 or hours > 720:
        raise HTTPException(400, "Share links must expire between 1 hour and 30 days.")
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    claims = getattr(request.state, "auth", None) or {}
    row = HandoverShare(project_id=project_id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        created_by=claims.get("sub", "demo-owner"), expires_at=expires_at)
    db.add(row)
    log_event(db, project_id, f"Read-only handover link created (expires {expires_at.isoformat()})", "handover_share_created", actor=claims.get("sub", "demo-owner"))
    db.commit()
    return {"id": row.id, "token": raw_token, "expires_at": expires_at.isoformat(),
            "access": "read_only", "message": "Copy this link now. The secret token is shown only once."}


@app.get("/api/projects/{project_id}/shares")
def list_handover_shares(project_id: int, request: Request, db: Session = Depends(get_db)):
    require_share_owner(request)
    get_project_or_404(project_id, db)
    rows = db.scalars(select(HandoverShare).where(HandoverShare.project_id == project_id)
        .order_by(HandoverShare.created_at.desc())).all()
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
        result.append({"id": row.id, "created_by": row.created_by,
            "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat(),
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "status": "revoked" if row.revoked_at else ("expired" if expiry <= now else "active")})
    return result


@app.delete("/api/projects/{project_id}/shares/{share_id}")
def revoke_handover_share(project_id: int, share_id: int, request: Request, db: Session = Depends(get_db)):
    require_share_owner(request)
    row = db.get(HandoverShare, share_id)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "Handover link not found.")
    if not row.revoked_at:
        row.revoked_at = datetime.now(timezone.utc)
        claims = getattr(request.state, "auth", None) or {}
        log_event(db, project_id, "Read-only handover link revoked", "handover_share_revoked", actor=claims.get("sub", "demo-owner"))
        db.commit()
    return {"id": row.id, "status": "revoked", "revoked_at": row.revoked_at.isoformat()}


@app.get("/api/shared/{token}")
def read_shared_handover(token: str, db: Session = Depends(get_db)):
    share = active_share_from_token(token, db)
    data = handover(share.project_id, db)
    return {"share": {"expires_at": share.expires_at.isoformat(), "access": "read_only"},
            "handover": data}


@app.get("/api/projects/{project_id}/handover.md")
def handover_markdown(project_id: int, db: Session = Depends(get_db)):
    data = handover(project_id, db)
    lines = [f"# Handover: {data['project']['name']}", "", data['project']['description'], "",
        f"Generated: {data['generated_at']}", f"Readiness checklist: {data['readiness']}%",
        f"Sources: {data['source_count']} | Approved: {data['approved_count']} | Needs review: {data['review_count']}", "",
        "## Readiness score breakdown"]
    for part in data.get("readiness_breakdown", {}).values():
        lines.append(f"- {part['label']}: {part['score']}/{part['max']} — {part['detail']}")
    lines.append("")
    for cat, title in [("decision", "Key decisions"), ("task", "Tasks and actions"), ("risk", "Risks and dependencies"), ("question", "Open questions")]:
        lines += [f"## {title}"]
        group = data["categories"][cat]
        if not group: lines.append("- No approved items yet.")
        for x in group:
            owner = f" | Owner: {x['owner']}" if x["owner"] else " | Owner: UNASSIGNED"
            due = f" | Due: {x['due_date']}" if x["due_date"] else ""
            lines.append(f"- **{x['title']}** — {x['detail']} [Work: {x['work_status']} | Priority: {x['priority']}{owner}{due}] (Source: document #{x['source_id']}; evidence: “{x['evidence']}”)")
        lines.append("")
    lines += ["## Project milestones"]
    if not data.get("milestones"): lines.append("- No milestones recorded.")
    for m in data.get("milestones", []):
        lines.append(f"- **{m['name']}** | Status: {m['status']} | Progress: {m['progress']}% ({m['completed_item_count']}/{m['linked_item_count']} linked tasks) | Owner: {m['owner'] or 'UNASSIGNED'} | Due: {m['due_date'] or 'Not set'}")
    lines += ["", "## Task dependencies"]
    dependencies = data.get("task_dependencies", [])
    if not dependencies: lines.append("- No explicit task dependencies recorded.")
    for dep in dependencies:
        state = "satisfied" if dep["satisfied"] else "waiting"
        lines.append("- **" + dep["task_title"] + "** depends on **" + dep["prerequisite_title"] + "** (" + state + "; prerequisite status: " + dep["prerequisite_status"] + ").")
    lines += ["", "## Unfinished work and ownership"]
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


@app.get("/api/projects/{project_id}/intelligence")
def project_intelligence(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id)).all()
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id).order_by(SourceDocument.uploaded_at.desc())).all()
    now = datetime.now(timezone.utc)
    freshness = []
    for doc in docs:
        uploaded = doc.uploaded_at.replace(tzinfo=timezone.utc) if doc.uploaded_at.tzinfo is None else doc.uploaded_at
        reviewed = doc.last_reviewed_at
        if reviewed and reviewed.tzinfo is None:
            reviewed = reviewed.replace(tzinfo=timezone.utc)
        reference = reviewed or uploaded
        age_days = max(0, (now - reference).days)
        freshness.append({
            "source_id": doc.id, "filename": doc.filename,
            "uploaded_at": doc.uploaded_at.isoformat(),
            "last_reviewed_at": doc.last_reviewed_at.isoformat() if doc.last_reviewed_at else None,
            "age_days_since_check": age_days,
            "status": "review_due" if age_days >= 90 else ("never_reviewed" if not reviewed else "recently_reviewed"),
            "review_required": age_days >= 90 or reviewed is None,
            "basis": "Upload date is used until a human records a review; age is a review reminder, not proof the document is outdated."
        })
    report = analyze_project([item_dict(i) for i in items])
    report["source_freshness"] = freshness
    report["counts"]["sources_never_reviewed"] = sum(1 for x in freshness if x["status"] == "never_reviewed")
    report["counts"]["sources_review_due"] = sum(1 for x in freshness if x["status"] == "review_due")
    return report


@app.post("/api/sources/{source_id}/review")
def mark_source_reviewed(source_id: int, db: Session = Depends(get_db)):
    doc = db.get(SourceDocument, source_id)
    if not doc:
        raise HTTPException(404, "Source document not found")
    doc.last_reviewed_at = datetime.now(timezone.utc)
    log_event(db, doc.project_id, f'Source reviewed: {doc.filename}', "source_reviewed")
    db.commit(); db.refresh(doc)
    return {
        "source_id": doc.id, "filename": doc.filename,
        "last_reviewed_at": doc.last_reviewed_at.isoformat(),
        "status": "recently_reviewed",
    }


@app.post("/api/projects/{project_id}/ask")
def ask_project(project_id: int, payload: dict, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "Question is required")
    if len(question) > 500:
        raise HTTPException(400, "Question must be 500 characters or fewer")
    docs = db.scalars(select(SourceDocument).where(SourceDocument.project_id == project_id)).all()
    items = db.scalars(select(KnowledgeItem).where(KnowledgeItem.project_id == project_id)).all()
    return answer_project_question(
        question,
        [{"id": d.id, "filename": d.filename, "content": d.content} for d in docs],
        [item_dict(i) for i in items],
    )


@app.post("/api/projects/{project_id}/integrations/events")
def receive_integration_event(
    project_id: int,
    payload: dict,
    x_integration_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Receive a normalized event from a trusted GitHub/Slack/PM webhook adapter."""
    configured_token = os.getenv("INTEGRATION_WEBHOOK_TOKEN", "")
    if not configured_token:
        raise HTTPException(503, "Integration webhook is disabled until INTEGRATION_WEBHOOK_TOKEN is configured")
    if not x_integration_token or not secrets.compare_digest(x_integration_token, configured_token):
        raise HTTPException(401, "Invalid integration token")
    get_project_or_404(project_id, db)
    provider = str(payload.get("provider", "external"))[:40]
    event_type = str(payload.get("event_type", "update"))[:50]
    title = str(payload.get("title", "")).strip()[:300]
    body = str(payload.get("body", "")).strip()[:5000]
    url = str(payload.get("url", "")).strip()[:1000]
    actor = str(payload.get("actor", "")).strip()[:180]
    if not title and not body:
        raise HTTPException(400, "Integration event needs a title or body")
    summary = f"[{provider}] {event_type}: {title or body[:180]}"
    if actor:
        summary += f" · by {actor}"
    if url:
        summary += f" · {url}"
    db.add(ActivityEvent(project_id=project_id, event_type=f"{provider}_{event_type}"[:50], message=summary[:2000], actor=actor or provider))
    created_item_id = None
    category = str(payload.get("category", "")).lower()
    if category in {"decision", "task", "risk", "question"} and title:
        item = KnowledgeItem(
            project_id=project_id, category=category, title=title,
            detail=body, evidence=body, status="needs_review", verified=False,
            owner=actor, due_date="", priority="medium", work_status="open",
        )
        db.add(item)
        db.flush()
        created_item_id = item.id
    db.commit()
    return {"received": True, "provider": provider, "created_item_id": created_item_id,
            "message": "Event recorded in the project activity timeline. Any created knowledge item requires human review."}


@app.get("/api/projects/{project_id}/audit")
def project_audit_log(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(project_id, db)
    events = db.scalars(
        select(ActivityEvent).where(ActivityEvent.project_id == project_id)
        .order_by(ActivityEvent.created_at.desc()).limit(500)
    ).all()
    return [{"id": e.id, "event_type": e.event_type, "message": e.message,
             "actor": e.actor, "item_id": e.item_id, "created_at": e.created_at.isoformat()}
            for e in events]
