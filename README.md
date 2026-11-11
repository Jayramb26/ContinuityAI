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

## Technology

- Frontend: React, Vite, JavaScript, CSS and Lucide icons.
- Backend: Python, FastAPI, SQLAlchemy.
- Document parsing: PyMuPDF (PDF) and python-docx (DOCX).
- Database: SQLite by default; PostgreSQL through DATABASE_URL.
- Optional extraction: OpenAI-compatible chat-completions API (e.g. Groq).

## Run locally

Requirements: Python 3.10+ and Node.js 18+.

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

- The app has no authentication, authorisation, workspace membership or role-based access. Do not put confidential or personal project information in a public deployment.
- The Render Blueprint uses SQLite by default. Free service storage may be ephemeral, so data can be lost on restart or redeploy. Use persistent PostgreSQL and appropriate file storage for a durable deployment.
- Uploads are limited to 10 MB per file. Supported formats are PDF, DOCX, TXT and Markdown.
- Rule-based extraction searches for explicit decision/action/risk/question cues and can miss implicit context. Owner and due-date extraction is conservative and only attempts to capture explicitly written names and ISO dates; review every candidate.
- LLM extraction is optional. If enabled, data is sent to the configured provider; review its data-handling terms before use.
- Evidence substring validation does not perform semantic entailment or contradiction detection.
- The readiness percentage is an illustrative checklist indicator, not a validated project-health score.
- The activity timeline records actions performed in ContinuityAI; it is not yet a live audit feed from external tools. Authentication, malware scanning, controlled sharing and real-time collaboration are not implemented.
- GitHub, Slack, Teams and email ingestion are not implemented.

## API endpoints

- `GET /api/brand/guidelines`, `POST /api/brand/guidelines`, `DELETE /api/brand/guidelines/{id}`
- `GET /api/brand/reviews`, `POST /api/brand/reviews`, `PATCH /api/brand/reviews/{id}`
- `GET /api/health`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{id}`
- `POST /api/projects/{id}/upload`
- `POST /api/projects/{id}/items` (manually record a decision, task, risk or question)
- `POST /api/projects/{id}/activity` (record a project update)
- `PATCH /api/items/{id}` (review and update owner, due date, priority and work status)
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
    database.py
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
