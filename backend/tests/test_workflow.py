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
