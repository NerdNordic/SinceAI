import argparse
import json

from govagent import AUDIT_KICKOFF, AUDITOR_SYSTEM, DEMO_QUESTIONS, TRIAGE_SYSTEM, run_agent
from govagent import tools as T
from govagent.llm import config


def main():
    ap = argparse.ArgumentParser(
        description="Build Less, Build Better — governed analytics agent (Since AI 2026)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("audit", help="run the governance audit end-to-end")
    p_ask = sub.add_parser("ask", help="triage a business request through the decision ladder")
    p_ask.add_argument("question")
    sub.add_parser("tools", help="list available tools")
    p_call = sub.add_parser("call", help="call a single tool directly (debugging)")
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}", help="JSON object of tool arguments")
    sub.add_parser("demo", help="list canned demo questions")
    args = ap.parse_args()

    if args.cmd == "tools":
        for spec in T.TOOL_SPECS:
            f = spec["function"]
            print(f"{f['name']}: {f['description'].split('.')[0]}")
        return
    if args.cmd == "call":
        result = T.call_tool(args.tool, **json.loads(args.args))
        print(json.dumps(result, indent=2, default=str)[:6000])
        return
    if args.cmd == "demo":
        for q in DEMO_QUESTIONS:
            print(f"- {q}")
        return

    cfg = config()
    print(f"[provider={cfg['provider']} model={cfg['model']} "
          f"endpoint={'set' if cfg['configured'] else 'NOT SET'}]", file=__import__("sys").stderr)
    if args.cmd == "audit":
        result = run_agent(AUDITOR_SYSTEM, AUDIT_KICKOFF)
    else:
        result = run_agent(TRIAGE_SYSTEM, args.question)
    print(result["answer"])
    if result["trace"]:
        print("\n--- evidence trace ---")
        for t in result["trace"]:
            print(f"* {t['tool']} {json.dumps(t['args'], default=str)} -> {t['summary']}")


if __name__ == "__main__":
    main()
