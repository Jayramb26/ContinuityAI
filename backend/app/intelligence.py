"""Transparent, deterministic analysis over workspace knowledge.

This module does not claim semantic understanding: every flag is a review prompt
with the source text that triggered it.
"""
import re

STOP = {
    "about", "after", "again", "also", "because", "before", "being", "between",
    "could", "does", "from", "have", "into", "just", "more", "most", "must",
    "need", "only", "other", "same", "should", "some", "such", "than", "that",
    "their", "there", "these", "they", "this", "those", "through", "under",
    "until", "using", "very", "what", "when", "where", "which", "while",
    "will", "with", "would", "your", "project", "task", "decision", "risk",
    "the", "and", "for", "are", "but", "can", "who", "own", "owns", "does",
    "is", "was", "were", "how", "why", "tell", "explain", "describe",
}

DEFINITION_CUES = (
    " is a ", " is an ", " is the ", "platform", "software", "application",
    "system", "tool", "helps", "enables", "allows", "designed to", "built to",
    "turns ", "converts ", "organises ", "organizes ",
)

def terms(value):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (value or "").lower()) if w not in STOP}

def analyze_project(items):
    """Return explicit dependency cues, narrow contradiction candidates and gaps."""
    rows = list(items)
    dependencies = []
    gaps = []
    conflicts = []
    for item in rows:
        text = " ".join([item.get("title", ""), item.get("detail", ""), item.get("evidence", "")])
        match = re.search(r"\b(depends on|blocked by|requires|waiting for|after)\b([^.;\n]{3,180})", text, re.I)
        if match:
            dependencies.append({
                "item_id": item["id"], "title": item["title"],
                "relation": match.group(1).lower(), "related_text": match.group(2).strip(),
                "evidence": match.group(0).strip(), "source_id": item.get("source_id"),
                "review_status": item.get("status"),
            })
        if item.get("category") == "task":
            if not (item.get("owner") or "").strip():
                gaps.append({"item_id": item["id"], "kind": "missing_owner", "message": "Task has no named owner.", "title": item["title"]})
            if not (item.get("due_date") or "").strip():
                gaps.append({"item_id": item["id"], "kind": "missing_due_date", "message": "Task has no due date.", "title": item["title"]})
        if item.get("category") == "decision" and not (item.get("evidence") or "").strip():
            gaps.append({"item_id": item["id"], "kind": "missing_evidence", "message": "Decision has no source evidence attached.", "title": item["title"]})
        if item.get("status") in {"needs_review", "unknown"}:
            gaps.append({"item_id": item["id"], "kind": "awaiting_review", "message": "Candidate knowledge has not been approved by a human.", "title": item["title"]})

    decisions = [x for x in rows if x.get("category") == "decision"]
    for index, left in enumerate(decisions):
        left_text = " ".join([left.get("title", ""), left.get("detail", ""), left.get("evidence", "")])
        left_terms = terms(left_text)
        left_negative = bool(re.search(r"\b(not|never|no longer|instead of|rejected|cancelled|canceled|won't|cannot)\b", left_text, re.I))
        for right in decisions[index + 1:]:
            right_text = " ".join([right.get("title", ""), right.get("detail", ""), right.get("evidence", "")])
            right_terms = terms(right_text)
            overlap = sorted(left_terms & right_terms)
            right_negative = bool(re.search(r"\b(not|never|no longer|instead of|rejected|cancelled|canceled|won't|cannot)\b", right_text, re.I))
            if len(overlap) >= 2 and left_negative != right_negative:
                conflicts.append({
                    "item_ids": [left["id"], right["id"]],
                    "titles": [left["title"], right["title"]],
                    "shared_terms": overlap[:8],
                    "evidence": [left.get("evidence", ""), right.get("evidence", "")],
                    "message": "These decision candidates share key terms but differ in explicit negation. Check whether the decision changed or the records conflict.",
                    "review_required": True,
                })
    return {
        "dependencies": dependencies,
        "possible_conflicts": conflicts,
        "knowledge_gaps": gaps,
        "counts": {"dependencies": len(dependencies), "possible_conflicts": len(conflicts), "knowledge_gaps": len(gaps)},
        "method": "Rule-based cues only. These are review prompts, not verified dependency links or semantic contradiction findings.",
    }

def _is_noise_passage(value, filename=""):
    """Reject PDF furniture, URLs, repeated filenames and heading-like fragments."""
    text = re.sub(r"\s+", " ", (value or "")).strip()
    if len(text) < 45 or len(text.split()) < 7:
        return True
    if re.search(r"https?://|www\.", text, re.I):
        return True
    if re.search(r"\b\S+\.(pdf|docx?|pptx?)\b", text, re.I):
        return True
    if filename and text.casefold() == filename.casefold():
        return True
    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters and letters.isupper():
        return True
    # Standalone repeated report titles and navigation labels are not answers.
    if re.match(r"^(source excerpt|contents|table of contents|continuityai\s*[—-])", text, re.I):
        return True
    return False

def _passages(content):
    """Build readable context windows; PDF extraction often breaks sentences across lines."""
    # A single newline in extracted PDF text is usually a visual line-wrap, not a paragraph.
    normalized = re.sub(r"\s+", " ", (content or "")).strip()
    sentences = [
        re.sub(r"\s+", " ", piece).strip()
        for piece in re.split(r"(?<=[.!?])\s+", normalized)
        if piece.strip()
    ]
    # Include adjacent sentences so sentence fragments at PDF boundaries gain context.
    windows = list(sentences)
    windows.extend(
        sentences[i] + " " + sentences[i + 1]
        for i in range(len(sentences) - 1)
    )
    return windows

def _definition_focus(value, subject="continuityai"):
    """Return a sentence that directly defines the product, when one exists."""
    sentences = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"(?<=[.!?])\s+", value or "") if part.strip()]
    for sentence in sentences:
        if (re.search(rf"\b{re.escape(subject)}\b", sentence, re.I)
                and re.search(r"\b(?:is|are)\s+(?:an?\s+|the\s+)?", sentence, re.I)
                and re.search(r"\b(?:system|platform|software|tool|application|service)\b", sentence, re.I)):
            return sentence[:700]
    return ""

def answer_project_question(question, documents, items):
    """Retrieve relevant, non-duplicated source excerpts; do not guess when evidence is weak."""
    q_terms = terms(question)
    if not q_terms:
        return {"answer": "Please ask a more specific question using project terms.", "matches": [], "confidence": "none"}

    lowered_question = (question or "").lower()
    definition_intent = bool(re.search(r"\b(what is|what are|define|describe|explain)\b", lowered_question))
    # For definition questions, the named subject is usually the first meaningful query term.
    subject_terms = set(q_terms)
    matches = []
    seen = set()

    def add_match(candidate):
        excerpt = re.sub(r"\s+", " ", candidate.get("excerpt", "")).strip()
        key = re.sub(r"[^a-z0-9]+", " ", excerpt.lower()).strip()
        if not key or key in seen:
            return
        candidate_terms = terms(key)
        # Suppress near-identical excerpts from multiple versions of the same PDF.
        for previous in matches:
            previous_terms = terms(previous.get("excerpt", ""))
            union = candidate_terms | previous_terms
            if union and len(candidate_terms & previous_terms) / len(union) >= 0.78:
                return
        seen.add(key)
        candidate["excerpt"] = excerpt[:700]
        matches.append(candidate)

    for item in items:
        detail = item.get("detail") or ""
        evidence = item.get("evidence") or ""
        searchable = " ".join([item.get("title", ""), detail, evidence])
        overlap = q_terms & terms(searchable)
        if not overlap:
            continue
        # Prefer actual detail/evidence over short autogenerated item titles.
        excerpt = evidence if len(evidence.strip()) >= 45 else detail
        if _is_noise_passage(excerpt):
            continue
        approved = item.get("status") == "approved"
        score = len(overlap) * 3 + (2 if approved else 0)
        if definition_intent and any(term in searchable.lower() for term in subject_terms):
            score += 2
        add_match({
            "kind": "knowledge_item", "item_id": item["id"], "source_id": item.get("source_id"),
            "title": item.get("title", ""), "excerpt": excerpt,
            "review_status": item.get("status"), "matched_terms": sorted(overlap),
            "score": score, "approved": approved,
        })

    for doc in documents:
        content = doc.get("content", "")
        filename = doc.get("filename", "")
        for excerpt in _passages(content):
            if _is_noise_passage(excerpt, filename):
                continue
            overlap = q_terms & terms(excerpt)
            if not overlap:
                continue
            lowered = " " + excerpt.lower() + " "
            score = len(overlap) * 3
            selected_excerpt = excerpt
            if definition_intent:
                # Prefer a direct product definition over architecture diagrams or generic mentions.
                direct_definition = _definition_focus(excerpt)
                if direct_definition:
                    selected_excerpt = direct_definition
                    score += 25
                if any(term in terms(excerpt) for term in subject_terms):
                    score += 3
                if any(cue in lowered for cue in DEFINITION_CUES):
                    score += 5
                if re.search(r"\b(ingests|captures|organises|organizes|connects|tracks|transforms|turns|helps)\b", lowered):
                    score += 2
                if re.search(r"\b(system flow|architecture diagram|frontend layer|backend & storage|ai pipeline|figure \d)\b", lowered):
                    score -= 8
            add_match({
                "kind": "source_excerpt", "source_id": doc["id"], "filename": filename,
                "title": filename, "excerpt": selected_excerpt,
                "review_status": "source_unreviewed", "matched_terms": sorted(overlap),
                "score": score, "approved": False,
            })

    matches.sort(key=lambda x: (x["score"], x["approved"], len(x["excerpt"])), reverse=True)
    top = matches[:3]
    # A one-word match such as only "ContinuityAI" is not enough to support a useful answer.
    minimum_score = 5 if len(q_terms) == 1 else 3
    if not top or top[0]["score"] < minimum_score:
        answer = "I couldn't find a sufficiently relevant explanation in this workspace's uploaded sources or recorded knowledge. Add a project overview or ask the project owner; I won't guess."
        confidence = "none"
        top = []
    else:
        best = top[0]
        prefix = "Approved knowledge says: " if best["approved"] else "The closest relevant source passage says (not yet human-approved): "
        answer = prefix + best["excerpt"]
        confidence = "high" if best["approved"] and best["score"] >= 7 else ("medium" if best["score"] >= 5 else "low")

    return {
        "answer": answer,
        "matches": [{k: v for k, v in x.items() if k != "score"} for x in top],
        "confidence": confidence,
        "disclaimer": "Answers are retrieval-based excerpts, not generated facts. Verify the linked source and review status.",
    }
