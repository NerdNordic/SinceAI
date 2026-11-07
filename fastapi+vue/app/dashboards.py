"""Role dashboards: certified charts as live, receipt-backed tiles.

A certified chart already carries its full specification in the registry, so a dashboard
is just an ordered list of fingerprints recomputed on request with the same governed
metrics as chat (the LLM never calculates). Composition is hybrid:

  - pinned:    certified charts the data steward has explicitly pinned to the role
  - automatic: certified charts the role itself has used, most used first

Only certified charts are ever rendered: retiring a chart removes it from every
dashboard because the status is filtered here, not stored in the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import config
from .db import get_db
from .metrics import compute
from .spec import ChartSpec

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _audit(event: str, **data: Any) -> None:
    get_db().audit_log.insert_one({"ts": datetime.now(timezone.utc), "event": event, **data})


def _pinned(db, role: str) -> list[str]:
    doc = db.dashboards.find_one({"_id": role}) or {}
    return [fp for fp in doc.get("charts", []) if isinstance(fp, str)]


def _last_use(chart: dict[str, Any]) -> datetime:
    for key in ("last_used_at", "created_at"):
        v = chart.get(key)
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return EPOCH


def _tile(chart: dict[str, Any], pinned: bool) -> dict[str, Any]:
    tile = {"fingerprint": chart["fingerprint"], "title": chart["title"], "kpi_ids": chart.get("kpi_ids", []),
            "owner": chart.get("owner"), "pinned": pinned}
    try:
        result = compute(ChartSpec.model_validate(chart["spec"]))
        tile.update(chart=result["chart"], rows=result["rows"], unit=result["unit"], receipt=result["receipt"])
    except Exception as exc:  # noqa: BLE001 - one broken tile must not break the dashboard
        tile["error"] = str(exc)[:200]
    return tile


def get_dashboard(role: str, tiles: bool = True) -> dict[str, Any]:
    """Rendered dashboard for a role. tiles=false returns only metadata (pinned list,
    kpi ids) for lightweight polls such as the steward registry view."""
    if role not in config.ROLES:
        raise ValueError(f"unknown role {role}")
    db = get_db()
    pinned = _pinned(db, role)
    charts = list(db.chart_registry.find(
        {"status": "certified", "$or": [{"fingerprint": {"$in": pinned}}, {"used_by_roles": role}]},
        {"embedding": 0, "embedding_text": 0, "_id": 0}))
    by_fp = {c["fingerprint"]: c for c in charts}
    pinned_charts = [by_fp[fp] for fp in dict.fromkeys(pinned) if fp in by_fp]
    pinned_set = set(pinned)
    auto = sorted((c for c in charts if c["fingerprint"] not in pinned_set),
                  key=lambda c: (c.get("use_count", 0), _last_use(c)), reverse=True)
    out: dict[str, Any] = {"role": role, "label": config.ROLES[role]["label"], "pinned": pinned,
                           "kpi_ids": sorted({k for c in charts for k in c.get("kpi_ids", [])})}
    if tiles:
        out["tiles"] = [_tile(c, c["fingerprint"] in pinned_set) for c in pinned_charts + auto]
    return out


def pin(role: str, fingerprint: str) -> dict[str, Any]:
    """Data steward action: add a certified chart to a role's dashboard (front of the list)."""
    if role not in config.ROLES:
        raise ValueError(f"unknown role {role}")
    db = get_db()
    chart = db.chart_registry.find_one({"fingerprint": fingerprint}, {"status": 1})
    if not chart:
        raise KeyError(fingerprint)
    if chart.get("status") != "certified":
        raise ValueError("only certified charts can be pinned to a dashboard")
    ts = datetime.now(timezone.utc)
    db.dashboards.update_one({"_id": role},
                             {"$addToSet": {"charts": fingerprint}, "$set": {"updated_at": ts},
                              "$setOnInsert": {"created_at": ts, "label": config.ROLES[role]["label"]}},
                             upsert=True)
    _audit("chart_pinned", role=role, fingerprint=fingerprint)
    return {"role": role, "fingerprint": fingerprint, "pinned": _pinned(db, role)}


def unpin(role: str, fingerprint: str) -> dict[str, Any]:
    if role not in config.ROLES:
        raise ValueError(f"unknown role {role}")
    db = get_db()
    db.dashboards.update_one({"_id": role},
                             {"$pull": {"charts": fingerprint}, "$set": {"updated_at": datetime.now(timezone.utc)}})
    _audit("chart_unpinned", role=role, fingerprint=fingerprint)
    return {"role": role, "fingerprint": fingerprint, "pinned": _pinned(db, role)}
