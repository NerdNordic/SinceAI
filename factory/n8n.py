"""n8n webhook client — the frontend's only transport to the analytics backend.

The n8n workflows own: question -> chart specification (Gemini), fingerprint lookup
against the chart registry, canonical KPI computation in code (data from MongoDB
Atlas) and the receipt + raw CSV. Set N8N_PROVIDER=stub to run the whole UI offline
on canned demo flows (factory/stub.py implements the same contract).

Webhook contract
----------------
POST {N8N_BASE_URL}{N8N_BRIEFING_PATH}  body {"role": "<role_id>"}
  -> {"role": str, "as_of": str,
      "kpis": [{"id","name","value","unit","target","status" (ok|deviation),
                "freshness": {"last_refresh","state" (fresh|stale)}}],
      "deviations": [{"kpi_id","message","severity" (high|medium|low)}]}

POST {N8N_BASE_URL}{N8N_ASK_PATH}  body {"role","question","history": [str]}
  -> {"type": "clarify", "question": str,
      "suggestions": [{"kpi_id","label"}]}
  or  {"type": "reuse|extend|answer|build", "text": str,
      "matched_chart": {"id","title"} | null,
      "chart": {"spec": {"chart_type" (line|bar),"title","x","y"},
                "data": [{"<x>","value"}, ...]},
      "receipt": {"formula","source","source_rows","assumption_version","freshness"},
      "csv": str}
"""

import json
import os
import urllib.error
import urllib.request

from factory import stub

VERDICTS = ("reuse", "extend", "answer", "build")


def config():
    return {
        "provider": os.environ.get("N8N_PROVIDER", "stub").strip().lower(),
        "base_url": os.environ.get("N8N_BASE_URL", "http://localhost:5678").rstrip("/"),
        "briefing_path": os.environ.get("N8N_BRIEFING_PATH", "/webhook/briefing"),
        "ask_path": os.environ.get("N8N_ASK_PATH", "/webhook/ask"),
        "api_key": os.environ.get("N8N_API_KEY", ""),
    }


def get_briefing(role):
    cfg = config()
    if cfg["provider"] == "stub":
        return stub.get_briefing(role)
    return _validate_briefing(_post(cfg["base_url"] + cfg["briefing_path"], {"role": role}, cfg))


def ask(role, question, history=None):
    cfg = config()
    if cfg["provider"] == "stub":
        return stub.ask(role, question)
    payload = {"role": role, "question": question, "history": history or []}
    return _validate_ask(_post(cfg["base_url"] + cfg["ask_path"], payload, cfg))


def _post(url, payload, cfg, timeout=30):
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["X-N8N-API-KEY"] = cfg["api_key"]
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise RuntimeError(f"n8n webhook returned HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach n8n at {url} ({e.reason}). "
                           f"Set N8N_PROVIDER=stub for the offline demo.") from None
    except json.JSONDecodeError as e:
        raise RuntimeError(f"n8n returned invalid JSON: {e}") from None


def _require(doc, key, kind, ctx):
    if key not in doc or not isinstance(doc[key], kind) or doc[key] == "":
        raise ValueError(f"n8n response field '{ctx}' must be a non-empty {kind.__name__}")
    return doc[key]


def _validate_briefing(doc):
    if not isinstance(doc, dict):
        raise ValueError("n8n briefing response must be a JSON object")
    _require(doc, "role", str, "role")
    _require(doc, "as_of", str, "as_of")
    kpis = _require(doc, "kpis", list, "kpis")
    for i, kpi in enumerate(kpis):
        ctx = f"kpis[{i}]"
        for field in ("id", "name", "status"):
            _require(kpi, field, str, f"{ctx}.{field}")
        if "value" not in kpi or not isinstance(kpi["value"], (int, float)):
            raise ValueError(f"n8n response field '{ctx}.value' must be numeric")
        freshness = kpi.get("freshness")
        if not isinstance(freshness, dict) or freshness.get("state") not in ("fresh", "stale") \
                or not freshness.get("last_refresh"):
            raise ValueError(f"n8n response field '{ctx}.freshness' must be "
                             "{{'last_refresh': str, 'state': 'fresh'|'stale'}}")
    deviations = doc.get("deviations", [])
    if not isinstance(deviations, list):
        raise ValueError("n8n response field 'deviations' must be a list")
    for i, dev in enumerate(deviations):
        for field in ("kpi_id", "message", "severity"):
            _require(dev, field, str, f"deviations[{i}].{field}")
    return doc


def _validate_ask(doc):
    if not isinstance(doc, dict):
        raise ValueError("n8n ask response must be a JSON object")
    rtype = doc.get("type")
    if rtype == "clarify":
        _require(doc, "question", str, "question")
        suggestions = _require(doc, "suggestions", list, "suggestions")
        if not suggestions:
            raise ValueError("clarify response must carry at least one suggestion")
        for i, sug in enumerate(suggestions):
            _require(sug, "kpi_id", str, f"suggestions[{i}].kpi_id")
            _require(sug, "label", str, f"suggestions[{i}].label")
        return doc
    if rtype not in VERDICTS:
        raise ValueError(f"n8n ask response 'type' must be 'clarify' or one of {VERDICTS}, "
                         f"got {rtype!r}")
    _require(doc, "text", str, "text")
    if rtype in ("reuse", "extend"):
        matched = doc.get("matched_chart")
        if not isinstance(matched, dict) or not matched.get("id") or not matched.get("title"):
            raise ValueError(f"'{rtype}' response must reference matched_chart "
                             "{{'id','title'}} from the chart registry")
    chart = doc.get("chart")
    if not isinstance(chart, dict) or not isinstance(chart.get("data"), list) \
            or not chart["data"]:
        raise ValueError("non-clarify response must carry chart.data (non-empty list)")
    spec = chart.get("spec", {})
    if spec.get("chart_type") not in ("line", "bar"):
        raise ValueError("chart.spec.chart_type must be 'line' or 'bar'")
    receipt = doc.get("receipt")
    if not isinstance(receipt, dict):
        raise ValueError("non-clarify response must carry a receipt object")
    for field in ("formula", "source", "freshness"):
        _require(receipt, field, str, f"receipt.{field}")
    if not isinstance(doc.get("csv", ""), str):
        raise ValueError("response field 'csv' must be a string when present")
    return doc
