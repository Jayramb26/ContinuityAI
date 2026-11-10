import os, json, re
import httpx

CATEGORIES = {
    "decision": ["decided", "decision", "agreed", "selected", "chosen", "we will use", "approved"],
    "task": ["todo", "to-do", "action item", "must implement", "need to", "will complete", "assigned"],
    "risk": ["risk", "blocker", "issue", "dependency", "may fail", "concern", "delayed"],
    "question": ["question", "unclear", "confirm", "tbd", "unknown", "not sure", "pending clarification"],
}

def heuristic_extract(text: str):
    """Conservative baseline: sentence candidates retain their exact source evidence."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    items, seen = [], set()
    for sentence in sentences:
        s = sentence.strip(" •\t-#")
        if len(s) < 24 or len(s) > 500:
            continue
        low = s.lower()
        for category, words in CATEGORIES.items():
            if any(w in low for w in words):
                key = (category, low)
                if key not in seen:
                    seen.add(key)
                    # Only capture ownership and dates when explicitly written in the source.
                    owner_match = re.search(r"\b(?:assigned to|owner\s*[:=]|responsible(?: person)?\s*[:=])\s*([A-Z][a-z]+(?: [A-Z][a-z]+){0,2})", s, re.I)
                    date_match = re.search(r"\b(?:due|by)\s+(\d{4}-\d{2}-\d{2})\b", s, re.I)
                    priority = "critical" if re.search(r"\b(critical|showstopper)\b", low) else "high" if re.search(r"\b(high priority|urgent|severe)\b", low) else "medium"
                    work_status = "blocked" if re.search(r"\b(blocked|blocker|waiting on)\b", low) else "done" if re.search(r"\b(completed|finished|done)\b", low) else "in_progress" if re.search(r"\b(in progress|currently working)\b", low) else "open"
                    items.append({"category": category, "title": s[:115], "detail": s,
                                  "evidence": s, "status": "needs_review", "verified": False,
                                  "owner": owner_match.group(1).strip().rstrip(".,;") if owner_match else "",
                                  "due_date": date_match.group(1) if date_match else "",
                                  "priority": priority, "work_status": work_status})
                break
    return items[:80]

async def ai_extract(text: str):
    base, key, model = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    if not base or not key:
        return None
    prompt = "Extract candidate project decisions, tasks, risks, and unresolved questions. Return ONLY JSON array. Each item must have category, title, detail, evidence. Evidence must be a verbatim substring of source. Do not infer missing facts. Source:\n" + text[:18000]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(base.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]})
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    content = re.sub(r"^\x60{3}(?:json)?|\x60{3}$", "", content.strip(), flags=re.M).strip()
    data = json.loads(content)
    valid = []
    for x in data:
        ev = str(x.get("evidence", ""))
        if x.get("category") in {"decision", "task", "risk", "question"} and ev and ev in text:
            valid.append({"category": x["category"], "title": str(x.get("title", ev))[:300],
                          "detail": str(x.get("detail", ev)), "evidence": ev,
                          "status": "needs_review", "verified": False})
    return valid[:80]
