import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrainCircuit, Plus, Upload, CheckCircle2, AlertTriangle, FileText,
  Download, RefreshCw, Search, LayoutDashboard, Layers3, ClipboardCheck,
  Clock3, ShieldCheck, ArrowUpRight, Sparkles, CircleHelp, ListTodo,
  Menu, X, ExternalLink
} from "lucide-react";
import "./style.css";

const API = import.meta.env.VITE_API_URL || "https://continuityai-api.onrender.com/api";

function App() {
  const [projects, setProjects] = useState([]);
  const [active, setActive] = useState(null);
  const [detail, setDetail] = useState(null);
  const [handover, setHandover] = useState(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("overview");
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [mobileNav, setMobileNav] = useState(false);

  const req = async (path, options = {}) => {
    const response = await fetch(API + path, options);
    if (!response.ok) {
      let data = {};
      try { data = await response.json(); } catch {}
      throw new Error(data.detail || "Request failed. Please try again.");
    }
    return response.json();
  };

  const refresh = async (id = active) => {
    setBusy(true);
    setError("");
    try {
      const list = await req("/projects");
      setProjects(list);
      const target = id || list[0]?.id;
      if (target) {
        setActive(target);
        const [project, summary] = await Promise.all([
          req("/projects/" + target),
          req("/projects/" + target + "/handover")
        ]);
        setDetail(project);
        setHandover(summary);
      } else {
        setActive(null); setDetail(null); setHandover(null);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { refresh(null); }, []);

  const select = async (id) => {
    setBusy(true); setError("");
    try {
      const [project, summary] = await Promise.all([
        req("/projects/" + id),
        req("/projects/" + id + "/handover")
      ]);
      setActive(id); setDetail(project); setHandover(summary);
      setTab("overview"); setMobileNav(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const create = async (event) => {
    event.preventDefault(); setError("");
    try {
      const project = await req("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description })
      });
      setName(""); setDescription("");
      await refresh(project.id);
      setNotice("Workspace created successfully.");
    } catch (e) { setError(e.message); }
  };

  const upload = async (event) => {
    const file = event.target.files?.[0];
    if (!file || !active) return;
    const form = new FormData();
    form.append("file", file);
    setBusy(true); setError("");
    try {
      const result = await req("/projects/" + active + "/upload", { method: "POST", body: form });
      setNotice(file.name + " · " + result.extracted_count + " knowledge items extracted.");
      await select(active);
      setTab("knowledge");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); event.target.value = ""; }
  };

  const review = async (item, status) => {
    setError("");
    try {
      await req("/items/" + item.id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...item, status, verified: status === "approved" })
      });
      await select(active);
      setNotice(status === "approved" ? "Item approved and verified." : "Review decision saved.");
    } catch (e) { setError(e.message); }
  };

  const edit = async (item) => {
    const title = window.prompt("Edit title", item.title);
    if (title === null) return;
    const detailText = window.prompt("Edit detail", item.detail);
    if (detailText === null) return;
    try {
      await req("/items/" + item.id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...item, title, detail: detailText })
      });
      await select(active);
      setNotice("Knowledge item updated.");
    } catch (e) { setError(e.message); }
  };

  const items = detail?.items || [];
  const documents = detail?.documents || [];
  const approved = items.filter(item => item.status === "approved").length;
  const needsReview = items.filter(item => item.status === "needs_review" || item.status === "unknown").length;
  const filteredItems = useMemo(() => items.filter(item => {
    const text = (item.title + " " + item.detail + " " + (item.evidence || "")).toLowerCase();
    return text.includes(query.toLowerCase()) &&
      (categoryFilter === "all" || item.category === categoryFilter) &&
      (statusFilter === "all" || item.status === statusFilter);
  }), [items, query, categoryFilter, statusFilter]);

  const tabs = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "knowledge", label: "Knowledge review", icon: ClipboardCheck },
    { id: "sources", label: "Sources", icon: FileText },
    { id: "handover", label: "Handover", icon: ShieldCheck }
  ];

  return (
    <div className="app-shell">
      <aside className={"sidebar " + (mobileNav ? "sidebar-open" : "")}>
        <div className="brand">
          <div className="brand-mark"><BrainCircuit size={22}/></div>
          <div><b>Continuity<span>AI</span></b><small>PROJECT KNOWLEDGE HUB</small></div>
          <button className="mobile-close" onClick={() => setMobileNav(false)} aria-label="Close menu"><X size={18}/></button>
        </div>

        <div className="side-label">WORKSPACE</div>
        <button className={"side-link " + (tab === "overview" ? "side-active" : "")} onClick={() => { setTab("overview"); setMobileNav(false); }}>
          <LayoutDashboard size={17}/> Dashboard
        </button>
        <div className="workspace-heading"><span>YOUR PROJECTS</span><button onClick={() => document.getElementById("create-workspace")?.scrollIntoView({ behavior: "smooth" })} aria-label="Create workspace"><Plus size={16}/></button></div>
        <div className="project-list">
          {projects.map(project => (
            <button key={project.id} className={"project-link " + (project.id === active ? "project-current" : "")} onClick={() => select(project.id)}>
              <span className="project-dot"/><span className="project-name">{project.name}</span>
            </button>
          ))}
          {!projects.length && <p className="empty-side">Your workspaces will appear here.</p>}
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-tip"><Sparkles size={16}/><p><b>Keep context connected.</b><br/>Review source-backed knowledge before sharing a handover.</p></div>
          <div className="sidebar-foot"><span className="online-dot"/> API workspace</div>
        </div>
      </aside>

      {mobileNav && <button className="mobile-backdrop" onClick={() => setMobileNav(false)} aria-label="Close navigation"/>}

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open menu"><Menu size={20}/></button>
            <span className="crumb-muted">CONTINUITYAI</span><span className="crumb-slash">/</span><b>{detail?.name || "Workspace dashboard"}</b>
          </div>
          <div className="topbar-actions">
            <span className="secure-label"><ShieldCheck size={14}/> Evidence-first workflow</span>
            <button className="icon-button" onClick={() => refresh(active)} title="Refresh workspace"><RefreshCw size={16}/></button>
          </div>
        </header>

        <div className="content-wrap">
          {error && <div className="toast toast-error"><AlertTriangle size={16}/><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
          {notice && <div className="toast toast-success"><CheckCircle2 size={16}/><span>{notice}</span><button onClick={() => setNotice("")}>Dismiss</button></div>}

          {!detail ? (
            <section className="empty-state">
              <div className="empty-icon"><BrainCircuit size={34}/></div>
              <p className="eyebrow">PROJECT KNOWLEDGE CONTINUITY</p>
              <h1>Keep the knowledge.<br/><span>Continue the work.</span></h1>
              <p className="empty-copy">Turn scattered project documents into a structured, evidence-linked handover your team can trust.</p>
              <a className="primary-button" href="#create-workspace"><Plus size={17}/> Create your first workspace</a>
            </section>
          ) : (
            <>
              <section className="page-intro">
                <div>
                  <div className="eyebrow">PROJECT WORKSPACE <span className="eyebrow-id">/ #{active}</span></div>
                  <h1>{detail.name}</h1>
                  <p>{detail.description || "Your project's decisions, tasks, risks and open questions — all in one place."}</p>
                </div>
                <div className="intro-actions">
                  <label className="secondary-button"><Upload size={16}/> Add source<input type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={upload}/></label>
                  <a className="primary-button" href={API + "/projects/" + active + "/handover.md"}><Download size={16}/> Export handover</a>
                </div>
              </section>

              <nav className="tab-bar" aria-label="Project sections">
                {tabs.map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? "tab-active" : ""} onClick={() => setTab(id)}><Icon size={16}/>{label}{id === "knowledge" && needsReview > 0 && <span className="tab-count">{needsReview}</span>}</button>)}
              </nav>

              {tab === "overview" && (
                <>
                  <div className="metric-grid">
                    <article className="metric-card"><div className="metric-icon icon-blue"><FileText size={19}/></div><div className="metric-value">{documents.length}</div><div className="metric-label">Source documents</div><div className="metric-foot">Uploaded project context</div></article>
                    <article className="metric-card"><div className="metric-icon icon-violet"><Layers3 size={19}/></div><div className="metric-value">{items.length}</div><div className="metric-label">Knowledge items</div><div className="metric-foot">Decisions, tasks, risks & questions</div></article>
                    <article className="metric-card"><div className="metric-icon icon-green"><CheckCircle2 size={19}/></div><div className="metric-value">{approved}</div><div className="metric-label">Approved items</div><div className="metric-foot">Reviewed and verified</div></article>
                    <article className="metric-card"><div className="metric-icon icon-amber"><Clock3 size={19}/></div><div className="metric-value">{needsReview}</div><div className="metric-label">Need attention</div><div className="metric-foot">Awaiting a review decision</div></article>
                  </div>

                  <div className="overview-grid">
                    <section className="surface-card readiness-card">
                      <div className="section-heading"><div><span className="eyebrow">HANDOVER HEALTH</span><h2>Readiness overview</h2></div><span className="status-pill"><span className="status-dot"/> Live summary</span></div>
                      <div className="readiness-content">
                        <div className="readiness-ring" style={{ "--progress": (handover?.readiness || 0) + "%" }}><div><strong>{handover?.readiness ?? 0}%</strong><span>ready</span></div></div>
                        <div className="readiness-copy"><h3>{(handover?.readiness ?? 0) >= 80 ? "Good progress" : "Build your handover"}</h3><p>Readiness reflects approved knowledge coverage across decisions, tasks, risks and questions.</p><button className="text-link" onClick={() => setTab("handover")}>View handover details <ArrowUpRight size={15}/></button></div>
                      </div>
                      <div className="mini-progress"><div><span>Approved knowledge</span><b>{approved} / {items.length}</b></div><div className="progress-track"><span style={{ width: (items.length ? approved / items.length * 100 : 0) + "%" }}/></div></div>
                    </section>

                    <section className="surface-card action-card">
                      <div className="section-heading"><div><span className="eyebrow">NEXT STEPS</span><h2>Move work forward</h2></div><Sparkles size={19} className="heading-spark"/></div>
                      <button className="action-row" onClick={() => setTab("knowledge")}><span className="action-icon"><ClipboardCheck size={17}/></span><span><b>Review extracted knowledge</b><small>{needsReview} items waiting for review</small></span><ArrowUpRight size={16}/></button>
                      <label className="action-row action-label"><span className="action-icon"><Upload size={17}/></span><span><b>Upload project documents</b><small>PDF, DOCX, TXT or Markdown</small></span><Plus size={17}/><input type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={upload}/></label>
                      <button className="action-row" onClick={() => setTab("sources")}><span className="action-icon"><FileText size={17}/></span><span><b>Explore source library</b><small>{documents.length} documents connected</small></span><ArrowUpRight size={16}/></button>
                    </section>
                  </div>

                  <section className="surface-card recent-card">
                    <div className="section-heading"><div><span className="eyebrow">PROJECT CONTEXT</span><h2>Recent source documents</h2></div><button className="text-link" onClick={() => setTab("sources")}>View all <ArrowUpRight size={15}/></button></div>
                    {documents.length ? documents.slice(-4).reverse().map(doc => <div className="document-row" key={doc.id}><div className="doc-icon"><FileText size={17}/></div><div className="doc-info"><b>{doc.filename}</b><small>Source document #{doc.id}</small></div><span className="doc-date">{doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString() : "Uploaded"}</span></div>) : <div className="inline-empty"><FileText size={20}/><span>No source documents yet. Upload a project file to start extracting knowledge.</span></div>}
                  </section>
                </>
              )}

              {tab === "knowledge" && (
                <section className="surface-card knowledge-card">
                  <div className="section-heading"><div><span className="eyebrow">EVIDENCE REVIEW</span><h2>Knowledge items</h2><p className="section-subtitle">Check each extracted item against its source before approving it.</p></div><span className="total-pill">{filteredItems.length} of {items.length} items</span></div>
                  <div className="filter-row">
                    <div className="search-box"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search title, detail or evidence..."/></div>
                    <select value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)} aria-label="Filter category"><option value="all">All categories</option><option value="decision">Decisions</option><option value="task">Tasks</option><option value="risk">Risks</option><option value="question">Questions</option></select>
                    <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} aria-label="Filter status"><option value="all">All statuses</option><option value="needs_review">Needs review</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="unknown">Unknown</option></select>
                  </div>
                  {filteredItems.length ? filteredItems.map(item => (
                    <article className="knowledge-item" key={item.id}>
                      <div className="knowledge-main">
                        <div className="item-meta"><span className={"category-tag category-" + item.category}>{item.category}</span><span className={"review-status status-" + item.status}>{item.status.replaceAll("_", " ")}</span>{item.verified && <span className="verified-label"><ShieldCheck size={12}/> Verified</span>}</div>
                        <h3>{item.title}</h3><p className="item-detail">{item.detail}</p>
                        <div className="evidence-box"><span className="evidence-label">SOURCE EVIDENCE</span><p>{item.evidence || "No evidence snippet available."}</p><small><FileText size={12}/> Document #{item.source_id}</small></div>
                      </div>
                      <div className="item-actions"><button className="small-button" onClick={() => edit(item)}>Edit</button><button className="small-button approve-button" onClick={() => review(item, "approved")}><CheckCircle2 size={13}/> Approve</button><button className="small-button" onClick={() => review(item, "rejected")}>Reject</button><button className="small-button" onClick={() => review(item, "unknown")}>Unknown</button></div>
                    </article>
                  )) : <div className="inline-empty"><Search size={20}/><span>No matching knowledge items. Try changing your filters or upload another source.</span></div>}
                </section>
              )}

              {tab === "sources" && (
                <section className="surface-card">
                  <div className="section-heading"><div><span className="eyebrow">CONNECTED CONTEXT</span><h2>Source library</h2><p className="section-subtitle">Documents provide traceable evidence for extracted project knowledge.</p></div><label className="secondary-button"><Upload size={15}/> Upload source<input type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={upload}/></label></div>
                  {documents.length ? <div className="source-grid">{documents.map(doc => <article className="source-card" key={doc.id}><div className="doc-icon"><FileText size={20}/></div><div><b>{doc.filename}</b><p>Document #{doc.id}</p><small>{doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleString() : "Date unavailable"}</small></div><span className="source-connected"><CheckCircle2 size={13}/> Connected</span></article>)}</div> : <div className="inline-empty"><FileText size={20}/><span>No sources added yet. Upload a PDF, DOCX, TXT or Markdown file.</span></div>}
                </section>
              )}

              {tab === "handover" && (
                <div className="handover-layout">
                  <section className="surface-card handover-main">
                    <div className="section-heading"><div><span className="eyebrow">HANDOVER REPORT</span><h2>Project readiness</h2><p className="section-subtitle">A snapshot of the knowledge that is ready to transfer.</p></div><a className="primary-button" href={API + "/projects/" + active + "/handover.md"}><Download size={15}/> Download .md</a></div>
                    <div className="handover-score"><div><strong>{handover?.readiness ?? 0}%</strong><span>readiness score</span></div><div className="score-track"><span style={{ width: (handover?.readiness || 0) + "%" }}/></div></div>
                    <div className="handover-stats"><div><b>{handover?.source_count ?? documents.length}</b><span>Sources</span></div><div><b>{handover?.approved_count ?? approved}</b><span>Approved</span></div><div><b>{handover?.review_count ?? needsReview}</b><span>Need review</span></div></div>
                    <h3 className="subsection-title">Items requiring attention</h3>
                    {(handover?.gaps || []).length ? handover.gaps.map(item => <div className="gap-row" key={item.id}><AlertTriangle size={16}/><div><b>{item.title}</b><small>{item.category} · {item.status.replaceAll("_", " ")}</small></div><button onClick={() => setTab("knowledge")}>Review</button></div>) : <div className="inline-empty"><CheckCircle2 size={19}/><span>No unresolved review items in this handover.</span></div>}
                  </section>
                  <section className="surface-card handover-side">
                    <span className="eyebrow">RECOMMENDED CHECKLIST</span><h2>Before you hand over</h2>
                    {(handover?.next_steps || []).map((step, index) => <div className="checklist-row" key={index}><span>{index + 1}</span><p>{step}</p></div>)}
                    <div className="handover-note"><ShieldCheck size={17}/><p>Only approve information after checking its source evidence. A high score does not replace human review.</p></div>
                  </section>
                </div>
              )}
            </>
          )}

          <section className="create-section" id="create-workspace">
            <div><span className="eyebrow">GET STARTED</span><h2>Create a workspace</h2><p>Start a separate knowledge space for another project or team.</p></div>
            <form onSubmit={create} className="create-form"><input value={name} onChange={e => setName(e.target.value)} placeholder="Project name" required/><input value={description} onChange={e => setDescription(e.target.value)} placeholder="Short project description (optional)"/><button className="primary-button" type="submit" disabled={busy}><Plus size={16}/> Create workspace</button></form>
          </section>
        </div>

        <footer className="app-footer"><span>CONTINUITYAI</span><span>Never let project knowledge leave with a person.</span><a href="https://github.com/Jayramb26/ContinuityAI" target="_blank" rel="noreferrer">Open source repository <ExternalLink size={12}/></a></footer>
      </main>
      {busy && <div className="busy-indicator"><span className="spinner"/> Updating workspace…</div>}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App/>);
