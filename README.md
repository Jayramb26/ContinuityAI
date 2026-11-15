# ContinuityAI — CODE TITANS

**Never let project knowledge leave with a person.**

ContinuityAI is an evidence-first project knowledge handover MVP. It turns authorised project documents into candidate decisions, tasks, risks and unresolved questions, then lets a human review the extracted items before exporting a handover.

## Implemented MVP workflow

1. Create a project workspace.
2. Upload PDF, DOCX, TXT or Markdown source files (maximum 10 MB per file).
3. Extract candidate knowledge using rule-based matching, with optional OpenAI-compatible LLM extraction.
4. Keep a verbatim evidence excerpt and source-document reference with each candidate.
5. Assign explicit owners, due dates, priorities and work states (open, in progress, blocked, done).
6. Add decisions, tasks, risks and questions manually when context is not present in an uploaded file.
7. Record project updates in a timestamped activity timeline; uploads and knowledge-item changes are logged automatically.
8. Edit, approve, reject or mark candidates as unknown.
9. Review unfinished and unassigned work, blocked items, overdue tasks and risks in the handover, then export Markdown.

## Brand governance workflow

A separate Brand Governance area is available from the sidebar. Add explicit approved rules for required terms, prohibited terms, approved facts, approved assets/identifiers and tone guidance. Upload a PDF, DOCX, TXT or Markdown content draft to create an explainable review report. Findings include the matched rule, severity, explanation and suggested action. A human reviewer must then approve, reject or request changes and can leave a decision note.

The checks are deliberately transparent: required/prohibited terms and asset identifiers use exact case-insensitive phrase matching; approved facts are checked for exact approved wording and missing matches are marked for verification, not declared false. Tone guidance is always surfaced for human review. Potential absolute claims (such as guaranteed or risk-free) are flagged for substantiation. This is a review assistant, not legal advice, semantic fact verification or an automatic publication gate.

## Round 3 commitments and delivery status

These are the three commitments recorded in the Round 2 submission. The current implementation delivers useful parts of each, with the following limitations kept explicit.

1. **Advanced Evidence Intelligence and Conflict Detection — partially delivered.** Every extracted candidate retains a verbatim evidence excerpt and source-document ID. The Intelligence view flags explicit dependency phrases, possible decision conflicts using shared terms plus opposing negation, and gaps such as missing task owners/due dates or unreviewed candidates. These are explainable review prompts, not semantic contradiction proof. Semantic RAG, stale-source detection and robust claim-entailment verification remain future work.
2. **Secure Access Control and Auditable Knowledge Management — partially delivered.** When `AUTH_SECRET` is configured, API data routes require signed, expiring bearer tokens. Workspaces support owner/editor/viewer membership, owner-managed one-time invitations, password-hashed user accounts, revocable expiring read-only handover links, and an activity audit log. Invitation links are shared manually; email verification, automated delivery, password reset, rate limiting, individual session revocation and malware scanning are not implemented. This remains a demo access system, not production identity management.
3. **Intelligent Handover and Project Continuity Tracking — partially delivered.** Work items carry owner, due date, priority and work status; workspaces also support milestones with status, owner, due date and linked tasks. Tasks can have explicit prerequisite tasks: the API rejects self-links, cross-workspace links, duplicates and circular dependency chains. Handover shows whether each prerequisite is complete, highlights tasks still waiting, and includes the relationships in Markdown export. Handover also highlights unassigned, overdue and manually blocked work, review gaps, activity and recommended next actions. The Q&A view retrieves source excerpts and labels their review state. A visual dependency graph and change-aware knowledge updates remain future work.

The normalized integration-event endpoint is a supporting capture adapter, not one of the three Round 2 commitments. It can record events from a trusted provider adapter; provider-specific OAuth/webhook mapping and signature verification are not included.

The AI extraction provider remains optional. Without provider credentials, the application uses its rule-based extractor.

## Integration event example

After setting a strong `INTEGRATION_WEBHOOK_TOKEN` in the backend environment, a trusted adapter can send:

```bash
curl -X POST "$API_URL/api/projects/PROJECT_ID/integrations/events" \
  -H "Content-Type: application/json" \
  -H "X-Integration-Token: $INTEGRATION_WEBHOOK_TOKEN" \
  -d '{
    "provider": "github",
    "event_type": "issue_opened",
    "title": "Complete release checklist",
    "body": "Task: Complete release checklist before launch.",
    "url": "https://github.com/example/repo/issues/7",
    "actor": "Project owner",
    "category": "task"
  }'
```

Events are recorded in the activity timeline. When `category` is one of decision, task, risk or question, a candidate is created with `needs_review` status; it is never auto-approved. Do not expose the integration token in browser code or commit it to Git.

## Architecture

```text
React + Vite browser
  ├─ Workspace dashboard, source upload, review, intelligence, Q&A, audit and handover
  └─ Bearer session (optional when AUTH_SECRET is configured)
          │ JSON / multipart
          ▼
FastAPI API
  ├─ Auth: signed short-lived demo sessions
  ├─ Ingestion: PyMuPDF / python-docx / UTF-8 text
  ├─ Extraction: deterministic rules + optional OpenAI-compatible endpoint
  ├─ Intelligence: dependency/conflict/gap heuristics + source retrieval
  └─ Review, audit events and Markdown handover
          │ SQLAlchemy
          ▼
SQLite (default) or PostgreSQL (DATABASE_URL)
```

Evidence remains attached to candidate knowledge items. Human approval is required before candidates are counted as approved handover knowledge. The current demo stores document text and project records in the database; use synthetic data only.

## Roadmap

- **Next:** add automated invitation email delivery and verification, password reset, session revocation, durable managed PostgreSQL/object storage, and stronger operational controls.
- **Evidence quality:** semantic retrieval, source versioning, stale-information detection, claim-to-evidence entailment checks and reviewer resolution workflows for contradictions.
- **Continuity:** explicit dependency graph, milestone tracking, change-aware re-review when source material changes, and handover templates.
- **Integrations:** provider-native GitHub webhooks with signature verification, then Slack and issue-tracker adapters.
- **Operations:** persistent managed PostgreSQL, durable object storage, malware scanning, rate limits, structured monitoring and backup/restore.

## Technology

- Frontend: React, Vite, JavaScript, CSS and Lucide icons.
- Backend: Python, FastAPI, SQLAlchemy.
- Document parsing: PyMuPDF (PDF) and python-docx (DOCX).
- Database: SQLite by default; PostgreSQL through DATABASE_URL.
- Optional extraction: OpenAI-compatible chat-completions API (e.g. Groq).

## Run locally

Requirements: Python 3.11+ and Node.js 22.12+ (the frontend declares this engine requirement).

### Backend
```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
API: http://localhost:8000  
API docs: http://localhost:8000/docs

### Frontend (new terminal)
```bash
cd frontend
npm install
npm run dev
```
Frontend: http://localhost:5173

Set `VITE_API_URL` in `frontend/.env` if the API is hosted elsewhere, for example:
```env
VITE_API_URL=http://localhost:8000/api
```

## Demo authentication and role gates

The Render Blueprint configures the shared judge demo-owner account. The API also supports optional role-specific demo accounts through `DEMO_EDITOR_EMAIL`, `DEMO_EDITOR_PASSWORD`, `DEMO_VIEWER_EMAIL` and `DEMO_VIEWER_PASSWORD`. The existing `DEMO_EMAIL` / `DEMO_PASSWORD` account remains the owner for backwards compatibility. All accounts use the same `AUTH_SECRET` and receive signed, expiring bearer tokens.

- **Owner:** full control of the assigned workspace, including member and invitation management.
- **Editor:** can create and update assigned workspace knowledge and handover data; cannot manage workspace membership or global brand governance rules.
- **Viewer:** read-only access to assigned workspace data and source Q&A.

The configured demo owner and optional demo editor/viewer accounts remain available. Workspace invitations are email-bound, single-use, expire after seven days, and can be revoked by the owner. New invitees create a password (minimum 12 characters); existing accounts must prove their password. Passwords are stored as PBKDF2-HMAC-SHA256 hashes. Invitation URLs are bearer secrets and must be shared privately. The app does not send invitation emails or verify mailbox ownership. Set a strong `AUTH_SECRET` and distinct strong demo passwords; use synthetic data only.

## Optional LLM extraction

The application works without an API key using rule-based extraction. To enable an OpenAI-compatible endpoint, copy `backend/.env.example` to `backend/.env` and configure:
```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=your_key_here
LLM_MODEL=llama-3.3-70b-versatile
```
Never commit a real API key. The backend only accepts LLM candidates whose evidence is a verbatim substring of the source. This is a basic evidence check, not proof that the evidence fully supports the claim; human review is required.

## Deploy a public demo on Render

A starter `render.yaml` Blueprint is included. In Render, choose **New → Blueprint**, connect this public GitHub repository, and deploy the two services described in the Blueprint. Render will show the actual public frontend and API URLs after deployment. The URLs in the Blueprint are suggested service names, not proof that a deployment exists.

After deployment:
1. Confirm the API health endpoint returns status `ok`.
2. Open the frontend in a private/incognito window.
3. Create a synthetic demo workspace.
4. Upload a non-confidential sample document.
5. Review an item and export the Markdown handover.

Do not claim the public demo is live until these checks pass.

## Important demo and security limitations

- The Render Blueprint provisions a generated API signing secret and a shared demo-owner login. The visible judge credentials are `demo@continuityai.app` / `ContinuityDemo2026!`. Workspace membership and invitation onboarding are implemented, but email verification/delivery, password reset, rate limiting and individual session revocation are not. This is not production identity management. Do not put confidential or personal project information in a public deployment.
- The Render Blueprint uses SQLite by default. Free service storage may be ephemeral, so data can be lost on restart or redeploy. Use persistent PostgreSQL and appropriate file storage for a durable deployment.
- Uploads are limited to 10 MB per file. Supported formats are PDF, DOCX, TXT and Markdown.
- Rule-based extraction searches for explicit decision/action/risk/question cues and can miss implicit context. Owner and due-date extraction is conservative and only attempts to capture explicitly written names and ISO dates; review every candidate.
- LLM extraction is optional. If enabled, data is sent to the configured provider; review its data-handling terms before use.
- Evidence substring validation does not perform semantic entailment. The Intelligence tab flags only explicit rule-based dependency cues and narrow possible contradictions; it can miss implicit relationships and can produce false positives.
- The readiness percentage is an illustrative checklist indicator, not a validated project-health score. Handover receipt responses are member-scoped; each member can update their own accepted/needs-follow-up response, and the activity log records the actor and note. Anonymous bearer-share viewers cannot submit acknowledgements.
- The audit log records project actions with actor email where available. Invitation and handover-share actions are also logged. Bearer share links are read-only, scoped to one workspace, expiring and revocable. Malware scanning and real-time collaboration are not implemented.
- Provider-specific OAuth, direct GitHub/Slack/Teams/email integrations, and automated webhook signature verification are not implemented. The authenticated normalized-event intake is a connector adapter endpoint; it requires a server-side shared secret.

## API endpoints

- `GET /api/brand/guidelines`, `POST /api/brand/guidelines`, `DELETE /api/brand/guidelines/{id}`
- `GET /api/brand/reviews`, `POST /api/brand/reviews`, `PATCH /api/brand/reviews/{id}`
- `GET /api/health`
- `GET /api/auth/config`, `POST /api/auth/login`, `GET /api/auth/me`
- `POST /api/invitations/accept`
- `POST /api/projects/{id}/invitations`, `GET /api/projects/{id}/invitations`, `DELETE /api/projects/{id}/invitations/{invitation_id}`
- Workspace membership management: `GET/POST/DELETE /api/projects/{id}/members` (see API docs for request schemas)
- Handover share management and public read-only share routes (see API docs)
- `GET /api/projects/{id}/acknowledgements` (member-scoped response list)
- `POST /api/projects/{id}/acknowledgements` with `{ "status": "accepted" | "needs_follow_up", "note": "..." }`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{id}`
- `POST /api/projects/{id}/upload`
- `POST /api/projects/{id}/items` (manually record a decision, task, risk or question)
- `POST /api/projects/{id}/activity` (record a project update)
- `PATCH /api/items/{id}` (review and update owner, due date, priority and work status)
- `GET /api/projects/{id}/intelligence`
- `GET /api/projects/{id}/audit`
- `POST /api/projects/{id}/ask` with `{ "question": "..." }`
- `POST /api/projects/{id}/integrations/events` (requires `X-Integration-Token`)
- `GET /api/projects/{id}/handover`
- `GET /api/projects/{id}/handover.md`

## Automated checks

GitHub Actions runs the backend integration tests and builds the Vite frontend on pushes and pull requests to `main`. The workflow is in `.github/workflows/ci.yml`.

## Run backend tests

From `backend`:
```bash
python -m pytest -q
```

## Suggested demo flow

Create a workspace named “Campus Event Portal”, upload [`demo-data/synthetic-project-meeting-notes.md`](demo-data/synthetic-project-meeting-notes.md), review the extracted candidates, approve only accurate evidence-backed items, then export the Markdown handover. The sample contains fictional decisions, owners, due dates, risks, dependencies and open questions.

## Repository structure

```
backend/
  app/
    auth.py
    database.py
    intelligence.py
    ingestion.py
    knowledge.py
    main.py
    models.py
    schemas.py
  tests/
    test_workflow.py
  requirements.txt
  .env.example
frontend/
  src/
    main.jsx
    style.css
  index.html
  package.json
render.yaml
README.md
```


### Version-aware handover receipts

A successor acknowledgement is compared with the latest non-acknowledgement project activity. If tracked source material, decisions, tasks, or other workspace work changes after the response, the receipt is marked **Review required** until the member reviews and acknowledges again. Changes made outside ContinuityAI's tracked workflows are not detected.
