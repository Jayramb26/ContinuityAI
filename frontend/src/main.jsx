import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrainCircuit, Plus, Upload, CheckCircle2, AlertTriangle, FileText,
  Download, RefreshCw, Search, LayoutDashboard, Layers3, ClipboardCheck,
  Clock3, ShieldCheck, ArrowUpRight, Sparkles, CircleHelp, ListTodo,
  Menu, X, ExternalLink, ShieldAlert, FileCheck, Trash2, Network, MessageCircle
} from "lucide-react";
import "./style.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

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
  const [page, setPage] = useState("dashboard");
  const [tab, setTab] = useState("overview");
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [mobileNav, setMobileNav] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [brandGuidelines, setBrandGuidelines] = useState([]);
  const [brandReviews, setBrandReviews] = useState([]);
  const [brandName, setBrandName] = useState("");
  const [brandKind, setBrandKind] = useState("prohibited_term");
  const [brandRule, setBrandRule] = useState("");
  const [brandSeverity, setBrandSeverity] = useState("warning");
  const [brandDecisionNote, setBrandDecisionNote] = useState({});
  const [intelligence, setIntelligence] = useState(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantAnswer, setAssistantAnswer] = useState(null);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authToken, setAuthToken] = useState("");
  const [loginEmail, setLoginEmail] = useState("demo@continuityai.app");
  const [loginPassword, setLoginPassword] = useState("ContinuityDemo2026!");
  const [loginError, setLoginError] = useState("");
  const brandFileInput = useRef(null);

  const req = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    const token = authToken || sessionStorage.getItem("continuityai_access_token");
    if (token) headers.set("Authorization", "Bearer " + token);
    const response = await fetch(API + path, { ...options, headers });
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
      const target = id;
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

  useEffect(() => {
    const boot = async () => {
      try {
        const response = await fetch(API + "/auth/config");
        const config = await response.json();
        setAuthEnabled(Boolean(config.auth_enabled));
        if (config.auth_enabled) {
          const saved = sessionStorage.getItem("continuityai_access_token");
          if (saved) {
            const check = await fetch(API + "/auth/me", { headers: { Authorization: "Bearer " + saved } });
            if (check.ok) {
              setAuthToken(saved);
              await refresh(null);
            } else sessionStorage.removeItem("continuityai_access_token");
          }
        } else await refresh(null);
      } catch (e) { setError("Could not connect to the ContinuityAI API. " + e.message); }
      finally { setAuthChecked(true); }
    };
    boot();
  }, []);


  const signIn = async (event) => {
    event.preventDefault(); setLoginError("");
    try {
      const response = await fetch(API + "/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: loginEmail, password: loginPassword })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Sign in failed");
      sessionStorage.setItem("continuityai_access_token", data.access_token);
      setAuthToken(data.access_token);
      await refresh(null);
    } catch (e) { setLoginError(e.message); }
  };

  const signOut = () => {
    sessionStorage.removeItem("continuityai_access_token");
    setAuthToken(""); setProjects([]); setActive(null); setDetail(null); setHandover(null);
    setPage("dashboard"); setTab("overview");
  };

  const loadBrand = async () => {
    const [guidelines, reviews] = await Promise.all([req("/brand/guidelines"), req("/brand/reviews")]);
    setBrandGuidelines(guidelines); setBrandReviews(reviews);
    return { guidelines, reviews };
  };

  const openBrand = async () => {
    setPage("brand"); setMobileNav(false); setError("");
    try { await loadBrand(); } catch (e) { setError(/not found|404/i.test(e.message) ? "Brand Governance routes were not found on the connected API. Deploy the latest backend from the main branch, then refresh." : e.message); }
  };

  const saveBrandGuideline = async (event) => {
    event.preventDefault();
    try {
      await req("/brand/guidelines", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: brandName, kind: brandKind, content: brandRule, severity: brandSeverity }) });
      setBrandName(""); setBrandRule(""); await loadBrand(); setNotice("Approved brand rule added.");
    } catch (e) { setError(e.message); }
  };

  const uploadBrandContent = async (event) => {
    const input = event.target;
    const file = input.files?.[0];
    if (!file) return;
    setError(""); setNotice(""); setBusy(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await req("/brand/reviews", { method: "POST", body: form });
      await loadBrand();
      setNotice("Checked " + file.name + ": " + result.finding_count + " finding(s), including " + result.critical_count + " critical. Review the report below and record a human decision.");
      document.querySelector(".brand-review-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setError("Could not check " + file.name + ". " + e.message);
    } finally {
      setBusy(false);
      input.value = "";
    }
  };

  const decideBrandReview = async (review, status) => {
    try {
      await req("/brand/reviews/" + review.id, { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, decision_note: brandDecisionNote[review.id] || "" }) });
      await loadBrand(); setNotice("Human decision saved: " + status.replaceAll("_", " ") + ".");
    } catch (e) { setError(e.message); }
  };

  const deleteBrandGuideline = async (id) => {
    try { await req("/brand/guidelines/" + id, { method: "DELETE" }); await loadBrand(); setNotice("Guideline removed."); }
    catch (e) { setError(e.message); }
  };

  const select = async (id) => {
    setBusy(true); setError("");
    try {
      const [project, summary] = await Promise.all([
        req("/projects/" + id),
        req("/projects/" + id + "/handover")
      ]);
      setActive(id); setDetail(project); setHandover(summary);
      setPage("project"); setTab("overview"); setMobileNav(false);
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
      setCreateModalOpen(false);
      await refresh(project.id);
      setPage("project");
      setTab("overview");
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
      await select(active); setTab("knowledge");
      setNotice(status === "approved" ? "Item approved and verified." : "Review decision saved.");
    } catch (e) { setError(e.message); }
  };

  const updateWork = async (item, patch) => {
    try {
      await req("/items/" + item.id, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...item, ...patch }) });
      await select(active); setTab("knowledge");
      setNotice("Ownership and work status updated.");
    } catch (e) { setError(e.message); }
  };

  const addWorkItem = async () => {
    const category = window.prompt("Type: decision, task, risk or question", "task");
    if (!category) return;
    const title = window.prompt("What needs to be remembered?", "");
    if (!title) return;
    const detail = window.prompt("Add context or next action", "") ?? "";
    const owner = window.prompt("Who owns this? Leave blank if unknown", "") ?? "";
    const due_date = category.toLowerCase() === "task" ? (window.prompt("Due date (YYYY-MM-DD, optional)", "") ?? "") : "";
    try {
      await req("/projects/" + active + "/items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: category.toLowerCase(), title, detail, owner, due_date, priority: "medium", work_status: "open" }) });
      await select(active); setTab("knowledge"); setNotice("Work item added to project knowledge.");
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
      await select(active); setTab("knowledge");
      setNotice("Knowledge item updated.");
    } catch (e) { setError(e.message); }
  };


  const loadIntelligence = async () => {
    if (!active) return;
    try {
      const result = await req("/projects/" + active + "/intelligence");
      setIntelligence(result);
    } catch (e) { setError(e.message); }
  };

  const askAssistant = async (event) => {
    event.preventDefault();
    if (!assistantQuestion.trim() || !active) return;
    setAssistantBusy(true); setError(""); setAssistantAnswer(null);
    try {
      const result = await req("/projects/" + active + "/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: assistantQuestion.trim() })
      });
      setAssistantAnswer(result);
    } catch (e) { setError(e.message); }
    finally { setAssistantBusy(false); }
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
    { id: "handover", label: "Handover", icon: ShieldCheck },
    { id: "intelligence", label: "Intelligence", icon: Network },
    { id: "assistant", label: "Ask assistant", icon: MessageCircle }
  ];


  if (!authChecked) return <div className="auth-screen"><div className="auth-card"><div className="brand-mark"><BrainCircuit size={24}/></div><h1>ContinuityAI</h1><p>Connecting to your project workspace…</p></div></div>;
  if (authEnabled && !authToken) return (
    <div className="auth-screen">
      <section className="auth-card">
        <div className="brand-mark"><BrainCircuit size={24}/></div>
        <span className="eyebrow">CODE TITANS · PROJECT KNOWLEDGE HUB</span>
        <h1>Welcome back</h1>
        <p>Sign in to access the workspace and its project knowledge.</p>
        {loginError && <div className="toast toast-error">{loginError}</div>}
        <form className="auth-form" onSubmit={signIn}>
          <label>Email<input type="email" value={loginEmail} onChange={e => setLoginEmail(e.target.value)} required autoComplete="username"/></label>
          <label>Password<input type="password" value={loginPassword} onChange={e => setLoginPassword(e.target.value)} required autoComplete="current-password"/></label>
          <button className="primary-button" type="submit">Sign in to demo</button>
        </form>
        <div className="demo-credentials"><b>Shared judge demo account</b><span>Email: demo@continuityai.app</span><span>Password: ContinuityDemo2026!</span><small>Use only with synthetic demo data. The demo account is shared by evaluators.</small></div>
      </section>
    </div>
  );

  return (
    <div className="app-shell">
      <aside className={"sidebar " + (mobileNav ? "sidebar-open" : "")}>
        <div className="brand">
          <div className="brand-mark"><BrainCircuit size={22}/></div>
          <div><b>Continuity<span>AI</span></b><small>PROJECT KNOWLEDGE HUB</small></div>
          <button className="mobile-close" onClick={() => setMobileNav(false)} aria-label="Close menu"><X size={18}/></button>
        </div>

        <div className="side-label">WORKSPACE</div>
        <button type="button" className={"side-link " + (page === "dashboard" ? "side-active" : "")} onClick={() => { setPage("dashboard"); setMobileNav(false); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
          <LayoutDashboard size={17}/> Dashboard
        </button>
        <button type="button" className={"side-link " + (page === "brand" ? "side-active" : "")} onClick={openBrand}>
          <ShieldAlert size={17}/> Brand governance
        </button>
        <div className="workspace-heading" onClick={() => { setError(""); setCreateModalOpen(true); setMobileNav(false); }}><span>YOUR PROJECTS</span><button type="button" className="sidebar-add-workspace" onClick={event => { event.preventDefault(); event.stopPropagation(); setError(""); setCreateModalOpen(true); setMobileNav(false); }} aria-label="Create workspace" aria-haspopup="dialog" aria-expanded={createModalOpen} title="Create workspace"><Plus size={18}/></button></div>
        <div className="project-list">
          {projects.map(project => (
            <button key={project.id} className={"project-link " + (page === "project" && project.id === active ? "project-current" : "")} onClick={() => select(project.id)}>
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
            <span className="crumb-muted">CONTINUITYAI</span><span className="crumb-slash">/</span><b>{page === "dashboard" ? "Dashboard" : page === "brand" ? "Brand governance" : (detail?.name || "Project workspace")}</b>
          </div>
          <div className="topbar-actions">
            <span className="secure-label"><ShieldCheck size={14}/> Evidence-first workflow</span>{authEnabled && <button className="small-button" type="button" onClick={signOut}>Sign out</button>}
            <button className="icon-button" onClick={() => refresh(active)} title="Refresh workspace"><RefreshCw size={16}/></button>
          </div>
        </header>

        <div className="content-wrap">




          {error && <div className="toast toast-error"><AlertTriangle size={16}/><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
          {notice && <div className="toast toast-success"><CheckCircle2 size={16}/><span>{notice}</span><button onClick={() => setNotice("")}>Dismiss</button></div>}

          {page === "brand" ? (
            <div className="brand-governance-page">
              <section className="page-intro">
                <div><div className="eyebrow">CONTENT COMPLIANCE WORKFLOW</div><h1>Brand governance</h1><p>Check content against approved brand rules, explain every finding, and keep the final decision with a human reviewer.</p></div>
                <button type="button" className="primary-button" onClick={() => brandFileInput.current?.click()} disabled={busy}><Upload size={16}/>{busy ? "Checking content…" : "Check content"}</button><input ref={brandFileInput} type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={uploadBrandContent}/><span className="upload-hint">Choose a PDF, DOCX, TXT or MD file (max 10 MB)</span>
              </section>
              <div className="brand-workflow-steps"><div><b>01 · Define</b><span>Approved terms, facts, assets and tone</span></div><div><b>02 · Check</b><span>Evidence-linked rule matching</span></div><div><b>03 · Decide</b><span>Human approval, rejection or changes</span></div></div>
              <div className="brand-grid">
                <section className="surface-card brand-guideline-panel">
                  <div className="section-heading"><div><span className="eyebrow">SOURCE OF TRUTH</span><h2>Approved guidelines</h2><p className="section-subtitle">Create explicit rules before submitting content for review.</p></div><span className="total-pill">{brandGuidelines.length} rules</span></div>
                  <form className="brand-rule-form" onSubmit={saveBrandGuideline}>
                    <label>Rule name<input value={brandName} onChange={e => setBrandName(e.target.value)} placeholder="e.g. Product name spelling" required/></label>
                    <div className="brand-form-row"><label>Rule type<select value={brandKind} onChange={e => setBrandKind(e.target.value)}><option value="required_term">Required term</option><option value="prohibited_term">Prohibited term</option><option value="approved_fact">Approved fact</option><option value="approved_asset">Approved asset / identifier</option><option value="tone_rule">Tone of voice</option></select></label><label>Severity<select value={brandSeverity} onChange={e => setBrandSeverity(e.target.value)}><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select></label></div>
                    <label>Approved rule or exact phrase<textarea value={brandRule} onChange={e => setBrandRule(e.target.value)} rows={3} placeholder="Enter exact approved/prohibited wording, fact, asset URL/name, or tone guidance." required/></label>
                    <button className="primary-button" type="submit"><Plus size={15}/> Add guideline</button>
                  </form>
                  <div className="brand-guideline-list">{brandGuidelines.length ? brandGuidelines.map(rule => <article className="brand-guideline" key={rule.id}><div><span className={"brand-kind kind-" + rule.kind}>{rule.kind.replaceAll("_"," ")}</span><b>{rule.name}</b><p>{rule.content}</p><small>{rule.severity} severity</small></div><button className="small-button" onClick={() => deleteBrandGuideline(rule.id)} title="Remove guideline"><Trash2 size={14}/></button></article>) : <div className="inline-empty"><ShieldAlert size={20}/><span>No brand rules yet. Add at least one approved guideline before checking content.</span></div>}</div>
                </section>
                <section className="surface-card brand-review-panel">
                  <div className="section-heading"><div><span className="eyebrow">CONTENT REVIEW QUEUE</span><h2>Submitted content</h2><p className="section-subtitle">Automated checks flag potential issues; reviewers make the final call.</p></div><span className="total-pill">{brandReviews.length} submissions</span></div>
                  {brandReviews.length ? brandReviews.map(review => <article className="brand-review-card" key={review.id}>
                    <div className="brand-review-head"><div><h3>{review.filename}</h3><small>Submitted {new Date(review.created_at).toLocaleString()}</small></div><span className={"review-status status-" + (review.status === "pending" ? "needs_review" : review.status)}>{review.status.replaceAll("_"," ")}</span></div>
                    <div className="brand-review-summary"><span><b>{review.finding_count}</b> findings</span><span><b>{review.critical_count}</b> critical</span></div>
                    {review.findings.length ? review.findings.map((finding,index) => <div className={"brand-finding severity-" + finding.severity} key={index}><div><span>{finding.severity}</span><b>{finding.issue}</b></div><p>{finding.explanation}</p><small>Suggested action: {finding.recommendation}</small></div>) : <div className="brand-clean-result"><CheckCircle2 size={16}/> No configured rule violations detected. Human review is still required.</div>}
                    <details className="brand-content-preview"><summary>View submitted content</summary><pre>{review.content}</pre></details>
                    {review.status === "pending" ? <div className="brand-human-decision"><label>Reviewer note<textarea rows={2} value={brandDecisionNote[review.id] || ""} onChange={e => setBrandDecisionNote(prev => ({...prev,[review.id]:e.target.value}))} placeholder="Explain approval, rejection or required changes."/></label><div><button className="small-button approve-button" onClick={() => decideBrandReview(review,"approved")}><CheckCircle2 size={13}/> Approve</button><button className="small-button" onClick={() => decideBrandReview(review,"changes_requested")}>Request changes</button><button className="small-button" onClick={() => decideBrandReview(review,"rejected")}>Reject</button></div></div> : <p className="brand-decision-note"><b>Human decision:</b> {review.status.replaceAll("_"," ")} {review.decision_note ? "— " + review.decision_note : ""}</p>}
                  </article>) : <div className="dashboard-empty"><div className="empty-icon"><FileCheck size={25}/></div><h3>No content submitted</h3><p>Add approved rules, then upload a content file to see a review report with explainable findings and human decision controls.</p><button type="button" className="primary-button" onClick={() => brandFileInput.current?.click()} disabled={busy}><Upload size={15}/>{busy ? "Checking content…" : "Upload content"}</button></div>}
                </section>
              </div>
              <p className="brand-disclaimer">Checking is deterministic phrase/rule matching, not legal review or semantic fact verification. Missing facts are marked for verification, not labelled false. A human decision is required before publication.</p>
            </div>
          ) : page === "dashboard" ? (
            <>
              <section className="page-intro dashboard-heading">
                <div><div className="eyebrow">YOUR WORKSPACE HUB</div><h1>Good to have you back.</h1><p>Keep project knowledge connected, track your workspaces and prepare reliable team handovers.</p></div>
                <button type="button" className="primary-button dashboard-create-button" onClick={() => setCreateModalOpen(true)}><Plus size={18}/> Create new workspace</button>
              </section>
              <section className="dashboard-stats">
                <article className="dashboard-stat"><span className="dashboard-stat-icon"><Layers3 size={18}/></span><div><strong>{projects.length}</strong><b>Total workspaces</b><small>Projects in your knowledge hub</small></div></article>
                <article className="dashboard-stat"><span className="dashboard-stat-icon"><ShieldCheck size={18}/></span><div><strong>Evidence-first</strong><b>Knowledge workflow</b><small>Source-backed project context</small></div></article>
                <article className="dashboard-stat"><span className="dashboard-stat-icon"><FileText size={18}/></span><div><strong>4 stages</strong><b>Workspace toolkit</b><small>Overview · Review · Sources · Handover</small></div></article>
              </section>
              <section className="surface-card recent-card dashboard-workspaces">
                <div className="section-heading"><div><span className="eyebrow">PROJECT DIRECTORY</span><h2>Your workspaces</h2><p className="section-subtitle">Open a workspace to review its knowledge, sources and handover readiness.</p></div><span className="total-pill">{projects.length} total</span></div>
                {projects.length ? <div className="dashboard-project-grid">{projects.map(project => <article className="dashboard-project-card" key={project.id}>
                  <div className="dashboard-project-top"><span className="dashboard-project-icon"><Layers3 size={19}/></span><span className="dashboard-project-id">#{project.id}</span></div>
                  <h3>{project.name}</h3><p>{project.description || "Project knowledge and handover workspace."}</p>
                  <button type="button" className="dashboard-open-link" onClick={() => select(project.id)}>Open workspace <ArrowUpRight size={16}/></button>
                </article>)}</div> : <div className="dashboard-empty"><div className="empty-icon"><Layers3 size={25}/></div><h3>Your workspace hub is ready</h3><p>Create your first workspace to start collecting project decisions, tasks, risks and source documents.</p><button type="button" className="primary-button" onClick={() => setCreateModalOpen(true)}><Plus size={15}/> Create workspace</button></div>}
              </section>
            </>
          ) : !detail ? (
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
                {tabs.map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? "tab-active" : ""} onClick={() => { setTab(id); if (id === "intelligence") loadIntelligence(); }}><Icon size={16}/>{label}{id === "knowledge" && needsReview > 0 && <span className="tab-count">{needsReview}</span>}</button>)}
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
                  <div className="section-heading"><div><span className="eyebrow">EVIDENCE REVIEW</span><h2>Knowledge items</h2><p className="section-subtitle">Check evidence, assign ownership and track unfinished work.</p></div><div className="section-actions"><span className="total-pill">{filteredItems.length} of {items.length} items</span><button className="primary-button" type="button" onClick={addWorkItem}><Plus size={14}/> Add work item</button></div></div>
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
                        <div className="work-metadata"><label>Owner<input defaultValue={item.owner || ""} placeholder="Unassigned" onBlur={e => { if (e.target.value !== (item.owner || "")) updateWork(item, { owner: e.target.value }); }}/></label><label>Due date<input type="date" defaultValue={item.due_date || ""} onChange={e => updateWork(item, { due_date: e.target.value })}/></label><label>Priority<select value={item.priority || "medium"} onChange={e => updateWork(item, { priority: e.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label><label>Work status<select value={item.work_status || "open"} onChange={e => updateWork(item, { work_status: e.target.value })}><option value="open">Open</option><option value="in_progress">In progress</option><option value="blocked">Blocked</option><option value="done">Done</option></select></label></div><div className="evidence-box"><span className="evidence-label">SOURCE EVIDENCE</span><p>{item.evidence || "Manually recorded item — no source excerpt attached."}</p><small><FileText size={12}/> {item.source_id ? "Document #" + item.source_id : "Manually added"}</small></div>
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
                    <div className="handover-risk-summary"><div><b>{handover?.unassigned_tasks?.length ?? 0}</b><span>Unassigned tasks</span></div><div><b>{handover?.blocked_items?.length ?? 0}</b><span>Blocked items</span></div><div><b>{handover?.overdue_tasks?.length ?? 0}</b><span>Overdue tasks</span></div></div><h3 className="subsection-title">Unfinished work and ownership</h3>{(handover?.open_tasks || []).length ? handover.open_tasks.map(item => <div className="gap-row" key={"task-" + item.id}><ListTodo size={16}/><div><b>{item.title}</b><small>{item.owner || "UNASSIGNED"} · {item.work_status.replaceAll("_", " ")} · {item.due_date || "No due date"}</small></div><button onClick={() => setTab("knowledge")}>Update</button></div>) : <div className="inline-empty"><CheckCircle2 size={18}/><span>No unfinished tasks recorded.</span></div>}<h3 className="subsection-title">Items requiring attention</h3>
                    {(handover?.gaps || []).length ? handover.gaps.map(item => <div className="gap-row" key={item.id}><AlertTriangle size={16}/><div><b>{item.title}</b><small>{item.category} · {item.status.replaceAll("_", " ")}</small></div><button onClick={() => setTab("knowledge")}>Review</button></div>) : <div className="inline-empty"><CheckCircle2 size={19}/><span>No unresolved review items in this handover.</span></div>}
                  </section>
                  <section className="surface-card handover-side"><span className="eyebrow">PROJECT ACTIVITY</span><h2>Recent history</h2>{(detail?.activity || []).slice(0,8).map(event => <div className="activity-entry" key={event.id}><span className="activity-dot"/><div><b>{event.message}</b><small>{new Date(event.created_at).toLocaleString()}</small></div></div>)}{!(detail?.activity || []).length && <p className="section-subtitle">Activity will appear as your team adds sources and updates work.</p>}<div className="activity-add"><button className="secondary-button" type="button" onClick={async () => { const message = window.prompt("Record a project update, discussion or decision context"); if (message?.trim()) { try { await req("/projects/" + active + "/activity", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, event_type: "team_update" }) }); await select(active); setTab("handover"); } catch (e) { setError(e.message); } } }}>+ Record activity</button></div>
                    <span className="eyebrow">RECOMMENDED CHECKLIST</span><h2>Before you hand over</h2>
                    {(handover?.next_steps || []).map((step, index) => <div className="checklist-row" key={index}><span>{index + 1}</span><p>{step}</p></div>)}
                    <div className="handover-note"><ShieldCheck size={17}/><p>Only approve information after checking its source evidence. A high score does not replace human review.</p></div>
                  </section>
                </div>
              )}

              {tab === "intelligence" && (
                <section className="surface-card knowledge-card">
                  <div className="section-heading"><div><span className="eyebrow">KNOWLEDGE INTELLIGENCE</span><h2>Dependencies, conflicts and missing context</h2><p className="section-subtitle">Transparent rule-based checks surface items that need human attention.</p></div><button className="secondary-button" type="button" onClick={loadIntelligence}><RefreshCw size={14}/> Re-analyse</button></div>
                  {intelligence ? <>
                    <div className="dashboard-stats">
                      <article className="dashboard-stat"><div><strong>{intelligence.counts.dependencies}</strong><b>Dependency cues</b><small>Explicit phrases in source text</small></div></article>
                      <article className="dashboard-stat"><div><strong>{intelligence.counts.possible_conflicts}</strong><b>Possible conflicts</b><small>Opposing decision language</small></div></article>
                      <article className="dashboard-stat"><div><strong>{intelligence.counts.knowledge_gaps}</strong><b>Knowledge gaps</b><small>Missing ownership, dates or review</small></div></article>
                    </div>
                    <h3 className="subsection-title">Possible decision conflicts</h3>
                    {intelligence.possible_conflicts.length ? intelligence.possible_conflicts.map((item,index) => <article className="knowledge-item" key={index}><div className="item-meta"><span className="category-tag category-risk">review required</span></div><h3>{item.message}</h3><p>{item.titles.join(" ↔ ")}</p><div className="evidence-box"><span className="evidence-label">CONFLICTING SOURCE EVIDENCE</span><p>{item.evidence.join(" / ")}</p><small>Shared terms: {item.shared_terms.join(", ")}</small></div><button className="small-button" onClick={() => setTab("knowledge")}>Review knowledge items</button></article>) : <div className="inline-empty"><CheckCircle2 size={18}/>No possible conflicts detected by the current rule set.</div>}
                    <h3 className="subsection-title">Dependency cues</h3>
                    {intelligence.dependencies.length ? intelligence.dependencies.map((item,index) => <div className="gap-row" key={index}><Network size={16}/><div><b>{item.title}</b><small>{item.relation}: {item.related_text} · {item.review_status}</small><small>Evidence: {item.evidence}</small></div><button onClick={() => setTab("knowledge")}>Review</button></div>) : <div className="inline-empty">No explicit dependency phrases found.</div>}
                    <h3 className="subsection-title">Missing knowledge</h3>
                    {intelligence.knowledge_gaps.length ? intelligence.knowledge_gaps.map((item,index) => <div className="gap-row" key={index}><AlertTriangle size={16}/><div><b>{item.title}</b><small>{item.message}</small></div><button onClick={() => setTab("knowledge")}>Fix</button></div>) : <div className="inline-empty">No configured knowledge gaps detected.</div>}
                    <p className="brand-disclaimer">{intelligence.method}</p>
                  </> : <div className="inline-empty">Select “Re-analyse” to inspect the current workspace.</div>}
                </section>
              )}

              {tab === "assistant" && (
                <section className="surface-card knowledge-card">
                  <div className="section-heading"><div><span className="eyebrow">SOURCE-BACKED HANDOVER Q&A</span><h2>Ask your project knowledge</h2><p className="section-subtitle">Answers are retrieved from uploaded sources and recorded knowledge. Unsupported questions return no answer rather than a guess.</p></div><MessageCircle size={22}/></div>
                  <form className="brand-rule-form" onSubmit={askAssistant}>
                    <label>What do you need to know?<textarea rows={3} maxLength={500} value={assistantQuestion} onChange={e => setAssistantQuestion(e.target.value)} placeholder="e.g. What decision was made about the frontend? Who owns deployment?" required/></label>
                    <button className="primary-button" type="submit" disabled={assistantBusy || !assistantQuestion.trim()}>{assistantBusy ? "Searching sources…" : "Ask ContinuityAI"}</button>
                  </form>
                  {assistantAnswer && <article className="knowledge-item"><div className="item-meta"><span className="category-tag category-decision">confidence: {assistantAnswer.confidence}</span></div><h3>Retrieved answer</h3><p className="item-detail">{assistantAnswer.answer}</p>{assistantAnswer.matches.map((match,index) => <div className="evidence-box" key={index}><span className="evidence-label">{match.kind === "knowledge_item" ? "KNOWLEDGE ITEM" : "SOURCE EXCERPT"} · {match.review_status}</span><b>{match.title}</b><p>{match.excerpt}</p><small>{match.filename || (match.source_id ? "Source document #" + match.source_id : "Manual knowledge")} {match.item_id ? "· Item #" + match.item_id : ""}</small></div>)}<p className="brand-disclaimer">{assistantAnswer.disclaimer}</p></article>}
                </section>
              )}

            </>
          )}


        </div>

        <footer className="app-footer"><span>CONTINUITYAI</span><span>Never let project knowledge leave with a person.</span><a href="https://github.com/Jayramb26/ContinuityAI" target="_blank" rel="noreferrer">Open source repository <ExternalLink size={12}/></a></footer>
      </main>

      {createModalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) setCreateModalOpen(false); }}>
          <section className="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-modal-title">
            <div className="create-modal-heading"><div><span className="eyebrow">NEW PROJECT</span><h2 id="create-modal-title">Create workspace</h2><p>Give this project a name and a little context to get started.</p></div><button type="button" className="modal-close" onClick={() => setCreateModalOpen(false)} disabled={busy} aria-label="Close dialog"><X size={18}/></button></div>
            <form onSubmit={create} className="modal-form">
              <label htmlFor="workspace-name">Workspace name <span>*</span></label><input id="workspace-name" value={name} onChange={event => setName(event.target.value)} placeholder="e.g. SmartMeet — Team Workspace" required autoFocus />
              <label htmlFor="workspace-description">Description <small>Optional</small></label><textarea id="workspace-description" value={description} onChange={event => setDescription(event.target.value)} placeholder="What is this project about? Add a short summary for your team." rows={4}/>
              <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setCreateModalOpen(false)} disabled={busy}>Cancel</button><button type="submit" className="primary-button" disabled={busy}><Plus size={15}/> Create workspace</button></div>
            </form>
          </section>
        </div>
      )}
      {busy && <div className="busy-indicator"><span className="spinner"/> Updating workspace…</div>}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App/>);
