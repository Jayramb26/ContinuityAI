"""End-to-end API tests for the local ContinuityAI MVP."""
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

TEST_DB = Path(__file__).parent / "test_continuityai.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
from app.main import app
from app.database import Base, engine

@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)

def create_project(client):
    response = client.post("/api/projects", json={"name": "Continuity Demo", "description": "Synthetic test project"})
    assert response.status_code == 200
    return response.json()["id"]

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
