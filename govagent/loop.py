import json

from .llm import chat
from .tools import TOOL_SPECS, dump_tool_result, call_tool

MAX_ITERATIONS = 12


def run_agent(system_prompt, user_message, history=None):
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        for h in history:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})
    trace = []
    for _ in range(MAX_ITERATIONS):
        msg = chat(messages, TOOL_SPECS)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return {"answer": msg.get("content") or "(empty response)",
                    "trace": trace, "messages": messages}
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    args = {"query": args}
            except json.JSONDecodeError:
                args = {}
            try:
                result = call_tool(name, **args)
                summary = result.get("summary", "") if isinstance(result, dict) else str(result)[:200]
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}", "tool": name}
                summary = f"ERROR: {e}"
            trace.append({"tool": name, "args": args, "summary": summary})
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": dump_tool_result(result)})
    summaries = "\n".join(f"- {t['tool']}: {t['summary']}" for t in trace)
    return {"answer": ("Reached the tool-call limit before a final answer. Evidence collected so far:\n"
                       + summaries),
            "trace": trace, "messages": messages}
