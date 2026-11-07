"""Decision engine: reuse before build.

question -> spec (Gemini) -> fingerprint -> REUSE / EXTEND / ANSWER / BUILD / CLARIFY -> governed computation.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config, metrics
from .db import get_db
from .spec import ChartSpec, generate_spec, write_answer

DECISIONS = ["REUSE", "EXTEND", "ANSWER", "BUILD", "CLARIFY"]
ACTIVE = ["active", "certified"]


def now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(spec: ChartSpec) -> str:
    """Identity of a chart: metric + dimensions + WHICH filters are used, not their values.
    'OTIF by month in Finland' and 'OTIF by month in Sweden' are the same chart with another filter."""
    keys = sorted(k for k, v in spec.filters.model_dump().items() if v)
    payload = {"metric": spec.metric, "dimensions": sorted(spec.dimensions), "filter_keys": keys}
    return "cf-" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _audit(event: str, **data: Any) -> None:
    get_db().audit_log.insert_one({"ts": now(), "event": event, **data})


def _similar_charts(spec: ChartSpec, fp: str, question: str) -> list[dict[str, Any]]:
    try:
        import vector_store as vs

        hits = vs.search_charts(get_db(), f"{spec.title}. {question}", filter={"status": {"$in": ACTIVE}}, limit=4)
        return [{"fingerprint": h["fingerprint"], "title": h["title"], "score": round(h["score"], 3)}
                for h in hits if h["fingerprint"] != fp and h["score"] >= 0.80][:3]
    except Exception:  # noqa: BLE001 - optional
        return []


def _related_reports(spec: ChartSpec) -> list[dict[str, Any]]:
    """Existing Bayer reports that measure the same canonical metric (from the catalogue)."""
    try:
        import vector_store as vs

        hits = vs.search_assets(get_db(), f"{spec.metric}. {spec.title}", limit=6)
        return [{"asset_id": h["_id"], "name": h["asset_name"], "platform": h["platform"],
                 "endorsement": h["endorsement"], "lifecycle_status": h["lifecycle_status"]}
                for h in hits if spec.metric in h.get("canonical_metrics", [])][:3]
    except Exception:  # noqa: BLE001 - optional
        return []


def _register(spec: ChartSpec, fp: str, role: str, question: str) -> dict[str, Any]:
    m = metrics.METRICS[spec.metric]
    chart = {
        "fingerprint": fp, "title": spec.title,
        "description": f"{spec.metric} by {', '.join(spec.dimensions) or 'total'}. Asked: {question}",
        "role": role, "plant": (spec.filters.plants or [None])[0], "kpi_ids": [m.kpi_id],
        "spec": spec.model_dump(), "filters": spec.filters.model_dump(),
        "owner": config.ROLES[role]["label"], "status": "active",
        "review_by": (now() + timedelta(days=config.REVIEW_DAYS)).date().isoformat(),
        "used_by_roles": [role], "last_used_at": now(),
    }
    try:
        import vector_store as vs

        vs.register_chart(get_db(), chart)
    except Exception as exc:  # noqa: BLE001 - registry must work without embeddings
        get_db().chart_registry.update_one(
            {"fingerprint": fp},
            {"$set": {**chart, "updated_at": now(), "embedding_error": str(exc)[:200]},
             "$setOnInsert": {"created_at": now(), "use_count": 0}},
            upsert=True)
    _audit("chart_registered", fingerprint=fp, role=role, title=spec.title)
    return get_db().chart_registry.find_one({"fingerprint": fp}, {"embedding": 0})


def _save_turn(session_id: str, role: str, turn: dict[str, Any]) -> None:
    turn["ts"] = now()
    get_db().conversations.update_one(
        {"_id": session_id},
        {"$push": {"turns": turn}, "$set": {"role": role, "updated_at": now()}, "$setOnInsert": {"created_at": now()}},
        upsert=True)


def fallback_answer(spec: ChartSpec, result: dict[str, Any]) -> str:
    """Deterministic one-liner when Gemini is not available. Uses only computed values."""
    rows = result["rows"]
    unit = result["unit"]
    if not rows:
        return "Valinnoilla ei löytynyt dataa."
    if spec.metric == "Replenishment Reorder-By Date":
        r = rows[0]
        return (f"{len(rows)} tuote–markkina-paria. Kiireellisin: {r['tuote']} → {r['markkina']}, "
                f"tilaa viimeistään {r['tilaa_viimeistaan']} ({r['tila']}).")
    chart = result["chart"]
    if "month" in spec.dimensions and chart["datasets"] and len(chart["labels"]) >= 2:
        d = chart["datasets"][0]
        vals = [(m, v) for m, v in zip(chart["labels"], d["data"]) if v is not None]
        if len(vals) >= 2:
            (pm, pv), (lm, lv) = vals[-2], vals[-1]
            trend = "noussut" if lv > pv else "laskenut" if lv < pv else "pysynyt ennallaan"
            return f"{d['label']}: {lv:g} {unit} ({lm}), {trend} edellisestä ({pv:g} {unit}, {pm})."
    top = rows[0]
    label = " · ".join(str(v) for k, v in top.items() if k != "arvo") or spec.metric
    return f"{spec.title}: {label} {top['arvo']:g} {unit}." if top.get("arvo") is not None else spec.title


def ask(question: str, role: str, session_id: str | None = None) -> dict[str, Any]:
    db = get_db()
    session_id = session_id or uuid.uuid4().hex[:12]
    conv = db.conversations.find_one({"_id": session_id}) or {}
    history = conv.get("turns", [])
    spec, meta = generate_spec(question, role, history)
    base = {"question": question, "role": role, "session_id": session_id, "spec": spec.model_dump(),
            "llm_cached": meta["cached"], "kpi_hints": meta.get("hints", [])}

    if spec.mode == "chat":
        answer = spec.reply or ("Voin näyttää tehtaan luvut ja kaaviot hallituilla määritelmillä: "
                                + ", ".join(metrics.METRICS) + ". Kysy esimerkiksi, mitä pitää tilata tällä viikolla.")
        _save_turn(session_id, role, {"q": question, "decision": "CHAT", "answer": answer})
        return {**base, "decision": "CHAT", "answer": answer}

    if not spec.understood or spec.metric == "UNSUPPORTED":
        msg = spec.clarification_question or (
            "En löytänyt tähän hallittua mittaria. Voin näyttää: " + ", ".join(k for k in metrics.METRICS) + ".")
        db.request_log.insert_one({"ts": now(), "role": role, "question": question, "decision": "CLARIFY"})
        _save_turn(session_id, role, {"q": question, "decision": "CLARIFY", "answer": msg})
        return {**base, "decision": "CLARIFY", "rule": "RULE-002", "reason": msg, "answer": msg}

    fp = fingerprint(spec)
    existing = db.chart_registry.find_one({"fingerprint": fp, "status": {"$in": ACTIVE}}, {"embedding": 0})
    result = metrics.compute(spec)

    if existing:
        same = existing.get("filters") == spec.filters.model_dump()
        decision = "REUSE" if same else "EXTEND"
        db.chart_registry.update_one({"fingerprint": fp}, {"$inc": {"use_count": 1}, "$set": {"last_used_at": now()},
                                                           "$addToSet": {"used_by_roles": role}})
        created = existing.get("created_at")
        if isinstance(created, datetime):
            from zoneinfo import ZoneInfo
            created = (created if created.tzinfo else created.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo("Europe/Helsinki"))
        reason = (f"Sama kaavio on jo olemassa: \"{existing['title']}\" (omistaja {existing['owner']}"
                  f"{', luotu ' + created.strftime('%d.%m. klo %H.%M') if isinstance(created, datetime) else ''}). "
                  + ("Näytetään päivitetyllä datalla." if same else "Näytetään sama kaavio uusilla suodattimilla, uutta kaaviota ei luotu."))
        title, chart_status, rule = existing["title"], existing["status"], "RULE-001"
    elif spec.intent == "one_off":
        decision, rule, chart_status, title = "ANSWER", "RULE-001", None, spec.title
        reason = "Kertaluonteinen kysymys: luku lasketaan hallitulla määritelmällä, mutta kaaviota ei tallenneta rekisteriin."
    else:
        reg = _register(spec, fp, role, question)
        decision, rule, chart_status, title = "BUILD", "RULE-002, RULE-003", reg["status"], spec.title
        reason = (f"Vastaavaa kaaviota ei löytynyt rekisteristä. Uusi kaavio rekisteröitiin: omistaja "
                  f"{reg['owner']}, kanoninen KPI {metrics.METRICS[spec.metric].kpi_id}, tarkistus {reg['review_by']}.")

    result_id = uuid.uuid4().hex[:12]
    db.results.insert_one({"_id": result_id, "fingerprint": fp, "metric": spec.metric, "source": result["source"],
                           "created_at": now()})
    db.request_log.insert_one({"ts": now(), "role": role, "question": question, "decision": decision,
                               "fingerprint": fp, "metric": spec.metric})

    warnings = result["receipt"].get("warnings", [])
    payload = {"metric": spec.metric, "unit": result["unit"], "decision": decision, "decision_reason": reason,
               "rows": result["rows"][:15], "warnings": warnings}
    answer = write_answer(question, payload) or fallback_answer(spec, result)
    kpi = result["receipt"].get("kpi", {})
    src = result["receipt"].get("source", {})
    receipt_brief = (f"KPI {kpi.get('id')} {kpi.get('name')} ({kpi.get('definition_status')}); "
                     f"{result['receipt'].get('definition', '')} Source {src.get('sheet') or src.get('collection')}, "
                     f"{src.get('rows_used')} rows. Warnings: {'; '.join(warnings) or 'none'}")
    _save_turn(session_id, role, {"q": question, "decision": decision, "spec": spec.model_dump(), "title": title,
                                  "answer": answer, "receipt_brief": receipt_brief})
    return {
        **base, "decision": decision, "rule": rule, "reason": reason, "answer": answer, "fingerprint": fp, "title": title,
        "chart_status": chart_status, "result_id": result_id, "unit": result["unit"], "chart": result["chart"],
        "rows": result["rows"], "receipt": result["receipt"],
        "similar_charts": _similar_charts(spec, fp, question), "related_reports": _related_reports(spec),
    }


# --------------------------------------------------------------------------- data steward

def meter() -> dict[str, Any]:
    logs = list(get_db().request_log.find({}, {"_id": 0, "decision": 1, "role": 1}))
    counts = {d: sum(1 for l in logs if l["decision"] == d) for d in DECISIONS}
    by_role: dict[str, dict[str, int]] = {}
    for l in logs:
        by_role.setdefault(l["role"], {d: 0 for d in DECISIONS})[l["decision"]] += 1
    answered = sum(counts[d] for d in ("REUSE", "EXTEND", "ANSWER", "BUILD"))
    return {"requests": len(logs), "new_charts": counts["BUILD"],
            "handled_without_new_chart": counts["REUSE"] + counts["EXTEND"] + counts["ANSWER"],
            "reuse_rate": round((counts["REUSE"] + counts["EXTEND"] + counts["ANSWER"]) / answered, 3) if answered else None,
            "by_decision": counts, "by_role": by_role}


def registry() -> list[dict[str, Any]]:
    idle = timedelta(minutes=int(__import__("os").environ.get("RETIRE_IDLE_MINUTES", str(30 * 24 * 60))))
    out = []
    for c in get_db().chart_registry.find({}, {"embedding": 0, "embedding_text": 0, "_id": 0}).sort("created_at", -1):
        last = c.get("last_used_at") or c.get("created_at")
        if isinstance(last, datetime) and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        roles = c.get("used_by_roles", [])
        c["suggestion"] = None
        if c.get("status") == "active" and (len(roles) >= 2 or c.get("use_count", 0) >= 3):
            c["suggestion"] = "certify"
        elif c.get("status") in ACTIVE and isinstance(last, datetime) and now() - last > idle:
            c["suggestion"] = "retire"
        out.append(c)
    return out


def propose(fp: str, action: str) -> dict[str, Any]:
    if action not in ("retire", "certify"):
        raise ValueError("action must be retire or certify")
    db = get_db()
    chart = db.chart_registry.find_one({"fingerprint": fp}, {"embedding": 0, "_id": 0})
    if not chart:
        raise KeyError(fp)
    pid = uuid.uuid4().hex[:10]
    evidence = {"use_count": chart.get("use_count", 0), "used_by_roles": chart.get("used_by_roles", []),
                "last_used_at": str(chart.get("last_used_at")), "owner": chart.get("owner"), "kpi_ids": chart.get("kpi_ids")}
    proposal = {"_id": pid, "fingerprint": fp, "title": chart["title"], "action": action, "status": "pending",
                "evidence": evidence, "created_at": now()}
    db.proposals.insert_one(proposal)
    _audit("proposal_created", proposal_id=pid, fingerprint=fp, action=action)
    sent = False
    if config.N8N_WEBHOOK_URL:
        payload = {"proposal_id": pid, "fingerprint": fp, "title": chart["title"], "action": action, "evidence": evidence,
                   "callback_url": f"{config.PUBLIC_BASE_URL}/api/registry/decision"}
        req = urllib.request.Request(config.N8N_WEBHOOK_URL, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            sent = True
        except Exception as exc:  # noqa: BLE001
            _audit("n8n_webhook_failed", proposal_id=pid, error=str(exc)[:200])
    return {"proposal_id": pid, "sent_to_n8n": sent, **{k: v for k, v in proposal.items() if k != "_id"}}


def decide_proposal(proposal_id: str, approved: bool, approver: str) -> dict[str, Any]:
    db = get_db()
    p = db.proposals.find_one({"_id": proposal_id})
    if not p:
        raise KeyError(proposal_id)
    if p["status"] != "pending":
        return {"proposal_id": proposal_id, "status": p["status"], "note": "already decided"}
    status = "approved" if approved else "rejected"
    db.proposals.update_one({"_id": proposal_id}, {"$set": {"status": status, "decided_by": approver, "decided_at": now()}})
    if approved:
        new = "retired" if p["action"] == "retire" else "certified"
        db.chart_registry.update_one({"fingerprint": p["fingerprint"]}, {"$set": {"status": new, "status_changed_at": now()}})
    _audit("proposal_decided", proposal_id=proposal_id, fingerprint=p["fingerprint"], action=p["action"],
           approved=approved, approver=approver)
    return {"proposal_id": proposal_id, "status": status, "action": p["action"], "fingerprint": p["fingerprint"]}


def audit(limit: int = 50) -> list[dict[str, Any]]:
    return list(get_db().audit_log.find({}, {"_id": 0}).sort("ts", -1).limit(limit))
