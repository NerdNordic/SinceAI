"""Read-only views of n8n-owned records; legacy documents are never migrated here."""

from __future__ import annotations

from .db import get_db

ROUTES = ("CLARIFY", "REUSE", "EXTEND", "ANSWER", "BUILD")


def meter(role: str | None = None) -> dict:
    match = {"role": role} if role and role != "data_steward" else {}
    groups = get_db().chart_requests.aggregate([
        {"$match": match},
        {"$group": {"_id": {"route": "$route", "role": "$role"}, "count": {"$sum": 1}}},
    ])
    counts = dict.fromkeys(ROUTES, 0)
    by_role = {}
    total = 0
    for group in groups:
        count = group["count"]
        total += count
        route = group["_id"].get("route")
        if route not in counts:
            continue
        counts[route] += count
        key = group["_id"].get("role", "unknown")
        by_role.setdefault(key, dict.fromkeys(ROUTES, 0))[route] += count
    # BUILD may mean a formula request, not a newly registered chart.
    new_query = {"chart_id": {"$type": "string"}}
    if match:
        new_query["role"] = role
    new_charts = get_db().chart_registry.count_documents(new_query)
    avoided = sum(counts[r] for r in ("REUSE", "EXTEND", "ANSWER"))
    answered = sum(counts[r] for r in ("REUSE", "EXTEND", "ANSWER", "BUILD"))
    return {"requests": total, "new_charts": new_charts,
            "handled_without_new_chart": avoided,
            "reuse_rate": round(avoided / answered, 3) if answered else None,
            "by_decision": counts, "by_role": by_role}


def registry() -> list[dict]:
    fields = {name: 1 for name in (
        "chart_id", "fingerprint", "title", "owner", "status", "usage_count",
        "used_by_roles", "created_at", "updated_at", "last_used_at", "role", "kpi_ids",
    )}
    fields["_id"] = 0
    return list(get_db().chart_registry.find(
        {"chart_id": {"$type": "string"}}, fields).sort("created_at", -1).limit(200))


def approvals() -> list[dict]:
    fields = {name: 1 for name in (
        "approval_id", "chart_id", "title", "action", "kind", "status", "decided_by", "created_at",
    )}
    fields["_id"] = 0
    return list(get_db().approvals.find(
        {"approval_id": {"$type": "string"}}, fields).sort("created_at", -1).limit(200))


def audit() -> list[dict]:
    fields = {name: 1 for name in (
        "ts", "event", "chart_id", "approval_id", "request_id", "title", "actor",
    )}
    fields["_id"] = 0
    return list(get_db().audit_log.find({}, fields).sort("ts", -1).limit(100))
