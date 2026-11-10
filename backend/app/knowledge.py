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
                    items.append({"category": category, "title": s[:115], "detail": s,
                                  "evidence": s, "status": "needs_review", "verified": False})
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
