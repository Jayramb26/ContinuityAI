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
}

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

def answer_project_question(question, documents, items):
    """Retrieve matching source excerpts and approved knowledge; never invent an answer."""
    q_terms = terms(question)
    if not q_terms:
        return {"answer": "Please ask a more specific question using project terms.", "matches": [], "confidence": "none"}
    matches = []
    for item in items:
        text = " ".join([item.get("title", ""), item.get("detail", ""), item.get("evidence", "")])
        overlap = q_terms & terms(text)
        if overlap:
            approved = item.get("status") == "approved"
            matches.append({
                "kind": "knowledge_item", "item_id": item["id"], "source_id": item.get("source_id"),
                "title": item.get("title", ""), "excerpt": item.get("evidence") or item.get("detail", ""),
                "review_status": item.get("status"), "matched_terms": sorted(overlap),
                "score": len(overlap) + (2 if approved else 0), "approved": approved,
            })
    for doc in documents:
        content = doc.get("content", "")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", content):
            excerpt = sentence.strip()
            if len(excerpt) < 12:
                continue
            overlap = q_terms & terms(excerpt)
            if overlap:
                matches.append({
                    "kind": "source_excerpt", "source_id": doc["id"], "filename": doc["filename"],
                    "title": doc["filename"], "excerpt": excerpt[:700],
                    "review_status": "source_unreviewed", "matched_terms": sorted(overlap),
                    "score": len(overlap), "approved": False,
                })
    matches.sort(key=lambda x: (x["score"], x["approved"]), reverse=True)
    top = matches[:5]
    if not top:
        answer = "I couldn't find a matching statement in this workspace's uploaded sources or recorded knowledge. Add a source or ask the project owner; I won't guess."
        confidence = "none"
    else:
        best = top[0]
        prefix = "Approved knowledge says: " if best["approved"] else "The closest source passage says (not yet human-approved): "
        answer = prefix + best["excerpt"]
        confidence = "medium" if best["score"] < 3 or not best["approved"] else "high"
    return {"answer": answer, "matches": [{k: v for k, v in x.items() if k != "score"} for x in top],
            "confidence": confidence, "disclaimer": "Answers are retrieval-based excerpts, not generated facts. Verify the linked source and review status."}
