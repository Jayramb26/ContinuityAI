"""End-to-end API tests for the local ContinuityAI MVP."""
import os
from pathlib import Path
from io import BytesIO
import fitz
from docx import Document
import pytest
from fastapi.testclient import TestClient

TEST_DB = Path(__file__).parent / "test_continuityai.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["AUTH_SECRET"] = "test-only-secret"
os.environ["DEMO_EMAIL"] = "demo@continuityai.app"
os.environ["DEMO_PASSWORD"] = "ContinuityDemo2026!"
from app.main import app
from app.database import Base, engine

@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        login = test_client.post("/api/auth/login", json={"email": "demo@continuityai.app", "password": "ContinuityDemo2026!"})
        assert login.status_code == 200, login.text
        test_client.headers.update({"Authorization": "Bearer " + login.json()["access_token"]})
        yield test_client
    Base.metadata.drop_all(bind=engine)

def create_project(client):
    response = client.post("/api/projects", json={"name": "Continuity Demo", "description": "Synthetic test project"})
    assert response.status_code == 200
    return response.json()["id"]

def test_health_and_brand_governance_routes(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"] == "0.3.0"
    assert client.get("/api/brand/guidelines").json() == []
    assert client.get("/api/brand/reviews").json() == []


def test_document_to_reviewed_handover_export(client):
    project_id = create_project(client)
    source = ("Decision: We decided to use FastAPI for the backend. "
              "Task: Assigned to Jayram, need to finish API tests by Friday. "
              "Risk: Database migration may fail during deployment. "
              "Question: Confirm who owns deployment monitoring.")
    upload = client.post(f"/api/projects/{project_id}/upload", files={"file": ("meeting-notes.txt", source.encode(), "text/plain")})
    assert upload.status_code == 200, upload.text
    result = upload.json()
    assert result["extracted_count"] >= 3
    assert result["extraction_mode"] == "rule_based"
    project = client.get(f"/api/projects/{project_id}").json()
    assert len(project["documents"]) == 1
    assert len(project["items"]) >= 3
    assert any(item["owner"] == "Jayram" for item in project["items"])
    first = project["items"][0]
    assert first["evidence"] in source
    assert first["status"] == "needs_review"
    reviewed = client.patch(f"/api/items/{first['id']}", json={**first, "title": "Reviewed: " + first["title"], "status": "approved", "verified": True})
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved"
    handover = client.get(f"/api/projects/{project_id}/handover")
    assert handover.status_code == 200
    assert handover.json()["approved_count"] == 1
    assert handover.json()["review_count"] >= 2
    export = client.get(f"/api/projects/{project_id}/handover.md")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/markdown")
    assert "# Handover: Continuity Demo" in export.text
    assert "Reviewed:" in export.text


def test_pdf_and_docx_ingestion(client):
    project_id = create_project(client)
    source = ("Decision: We decided to use React for the frontend.\n"
              "Task: Assigned to Aarav, complete API integration by 2026-11-20.\n"
              "Risk: Deployment may fail if environment variables are missing.\n"
              "Question: Confirm who owns the final release checklist.")

    docx = Document()
    for line in source.splitlines():
        docx.add_paragraph(line)
    docx_buffer = BytesIO()
    docx.save(docx_buffer)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 750), source, fontsize=11, lineheight=1.4)
    pdf_bytes = pdf.tobytes()
    pdf.close()

    uploads = [
        ("meeting-notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx_buffer.getvalue()),
        ("meeting-notes.pdf", "application/pdf", pdf_bytes),
    ]
    for filename, content_type, data in uploads:
        response = client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": (filename, data, content_type)}
        )
        assert response.status_code == 200, response.text
        assert response.json()["extracted_count"] >= 3
        assert response.json()["document"]["characters"] > 100

    project = client.get(f"/api/projects/{project_id}").json()
    assert {doc["filename"] for doc in project["documents"]} == {
        "meeting-notes.docx", "meeting-notes.pdf"
    }
    assert len(project["items"]) >= 6
    assert all(item["evidence"] for item in project["items"])


def test_rejects_unsupported_file_type(client):
    project_id = create_project(client)
    response = client.post(f"/api/projects/{project_id}/upload", files={"file": ("payload.exe", b"not a document", "application/octet-stream")})
    assert response.status_code == 400

def test_project_not_found(client):
    assert client.get("/api/projects/999999").status_code == 404


def test_owner_tracking_activity_and_handover_details(client):
    project_id = create_project(client)
    created = client.post(f"/api/projects/{project_id}/items", json={
        "category": "task", "title": "Finish deployment checklist",
        "detail": "Verify API health and frontend access",
        "owner": "Aarav", "due_date": "2026-11-20",
        "priority": "high", "work_status": "blocked"
    })
    assert created.status_code == 200, created.text
    item = created.json()
    assert item["owner"] == "Aarav"
    assert item["work_status"] == "blocked"
    assert item["priority"] == "high"

    update = client.patch(f"/api/items/{item['id']}", json={
        "title": item["title"], "detail": item["detail"],
        "status": "approved", "verified": True,
        "owner": "Mira", "work_status": "in_progress",
        "priority": "critical", "due_date": "2026-11-21"
    })
    assert update.status_code == 200, update.text
    assert update.json()["owner"] == "Mira"
    assert update.json()["work_status"] == "in_progress"

    activity = client.post(f"/api/projects/{project_id}/activity", json={
        "message": "Handover sync: deployment ownership transferred to Mira",
        "event_type": "team_update"
    })
    assert activity.status_code == 200

    project = client.get(f"/api/projects/{project_id}").json()
    assert any("deployment ownership transferred" in e["message"] for e in project["activity"])
    handover = client.get(f"/api/projects/{project_id}/handover").json()
    assert len(handover["tasks"]) == 1
    assert handover["tasks"][0]["owner"] == "Mira"
    assert handover["tasks"][0]["work_status"] == "in_progress"
    assert len(handover["blocked_items"]) == 0

    audit = client.get(f"/api/projects/{project_id}/audit")
    assert audit.status_code == 200
    assert any(event["actor"] == "demo-owner" for event in audit.json())

    exported = client.get(f"/api/projects/{project_id}/handover.md")
    assert exported.status_code == 200
    assert "Mira" in exported.text
    assert "Unfinished work and ownership" in exported.text
    assert "Recent project activity" in exported.text


def test_brand_governance_rule_check_and_human_decision(client):
    required = client.post("/api/brand/guidelines", json={"name": "Required product name", "kind": "required_term", "content": "ContinuityAI", "severity": "critical"})
    assert required.status_code == 200, required.text
    prohibited = client.post("/api/brand/guidelines", json={"name": "No unsupported superlatives", "kind": "prohibited_term", "content": "best in the world", "severity": "warning"})
    assert prohibited.status_code == 200, prohibited.text
    fact = client.post("/api/brand/guidelines", json={"name": "Approved founding fact", "kind": "approved_fact", "content": "Founded in 2024", "severity": "warning"})
    assert fact.status_code == 200, fact.text
    upload = client.post("/api/brand/reviews", files={"file": ("campaign.txt", b"Our product is the best in the world.", "text/plain")})
    assert upload.status_code == 200, upload.text
    review = upload.json()
    assert review["status"] == "pending"
    assert review["finding_count"] >= 3
    assert any("Required term is missing" in f["issue"] for f in review["findings"])
    assert any("Prohibited wording found" in f["issue"] for f in review["findings"])
    assert any("Approved fact not verified" in f["issue"] for f in review["findings"])
    decision = client.patch(f"/api/brand/reviews/{review['id']}", json={"status": "changes_requested", "decision_note": "Add approved product name and verify the founding claim."})
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "changes_requested"
    assert "verify the founding claim" in decision.json()["decision_note"]


def test_intelligence_and_grounded_project_assistant(client):
    project_id = create_project(client)
    source = (
        "Decision: We will use React for the dashboard interface.\n"
        "Decision: We will not use React for the dashboard interface.\n"
        "Task: Assigned to Jayram, finish deployment checklist depends on database migration.\n"
        "Risk: Deployment may fail if environment variables are missing."
    )
    uploaded = client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("notes.txt", source.encode(), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text

    intelligence = client.get(f"/api/projects/{project_id}/intelligence")
    assert intelligence.status_code == 200
    report = intelligence.json()
    assert report["counts"]["possible_conflicts"] >= 1
    assert report["counts"]["dependencies"] >= 1
    assert report["counts"]["knowledge_gaps"] >= 1

    question = client.post(
        f"/api/projects/{project_id}/ask",
        json={"question": "What does the source say about React dashboard?"},
    )
    assert question.status_code == 200
    answer = question.json()
    assert answer["matches"]
    assert "React" in answer["answer"]
    assert answer["confidence"] in {"medium", "high"}

    missing = client.post(f"/api/projects/{project_id}/ask", json={"question": "Who owns the moon base?"})
    assert missing.status_code == 200
    assert missing.json()["confidence"] == "none"


def test_integration_event_requires_token_and_records_reviewable_item(client, monkeypatch):
    project_id = create_project(client)
    payload = {
        "provider": "github",
        "event_type": "issue_opened",
        "title": "Document release checklist",
        "body": "Task: Document release checklist before launch.",
        "url": "https://github.com/example/repo/issues/7",
        "actor": "Jayram",
        "category": "task",
    }
    disabled = client.post(f"/api/projects/{project_id}/integrations/events", json=payload)
    assert disabled.status_code == 503

    monkeypatch.setenv("INTEGRATION_WEBHOOK_TOKEN", "test-secret")
    unauthorized = client.post(f"/api/projects/{project_id}/integrations/events", json=payload)
    assert unauthorized.status_code == 401

    accepted = client.post(
        f"/api/projects/{project_id}/integrations/events",
        json=payload,
        headers={"X-Integration-Token": "test-secret"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["created_item_id"] is not None
    project = client.get(f"/api/projects/{project_id}").json()
    assert any(item["title"] == payload["title"] and item["status"] == "needs_review" for item in project["items"])
    assert any("[github]" in event["message"] for event in project["activity"])


def test_demo_authentication_protects_workspace_routes():
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/auth/config").json()["auth_enabled"] is True
        assert anonymous.get("/api/projects").status_code == 401
        bad = anonymous.post("/api/auth/login", json={"email": "demo@continuityai.app", "password": "wrong"})
        assert bad.status_code == 401
        good = anonymous.post("/api/auth/login", json={"email": "demo@continuityai.app", "password": "ContinuityDemo2026!"})
        assert good.status_code == 200
        token = good.json()["access_token"]
        assert anonymous.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).json()["role"] == "owner"
