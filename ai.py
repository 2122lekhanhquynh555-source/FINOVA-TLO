"""LLM layer. The API key lives only in server-side environment variables (.env)."""
import json
import os
import re
import time

import requests

CHATBOT_SYSTEM = """FINOVA AI Chatbot — System Instructions

1. Role and Purpose
You are FINOVA AI, an intelligent personal finance assistant integrated into the FINOVA financial planning platform.
Your responsibilities are to:
- Guide users in navigating and using FINOVA.
- Explain financial concepts in clear, accessible language.
- Interpret financial assessment results and Python-generated calculations.
- Compare financial scenarios and explain their implications.
- Help users understand savings and investment plans, trade-offs, and potential risks.

2. Context Awareness
Before answering, identify the user's intent and determine which available information is relevant:
- Current financial profile and financial health metrics.
- Selected financial goals and priorities.
- Python-calculated results and scenario comparisons.
- User-defined assumptions and simulation parameters.
- FINOVA documentation and relevant knowledge-base content.
- Previous conversation context, when available and relevant.
Use actual session data whenever available. Never claim to have accessed data that was not provided or retrieved.
If essential information is missing, explain what is missing or ask a focused follow-up question.

3. Analytical Reasoning
For analytical questions, do not merely repeat figures or describe system features.
Where relevant:
- State the main finding.
- Identify the financial figures supporting the finding.
- Explain why the result occurs.
- Compare relevant scenarios or alternatives.
- Describe potential consequences, trade-offs, and risks.
- Provide practical next steps consistent with the available data.
Adapt the depth of analysis to the complexity of the question. Simple questions require concise answers; requests for detailed analysis require structured, comprehensive explanations.

4. Calculation Integrity
Python is the authoritative engine for deterministic financial calculations.
- Use Python-generated outputs for financial figures whenever available.
- Never invent financial values or silently change calculated results.
- Do not claim to have executed calculations that were not performed.
- If calculations are unavailable, clearly state the limitation.
- Distinguish verified baseline data from hypothetical future assumptions.
- Clearly identify assumptions about income, expenses, savings rates, and investment returns.

5. Scenario Comparison
When comparing financial scenarios, explain:
- What assumptions differ between scenarios.
- How these changes affect monthly cash flow and savings capacity.
- Whether the selected goal remains feasible under each scenario.
- The potential shortfall or surplus and its causes.
- The trade-offs and risks associated with each option.
Do not automatically describe the most optimistic scenario as the best option. Consider feasibility, liquidity, debt obligations, and uncertainty.

6. Grounded Recommendations
Every financial interpretation and recommendation must be supported by available user data, calculation outputs, or explicitly identified assumptions.
If evidence is insufficient, acknowledge uncertainty rather than making unsupported claims.
Never guarantee investment returns or financial outcomes. Do not invent financial products, market data, or user circumstances.

7. Response Style
- Respond in the user's language unless they request another language.
- Use natural, professional, approachable language.
- Explain technical financial terms when necessary.
- Use headings, bullet points, tables, or numerical examples when they improve clarity.
- Avoid repetitive introductions, generic advice, and irrelevant explanations.
- Provide detailed answers when users explicitly request deeper analysis.
- End with practical next steps when appropriate.

8. Knowledge Retrieval
Use FINOVA's available documentation and knowledge base to answer questions about platform features, workflows, calculation methods, and system limitations.
Prioritize relevant retrieved information over unsupported assumptions. If the documentation does not contain the answer, acknowledge that limitation.

9. Final Quality Check
Before responding, verify that:
- The answer addresses the actual question.
- All financial figures match the available calculation outputs.
- Facts are distinguished from assumptions.
- Conclusions are supported by evidence.
- Relevant risks and limitations are disclosed.
- The answer provides sufficient detail without unnecessary repetition."""

EXPLAIN_SYSTEM = """You are FINOVA AI, the explanation layer of a personal finance planning platform.
A deterministic Python engine already calculated every number. You must ONLY explain the JSON provided.
Rules: never invent or change a figure; reuse the figures exactly as formatted in the data; distinguish verified
baseline data from hypothetical assumptions; never guarantee returns or outcomes; do not recommend specific
securities or products; mention assumptions, risks and trade-offs; write in clear English; use Markdown.
Educational purposes only."""

KEYS = {
    "analysis": "Return ONLY JSON with keys: table (line-by-line explanation of the summary table metrics), chart (interpretation of the projection chart: slopes, when goal thresholds are reached, shortfall/surplus), "
                "scenarios (object with keys severe, conservative, baseline, optimistic, high; each value Markdown with: Background & Assumptions, Impact on the 3 Financial Goals incl. delay, Advantages & Disadvantages, Trade-off Analysis), "
                "guidance (objective narrative helping the client choose a scenario), recommendations (general financial recommendations: first analysis of results, then high-priority issues, then foundational orientation).",
    "whatif": "Return ONLY JSON with key: text (Markdown trade-off and risk explanation of the what-if / stress test results).",
    "goals": "Return ONLY JSON with keys: ranking (Markdown: for EACH goal explain its relation to income, the estimated completion percentage and fit), primary (Markdown: why the selected goal is the best fit, feasibility, preconditions, trade-offs, with the plan figures), "
             "process (Markdown: step-by-step process to achieve the selected goal). Remind the client they keep full authority to choose.",
    "secondary": "Return ONLY JSON with key: text (Markdown: why the secondary goal may be appropriate, required income or savings capacity, timeframe and preconditions, risks if future income or yields fall short; state it is optional reference, not a guarantee).",
}
OUT_KEYS = {"analysis": ["table", "chart", "scenarios", "guidance", "recommendations"], "whatif": ["text"],
            "goals": ["ranking", "primary", "process"], "secondary": ["text"]}


def configured():
    return bool(os.getenv("GEMINI_API_KEY"))


def gemini(contents, system=None, json_mode=False, timeout=50):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    body = {"contents": contents, "generationConfig": {"temperature": 0.3}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        r = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=timeout)
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except Exception:  # network, quota, bad key, safety block ...
        return None


def _compact(kind, data):
    """Trim big arrays so prompts stay small."""
    d = json.loads(json.dumps(data, default=str))
    if kind == "analysis":
        for s in d.get("scenarios", []):
            for k in ("assets_by_year", "net_worth_by_year"):
                s[k] = s[k][::max(1, len(s[k]) // 8)][:9] if k in s else s.get(k)
        d.pop("years", None)
    if kind in ("goals", "secondary"):
        d.pop("chart", None)
        for k in ("plan_baseline", "plan_assumed"):
            if d.get(k):
                d[k].pop("series", None)
        if d.get("secondary"):
            for k in ("plan", "plan_baseline"):
                d["secondary"].get(k, {}).pop("series", None)
        for r in d.get("ranking", []):
            r.pop("plan", None)
    return json.dumps(d)[:24000]


def explain(kind, data, fallback):
    """Return (content, source, ms). Falls back to rule-based text when the LLM is unavailable."""
    t0 = time.perf_counter()
    out, source = dict(fallback), "rules"
    if configured():
        prompt = f"{KEYS[kind]}\n\nCALCULATION OUTPUT (authoritative):\n{_compact(kind, data)}"
        txt = gemini([{"role": "user", "parts": [{"text": prompt}]}], EXPLAIN_SYSTEM, json_mode=True)
        if txt:
            try:
                parsed = json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip()).strip())
                if isinstance(parsed, dict):
                    got = False
                    for k in OUT_KEYS[kind]:
                        v = parsed.get(k)
                        if k == "scenarios" and isinstance(v, dict):
                            merged = dict(out.get("scenarios", {}))
                            merged.update({a: b for a, b in v.items() if isinstance(b, str) and b.strip()})
                            out[k], got = merged, True
                        elif isinstance(v, str) and v.strip():
                            out[k], got = v, True
                    source = "gemini" if got else "rules"
            except ValueError:
                pass
    return out, source, (time.perf_counter() - t0) * 1000


# ----------------------------------------------------------------- RAG / chat
def _tok(s):
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def build_kb(faq):
    docs = []
    for t in faq["topics"]:
        for q in t["questions"]:
            docs.append({"title": f"{t['topic']} — {q['q']}", "text": q["a"], "toks": _tok(q["q"] + " " + q["a"] + " " + t["topic"])})
    return docs


def retrieve(kb, query, k=4):
    qt = _tok(query)
    scored = sorted(((len(qt & d["toks"]) / (1 + len(d["toks"]) ** 0.3), d) for d in kb), key=lambda x: -x[0])
    return [d for s, d in scored[:k] if s > 0]


def chat(message, history, kb, session_ctx):
    hits = retrieve(kb, message)
    kb_txt = "\n".join(f"- {h['title']}: {h['text']}" for h in hits) or "(no matching documentation found)"
    ctx = (f"SESSION DATA (from Python engine):\n{session_ctx}\n\n" if session_ctx else "SESSION DATA: the user has not saved financial information yet.\n\n")
    contents = []
    for h in (history or [])[-8:]:
        role = "model" if h.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": str(h.get("text", ""))[:2000]}]})
    contents.append({"role": "user", "parts": [{"text": f"{ctx}RETRIEVED FINOVA DOCUMENTATION:\n{kb_txt}\n\nUSER QUESTION:\n{message[:2000]}"}]})
    txt = gemini(contents, CHATBOT_SYSTEM)
    if txt:
        return txt, "gemini"
    if hits:
        return ("The AI model is not available right now, but here is what the FINOVA documentation says:\n\n" +
                "\n\n".join(f"**{h['title']}**\n{h['text']}" for h in hits[:2]), "kb")
    return ("The AI model is not configured on this server, and I could not find a matching answer in the FINOVA documentation. "
            "Try the FAQ above or send a support request."), "none"
