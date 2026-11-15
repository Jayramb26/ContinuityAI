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


def test_explicit_task_dependencies_validate_cycles_and_export(client):
    project_id = create_project(client)
    def task(title):
        response = client.post(f"/api/projects/{project_id}/items", json={"category": "task", "title": title, "work_status": "open"})
        assert response.status_code == 200, response.text
        return response.json()

    first, second, third = task("Prepare database migration"), task("Deploy API"), task("Run smoke tests")
    added = client.post(f"/api/items/{second['id']}/dependencies", json={"depends_on_item_id": first["id"]})
    assert added.status_code == 200, added.text
    assert added.json()["satisfied"] is False
    assert added.json()["prerequisite_title"] == first["title"]
    chained = client.post(f"/api/items/{third['id']}/dependencies", json={"depends_on_item_id": second["id"]})
    assert chained.status_code == 200
    assert client.post(f"/api/items/{first['id']}/dependencies", json={"depends_on_item_id": first["id"]}).status_code == 400
    assert client.post(f"/api/items/{first['id']}/dependencies", json={"depends_on_item_id": third["id"]}).status_code == 400

    handover = client.get(f"/api/projects/{project_id}/handover").json()
    assert handover["readiness"] == sum(x["score"] for x in handover["readiness_breakdown"].values())
    assert handover["readiness_breakdown"]["dependency_health"]["score"] == 0
    assert len(handover["task_dependencies"]) == 2
    assert {x["id"] for x in handover["waiting_tasks"]} == {second["id"], third["id"]}
    assert "waiting on prerequisites" in " ".join(handover["next_steps"])
    assert client.patch(f"/api/items/{first['id']}", json={"work_status": "done"}).status_code == 200
    handover = client.get(f"/api/projects/{project_id}/handover").json()
    assert next(x for x in handover["task_dependencies"] if x["item_id"] == second["id"])["satisfied"] is True
    assert {x["item_id"] for x in handover["task_dependencies"] if not x["satisfied"]} == {third["id"]}
    exported = client.get(f"/api/projects/{project_id}/handover.md")
    assert "## Task dependencies" in exported.text
    assert "## Readiness score breakdown" in exported.text
    assert "Dependency health: 5/10" in exported.text
    assert "Deploy API" in exported.text and "Prepare database migration" in exported.text
    assert client.delete(f"/api/items/{second['id']}/dependencies/{added.json()['id']}").status_code == 200
    assert len(client.get(f"/api/projects/{project_id}/handover").json()["task_dependencies"]) == 1


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


def test_assistant_prioritizes_product_explanation_over_pdf_metadata(client):
    project_id = create_project(client)
    source = (
        "ContinuityAI — Round 2 Working MVP\\n"
        "https://continuityai-web.onrender.com/\\n"
        "CONTINUITYAI DEPLOYED IMPLEMENTATION\\n"
        "ContinuityAI is an evidence-first project knowledge handover platform that turns "
        "authorised project documents into decisions, tasks, risks, owners and open questions "
        "so another teammate can continue work without chasing the previous owner.\\n"
        "ContinuityAI — Round 2 Working MVP\\n"
    )
    upload = client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("round2-submission.pdf.txt", source.encode(), "text/plain")},
    )
    assert upload.status_code == 200, upload.text

    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={"question": "What is ContinuityAI?"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["confidence"] in {"medium", "high"}
    assert "evidence-first project knowledge handover platform" in result["answer"]
    assert "https://continuityai-web.onrender.com" not in result["answer"]
    assert len(result["matches"]) == 1


def test_assistant_does_not_answer_from_title_or_url_only(client):
    project_id = create_project(client)
    source = (
        "ContinuityAI — Round 2 Working MVP\\n"
        "https://continuityai-web.onrender.com/\\n"
        "CONTINUITYAI DEPLOYED IMPLEMENTATION\\n"
    )
    upload = client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("metadata-only.txt", source.encode(), "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    response = client.post(
        f"/api/projects/{project_id}/ask",
        json={"question": "What is ContinuityAI?"},
    )
    assert response.status_code == 200
    assert response.json()["confidence"] == "none"
    assert response.json()["matches"] == []


def test_assistant_retrieval_builds_context_windows_for_pdf_line_wraps():
    from app.intelligence import _passages

    extracted = (
        "ContinuityAI is an AI-assisted project knowledge transfer system\n"
        "designed to prevent critical knowledge from being lost when team members leave.\n"
        "It turns project documents into a structured handover pack."
    )
    passages = _passages(extracted)
    assert any(
        "ContinuityAI is an AI-assisted project knowledge transfer system designed to prevent"
        in passage
        for passage in passages
    )


def test_optional_editor_and_viewer_roles_enforce_write_permissions(client, monkeypatch):
    monkeypatch.setenv("DEMO_EDITOR_EMAIL", "editor@continuityai.app")
    monkeypatch.setenv("DEMO_EDITOR_PASSWORD", "EditorPassForTests!")
    monkeypatch.setenv("DEMO_VIEWER_EMAIL", "viewer@continuityai.app")
    monkeypatch.setenv("DEMO_VIEWER_PASSWORD", "ViewerPassForTests!")

    with TestClient(app) as anonymous:
        editor_login = anonymous.post("/api/auth/login", json={"email": "editor@continuityai.app", "password": "EditorPassForTests!"})
        assert editor_login.status_code == 200
        assert editor_login.json()["role"] == "editor"
        editor_headers = {"Authorization": "Bearer " + editor_login.json()["access_token"]}
        project = anonymous.post("/api/projects", json={"name": "Editor workspace"}, headers=editor_headers)
        assert project.status_code == 200

        viewer_login = anonymous.post("/api/auth/login", json={"email": "viewer@continuityai.app", "password": "ViewerPassForTests!"})
        assert viewer_login.status_code == 200
        assert viewer_login.json()["role"] == "viewer"
        viewer_headers = {"Authorization": "Bearer " + viewer_login.json()["access_token"]}
        assert anonymous.get("/api/projects", headers=viewer_headers).status_code == 200
        assert anonymous.post("/api/projects", json={"name": "Blocked workspace"}, headers=viewer_headers).status_code == 403
        assert anonymous.post("/api/brand/guidelines", json={"name":"x","kind":"required_term","content":"x"}, headers=viewer_headers).status_code == 403


def test_milestone_tracking_links_tasks_and_calculates_progress(client):
    project_id = create_project(client)
    other_project_id = create_project(client)
    task_a = client.post(f"/api/projects/{project_id}/items", json={
        "category":"task", "title":"Build API", "work_status":"done"
    }).json()
    task_b = client.post(f"/api/projects/{project_id}/items", json={
        "category":"task", "title":"Test deployment", "work_status":"in_progress"
    }).json()
    foreign_task = client.post(f"/api/projects/{other_project_id}/items", json={
        "category":"task", "title":"Foreign task"
    }).json()

    invalid = client.post(f"/api/projects/{project_id}/milestones", json={
        "name":"Release", "item_ids":[task_a["id"], foreign_task["id"]]
    })
    assert invalid.status_code == 400

    created = client.post(f"/api/projects/{project_id}/milestones", json={
        "name":"Release 1", "description":"Ship the first release",
        "owner":"Jayram", "due_date":"2026-11-20",
        "status":"in_progress", "item_ids":[task_a["id"],task_b["id"]]
    })
    assert created.status_code == 200, created.text
    milestone = created.json()
    assert milestone["linked_item_count"] == 2
    assert milestone["completed_item_count"] == 1
    assert milestone["progress"] == 50

    updated = client.patch(f"/api/milestones/{milestone['id']}", json={"status":"completed"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "completed"
    assert len(client.get(f"/api/projects/{project_id}/milestones").json()) == 1
    assert client.get(f"/api/projects/{other_project_id}/milestones").json() == []
    handover = client.get(f"/api/projects/{project_id}/handover").json()
    assert handover["milestones"][0]["progress"] == 50
    assert "## Project milestones" in client.get(f"/api/projects/{project_id}/handover.md").text
    assert any("Milestone created" in e["message"] for e in client.get(f"/api/projects/{project_id}").json()["activity"])
    assert client.delete(f"/api/milestones/{milestone['id']}").status_code == 200


def test_source_freshness_requires_human_review_and_records_review(client):
    project_id = create_project(client)
    uploaded = client.post(
        f"/api/projects/{project_id}/upload",
        files={"file": ("plan.txt", b"Decision: Use FastAPI for the service layer and document the release approach.", "text/plain")},
    )
    assert uploaded.status_code == 200
    source_id = uploaded.json()["document"]["id"]

    report = client.get(f"/api/projects/{project_id}/intelligence").json()
    assert report["counts"]["sources_never_reviewed"] == 1
    source = report["source_freshness"][0]
    assert source["source_id"] == source_id
    assert source["status"] == "never_reviewed"
    assert source["review_required"] is True
    assert "not proof" in source["basis"]

    reviewed = client.post(f"/api/sources/{source_id}/review")
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "recently_reviewed"
    report_after = client.get(f"/api/projects/{project_id}/intelligence").json()
    assert report_after["counts"]["sources_never_reviewed"] == 0
    assert report_after["source_freshness"][0]["status"] == "recently_reviewed"


def test_source_review_endpoint_rejects_unknown_source(client):
    response = client.post("/api/sources/999999/review")
    assert response.status_code == 404


def test_handover_share_is_read_only_expires_and_can_be_revoked(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.models import HandoverShare
    import hashlib
    project_id = create_project(client)
    approved = client.post(f"/api/projects/{project_id}/items", json={
        "category": "decision", "title": "Use FastAPI", "detail": "Backend decision"
    }).json()
    client.patch(f"/api/items/{approved['id']}", json={"status": "approved", "verified": True})

    created = client.post(f"/api/projects/{project_id}/shares", json={"expires_in_hours": 24})
    assert created.status_code == 200, created.text
    share = created.json()
    assert share["access"] == "read_only"
    assert share["token"]

    # Only a hash is persisted; the raw bearer token is not stored.
    stored = client.get(f"/api/projects/{project_id}/shares").json()
    assert stored[0]["status"] == "active"
    assert "token" not in stored[0]
    row = client.get(f"/api/shared/{share['token']}")
    assert row.status_code == 200, row.text
    assert row.json()["handover"]["categories"]["decision"][0]["title"] == "Use FastAPI"

    assert client.get("/api/shared/not-a-valid-token").status_code == 404
    revoked = client.delete(f"/api/projects/{project_id}/shares/{share['id']}")
    assert revoked.status_code == 200
    assert client.get(f"/api/shared/{share['token']}").status_code == 404
    assert client.get(f"/api/projects/{project_id}/shares").json()[0]["status"] == "revoked"


def test_handover_share_expiry_and_owner_only_controls(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.models import HandoverShare
    import hashlib
    project_id = create_project(client)
    invalid = client.post(f"/api/projects/{project_id}/shares", json={"expires_in_hours": 721})
    assert invalid.status_code == 400
    created = client.post(f"/api/projects/{project_id}/shares", json={"expires_in_hours": 1}).json()
    row = client.get(f"/api/projects/{project_id}/shares").json()[0]
    assert row["status"] == "active"
    share_row = client.get(f"/api/shared/{created['token']}")
    assert share_row.status_code == 200

    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/projects/{project_id}/shares").status_code == 401
        viewer = anonymous.post("/api/auth/login", json={"email": "demo@continuityai.app", "password": "ContinuityDemo2026!"})
        assert viewer.status_code == 200



def test_share_expiry_and_viewer_cannot_manage_links(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models import HandoverShare
    project_id = create_project(client)
    created = client.post(f"/api/projects/{project_id}/shares", json={"expires_in_hours": 24})
    assert created.status_code == 200
    token = created.json()["token"]

    db = SessionLocal()
    try:
        row = db.query(HandoverShare).filter(HandoverShare.id == created.json()["id"]).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    expired = client.get(f"/api/shared/{token}")
    assert expired.status_code == 410

    monkeypatch.setenv("DEMO_VIEWER_EMAIL", "viewer@continuityai.app")
    monkeypatch.setenv("DEMO_VIEWER_PASSWORD", "ViewerPassForTests!")
    with TestClient(app) as anonymous:
        login = anonymous.post("/api/auth/login", json={"email": "viewer@continuityai.app", "password": "ViewerPassForTests!"})
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert anonymous.post(f"/api/projects/{project_id}/shares", json={"expires_in_hours": 24}, headers=headers).status_code == 404
        assert anonymous.get(f"/api/projects/{project_id}/shares", headers=headers).status_code == 404


def test_workspace_membership_is_project_scoped_and_roles_are_enforced(client, monkeypatch):
    owner_project = create_project(client)
    other_project = create_project(client)
    monkeypatch.setenv("DEMO_EDITOR_EMAIL", "editor@continuityai.app")
    monkeypatch.setenv("DEMO_EDITOR_PASSWORD", "EditorPassForTests!")
    owner_token = client.headers.get("Authorization")
    added = client.post(f"/api/projects/{owner_project}/members", json={"email":"editor@continuityai.app","role":"editor"})
    assert added.status_code == 200, added.text
    assert added.json()["role"] == "editor"

    login = client.post("/api/auth/login", json={"email":"editor@continuityai.app","password":"EditorPassForTests!"})
    assert login.status_code == 200, login.text
    editor = TestClient(app)
    editor.headers.update({"Authorization":"Bearer " + login.json()["access_token"]})
    assert editor.get(f"/api/projects/{owner_project}").status_code == 200
    assert editor.get(f"/api/projects/{other_project}").status_code == 404
    assert editor.post(f"/api/projects/{owner_project}/items", json={"category":"task","title":"Editor task"}).status_code == 200
    assert editor.post(f"/api/projects/{owner_project}/members", json={"email":"demo@continuityai.app","role":"viewer"}).status_code == 403

    client.headers.update({"Authorization":owner_token})
    changed = client.patch(f"/api/projects/{owner_project}/members/{added.json()['id']}", json={"role":"viewer"})
    assert changed.status_code == 200
    assert editor.post(f"/api/projects/{owner_project}/items", json={"category":"task","title":"Blocked write"}).status_code == 403


def test_member_assignment_requires_existing_demo_account_and_owner_cannot_be_removed(client):
    project_id = create_project(client)
    unknown = client.post(f"/api/projects/{project_id}/members", json={"email":"unknown@example.com","role":"viewer"})
    assert unknown.status_code == 400
    members = client.get(f"/api/projects/{project_id}/members").json()
    assert len(members) == 1 and members[0]["role"] == "owner"
    assert client.delete(f"/api/projects/{project_id}/members/{members[0]['id']}").status_code == 400


def test_workspace_invitation_creates_account_and_grants_scoped_access(client):
    project_id = create_project(client)
    created = client.post(f"/api/projects/{project_id}/invitations",
        json={"email": "new.member@example.com", "role": "editor"})
    assert created.status_code == 200, created.text
    invitation = created.json()
    assert invitation["expires_in_days"] == 7
    assert "token" in invitation

    accepted = client.post("/api/invitations/accept",
        json={"token": invitation["token"], "password": "StrongPassword2026!"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["email"] == "new.member@example.com"
    assert accepted.json()["role"] == "editor"

    member_headers = {"Authorization": "Bearer " + accepted.json()["access_token"]}
    with TestClient(app) as member:
        assert member.get(f"/api/projects/{project_id}", headers=member_headers).status_code == 200
        assert member.post(f"/api/projects/{project_id}/items",
            json={"category": "task", "title": "Invitee task"}, headers=member_headers).status_code == 200
        assert member.post("/api/auth/login",
            json={"email": "new.member@example.com", "password": "StrongPassword2026!"}).status_code == 200

    reused = client.post("/api/invitations/accept",
        json={"token": invitation["token"], "password": "StrongPassword2026!"})
    assert reused.status_code == 404


def test_workspace_invitation_revocation_and_expiry(client):
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models import WorkspaceInvitation
    project_id = create_project(client)
    created = client.post(f"/api/projects/{project_id}/invitations",
        json={"email": "revoked@example.com", "role": "viewer"})
    assert created.status_code == 200
    invitation_id = created.json()["id"]
    assert client.delete(f"/api/projects/{project_id}/invitations/{invitation_id}").status_code == 200
    assert client.post("/api/invitations/accept",
        json={"token": created.json()["token"], "password": "StrongPassword2026!"}).status_code == 404

    second = client.post(f"/api/projects/{project_id}/invitations",
        json={"email": "expired@example.com", "role": "viewer"}).json()
    db = SessionLocal()
    try:
        row = db.query(WorkspaceInvitation).filter(WorkspaceInvitation.id == second["id"]).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    expired = client.post("/api/invitations/accept",
        json={"token": second["token"], "password": "StrongPassword2026!"})
    assert expired.status_code == 410
