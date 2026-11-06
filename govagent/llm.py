import json
import os
from pathlib import Path

_STUB_KICKOFF = {
    "id": "stub-1", "type": "function",
    "function": {"name": "find_kpi_conflicts", "arguments": "{}"},
}


def load_env():
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def provider():
    load_env()
    return os.environ.get("GOVAGENT_PROVIDER", "openai").lower()


def config():
    load_env()
    return {
        "provider": os.environ.get("GOVAGENT_PROVIDER", "openai"),
        "base_url": os.environ.get("GOVAGENT_BASE_URL", ""),
        "model": os.environ.get("GOVAGENT_MODEL", "glm-5.3"),
        "configured": bool(os.environ.get("GOVAGENT_BASE_URL") or os.environ.get("GOVAGENT_API_KEY")),
    }


def _stub_chat(messages, tools):
    last = messages[-1]
    if last.get("role") == "user":
        return {"role": "assistant", "content": None, "tool_calls": [dict(_STUB_KICKOFF)]}
    if last.get("role") == "tool":
        summary = ""
        try:
            payload = json.loads(last.get("content", "{}"))
            summary = payload.get("summary", "")
        except Exception:
            summary = last.get("content", "")[:200]
        content = (
            "OFFLINE STUB RESPONSE — no real LLM endpoint is configured "
            "(set GOVAGENT_BASE_URL / GOVAGENT_API_KEY / GOVAGENT_MODEL for real answers).\n\n"
            f"One tool call was exercised and returned: {summary}\n\n"
            "This stub exists to test the agent loop, tool layer and UI without network access."
        )
        return {"role": "assistant", "content": content, "tool_calls": None}
    return {"role": "assistant",
            "content": "OFFLINE STUB — send a message to trigger a stub tool call.",
            "tool_calls": None}


def chat(messages, tools=None):
    if provider() == "stub":
        return _stub_chat(messages, tools)
    from openai import OpenAI
    cfg = config()
    client = OpenAI(base_url=cfg["base_url"] or None, api_key=os.environ.get("GOVAGENT_API_KEY", "dummy"))
    resp = client.chat.completions.create(
        model=cfg["model"], messages=messages, tools=tools or None, temperature=0.2)
    m = resp.choices[0].message
    tool_calls = None
    if m.tool_calls:
        tool_calls = [{"id": tc.id, "type": "function",
                       "function": {"name": tc.function.name,
                                    "arguments": tc.function.arguments or "{}"}}
                      for tc in m.tool_calls]
    return {"role": "assistant", "content": m.content, "tool_calls": tool_calls}
