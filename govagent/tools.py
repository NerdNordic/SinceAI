import json
import os
import re
import sqlite3
import threading
from pathlib import Path

_PKG_PARENT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _PKG_PARENT / "Bayer_SinceAI2026 _1_" / "Bayer_SinceAI2026" / "bayer_sinceai.db"

_local = threading.local()
_usage_cache = None

KPI_GROUNDING = {
    "Net Sales": "Product_Market_Monthly.net_sales_m_eur_syn",
    "Net Sales Growth": "derived: Product_Market_Monthly.net_sales_m_eur_syn MoM",
    "Units Shipped": "Product_Market_Monthly.units_shipped_syn",
    "Forecast Variance": "Product_Market_Monthly.forecast_variance_pct",
    "Demand Forecast Accuracy": "Supply_Operations.forecast_accuracy_pct_syn",
    "Demand Forecast Bias": "derived: Product_Market_Monthly forecast vs net sales",
    "Inventory Coverage": "Product_Market_Monthly.inventory_weeks_syn / Supply_Operations.inventory_weeks_syn",
    "On-Time In-Full": "Product_Market_Monthly.otif_pct_syn / Supply_Operations.otif_pct_syn",
    "Market Access Coverage": "Market_Access.coverage_pct_syn / Product_Market_Monthly.market_access_coverage_pct_syn",
    "Reimbursement Status Coverage": "Market_Access.reimbursement_status",
    "Launch Adoption Index": "derived: Launch_Milestones.first_commercial_sale + Product_Market_Monthly.net_sales",
}

INTENTS = [
    ("replace/migrate", ("replace", "migrat", "migration")),
    ("consolidate", ("one executive view", "combin", "consolidat", "single")),
    ("new build", ("create", "new", "build")),
]


def classify_intent(text):
    t = text.lower()
    for label, kws in INTENTS:
        if any(k in t for k in kws):
            return label
    return "other"


def db():
    con = getattr(_local, "con", None)
    if con is None:
        path = Path(os.environ.get("GOVAGENT_DB") or _DEFAULT_DB).resolve()
        if not path.exists():
            raise RuntimeError(f"SQLite database not found at {path} (set GOVAGENT_DB to override)")
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        _local.con = con
    return con


def rows(sql, *params):
    return db().execute(sql, params).fetchall()


def one(sql, *params):
    r = db().execute(sql, params).fetchone()
    return r[0] if r is not None and len(r) == 1 else r


def _cap(lst, n=10):
    if len(lst) <= n:
        return lst, 0
    return lst[:n], len(lst) - n


def _clip(v, width=120):
    if isinstance(v, str) and len(v) > width:
        return v[: width - 1] + "…"
    return v


def _usage():
    global _usage_cache
    if _usage_cache is None:
        base = rows(
            "SELECT asset_id, SUM(views), AVG(unique_users), SUM(exports), AVG(avg_load_ms), SUM(query_errors) "
            "FROM Asset_Usage GROUP BY asset_id")
        months = [r[0] for r in rows("SELECT DISTINCT month FROM Asset_Usage ORDER BY month")]
        cutoff = months[-3]
        momentum = {r[0]: (r[1], r[2]) for r in rows(
            "SELECT asset_id, SUM(CASE WHEN month >= ? THEN views ELSE 0 END), "
            "SUM(CASE WHEN month < ? THEN views ELSE 0 END) FROM Asset_Usage GROUP BY asset_id",
            cutoff, cutoff)}
        views_sorted = sorted(r[1] or 0 for r in base)
        p10 = views_sorted[len(views_sorted) // 10]
        p90 = views_sorted[-(len(views_sorted) // 10)]
        cache = {}
        for aid, views, users, exports, load, errors in base:
            rec, prior = momentum.get(aid, (0, 0))
            ratio = round(rec / (prior / 7 * 3), 2) if prior else None
            decile = "bottom" if (views or 0) <= p10 else ("top" if (views or 0) >= p90 else "middle")
            cache[aid] = {
                "views": views or 0, "avg_users": round(users or 0, 1), "exports": exports or 0,
                "avg_load_ms": round(load or 0), "errors": errors or 0,
                "decile": decile, "recent_vs_prior_ratio": ratio,
            }
        _usage_cache = {"assets": cache, "p10_views": p10, "p90_views": p90, "months": months}
    return _usage_cache


def tool_estate_overview():
    counts = {
        "assets": one("SELECT COUNT(*) FROM Analytics_Assets"),
        "semantic_models": one("SELECT COUNT(*) FROM Semantic_Models"),
        "kpis": one("SELECT COUNT(*) FROM KPI_Catalog"),
        "lineage_edges": one("SELECT COUNT(*) FROM Lineage_Edges"),
        "governance_signals": one("SELECT COUNT(*) FROM Governance_Signals"),
        "migration_items": one("SELECT COUNT(*) FROM Migration_Backlog"),
        "business_requests": one("SELECT COUNT(*) FROM Business_Requests"),
    }
    platform_life = rows("SELECT platform, lifecycle_status, COUNT(*) FROM Analytics_Assets GROUP BY 1, 2 ORDER BY 1, 3 DESC")
    summary = (f"BI estate: {counts['assets']} assets (Power BI + Tableau), {counts['semantic_models']} semantic "
               f"models, {counts['kpis']} KPI definitions, {counts['governance_signals']} governance signals, "
               f"{counts['migration_items']} migration backlog items")
    data = {"counts": counts,
            "platform_x_lifecycle": [{"platform": p, "lifecycle": l, "assets": n} for p, l, n in platform_life]}
    return {"tool": "estate_overview", "summary": summary, "evidence": [summary], "data": data}


def tool_find_kpi_conflicts(canonical_metric=None):
    if canonical_metric:
        conflicts = rows("SELECT canonical_metric, variant_count, variants, canonical_variants, approved_variants "
                         "FROM v_kpi_conflicts WHERE UPPER(canonical_metric) = UPPER(?) ORDER BY variant_count DESC",
                         canonical_metric)
    else:
        conflicts = rows("SELECT canonical_metric, variant_count, variants, canonical_variants, approved_variants "
                         "FROM v_kpi_conflicts ORDER BY variant_count DESC, canonical_metric")
    unapproved_assets = dict(rows(
        "SELECT k.canonical_metric, COUNT(DISTINCT m.asset_id) FROM Asset_KPI_Map m "
        "JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id WHERE k.approval_status != 'approved' GROUP BY 1"))
    mixing = rows(
        "SELECT m.asset_id, a.asset_name, k.canonical_metric, COUNT(DISTINCT m.kpi_id) "
        "FROM Asset_KPI_Map m JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id "
        "JOIN Analytics_Assets a ON a.asset_id = m.asset_id "
        "GROUP BY m.asset_id, k.canonical_metric HAVING COUNT(DISTINCT m.kpi_id) > 1 ORDER BY 4 DESC")
    if canonical_metric and not conflicts:
        known = [r[0] for r in rows("SELECT DISTINCT canonical_metric FROM KPI_Catalog ORDER BY 1")]
        return {"tool": "find_kpi_conflicts", "summary": f"No KPI named '{canonical_metric}'",
                "evidence": [], "data": {"known_canonical_metrics": known}}
    total_unappr = sum(unapproved_assets.values())
    summary = (f"{len(conflicts)} canonical metrics have conflicting KPI variants; "
               f"{total_unappr} asset-references point at unapproved KPI variants; "
               f"{len(mixing)} asset/metric pairs mix conflicting definitions in one asset")
    evidence = [f"{c[0]}: {c[1]} variants ({c[2]})" for c in conflicts[:12]]
    data = {"conflicts": [{"canonical_metric": c[0], "variant_count": c[1], "variants": c[2],
                           "canonical_variants": c[3], "approved_variants": c[4],
                           "assets_using_unapproved": unapproved_assets.get(c[0], 0)} for c in conflicts],
            "assets_mixing_variants": [{"asset": m[0], "name": m[1], "canonical_metric": m[2],
                                        "variants_mixed": m[3]} for m in mixing[:15]],
            "assets_mixing_count": len(mixing)}
    return {"tool": "find_kpi_conflicts", "summary": summary, "evidence": evidence, "data": data}


def tool_find_assets_using_kpi(name):
    kpis = rows(
        "SELECT kpi_id, kpi_name, canonical_metric, domain, definition_status, approval_status, "
        "business_criticality, default_frequency FROM KPI_Catalog "
        "WHERE UPPER(canonical_metric) = UPPER(?) OR UPPER(kpi_id) = UPPER(?) "
        "OR UPPER(kpi_name) = UPPER(?)", name, name, name)
    if not kpis:
        kpis = rows(
            "SELECT kpi_id, kpi_name, canonical_metric, domain, definition_status, approval_status, "
            "business_criticality, default_frequency FROM KPI_Catalog "
            "WHERE UPPER(kpi_name) LIKE '%' || UPPER(?) || '%' "
            "OR UPPER(canonical_metric) LIKE '%' || UPPER(?) || '%'", name, name)
    if not kpis:
        known = [r[0] for r in rows("SELECT DISTINCT canonical_metric FROM KPI_Catalog ORDER BY 1")]
        return {"tool": "find_assets_using_kpi", "summary": f"No KPI matches '{name}'",
                "evidence": [], "data": {"known_canonical_metrics": known}}
    out = []
    evidence = []
    for kpi_id, kpi_name, canon, domain, dstat, astat, crit, freq in kpis:
        total = one("SELECT COUNT(*) FROM Asset_KPI_Map WHERE kpi_id = ?", kpi_id)
        assets = rows("SELECT a.asset_id, a.asset_name, a.platform, a.lifecycle_status, a.endorsement "
                      "FROM Asset_KPI_Map m JOIN Analytics_Assets a ON a.asset_id = m.asset_id "
                      "WHERE m.kpi_id = ? ORDER BY a.estimated_audience DESC", kpi_id)
        capped, more = _cap(assets)
        out.append({"kpi_id": kpi_id, "kpi_name": kpi_name, "canonical_metric": canon, "domain": domain,
                    "definition_status": dstat, "approval_status": astat, "business_criticality": crit,
                    "default_frequency": freq, "assets_using": total,
                    "sample_assets": [{"asset": a, "name": b, "platform": c, "lifecycle": d, "endorsement": e}
                                      for a, b, c, d, e in capped], "sample_truncated": more})
        flag = "" if astat == "approved" else "  <-- UNAPPROVED VARIANT"
        evidence.append(f"{kpi_id} {kpi_name} [{canon}] {dstat}/{astat}, used by {total} assets{flag}")
    canon_names = sorted({k[2] for k in kpis})
    mixing = rows(
        f"SELECT m.asset_id, a.asset_name, COUNT(DISTINCT m.kpi_id) FROM Asset_KPI_Map m "
        f"JOIN KPI_Catalog k ON k.kpi_id = m.kpi_id JOIN Analytics_Assets a ON a.asset_id = m.asset_id "
        f"WHERE k.canonical_metric IN ({','.join('?' * len(canon_names))}) "
        f"GROUP BY m.asset_id HAVING COUNT(DISTINCT m.kpi_id) > 1", *canon_names)
    unapproved = [k for k in out if k["approval_status"] != "approved"]
    summary = (f"Canonical metric(s) {', '.join(canon_names)}: {len(kpis)} KPI variants, "
               f"{len(unapproved)} unapproved; {sum(k['assets_using'] for k in unapproved)} asset-uses "
               f"of unapproved variants; {len(mixing)} assets mix multiple variants")
    return {"tool": "find_assets_using_kpi", "summary": summary, "evidence": evidence,
            "data": {"kpis": out, "assets_mixing_variants": len(mixing),
                     "mixing_sample": [{"asset": m, "name": n, "variants": c} for m, n, c in mixing[:10]]}}


def tool_find_duplicate_assets():
    scope_groups = rows("SELECT product_scope, market_scope, model_id, COUNT(*) FROM Analytics_Assets "
                        "GROUP BY 1, 2, 3 HAVING COUNT(*) > 1 ORDER BY 4 DESC")
    cross_platform = rows("SELECT product_scope, market_scope, COUNT(DISTINCT platform) FROM Analytics_Assets "
                          "GROUP BY 1, 2 HAVING COUNT(DISTINCT platform) > 1")
    dup_names = rows("SELECT asset_name, COUNT(*), GROUP_CONCAT(platform), COUNT(DISTINCT platform) "
                     "FROM Analytics_Assets GROUP BY 1 HAVING COUNT(*) > 1 ORDER BY 2 DESC")
    n_dup_assets = one("SELECT COUNT(*) FROM Analytics_Assets WHERE asset_name IN "
                       "(SELECT asset_name FROM Analytics_Assets GROUP BY 1 HAVING COUNT(*) > 1)")
    summary = (f"Sprawl: {len(scope_groups)} identical-scope groups (same product x market x model), "
               f"{len(cross_platform)} product-market scopes served on both platforms, "
               f"{n_dup_assets} assets share {len(dup_names)} duplicate names")
    evidence = [f"scope group: {p} x {m} on {mod} -> {n} assets" for p, m, mod, n in scope_groups[:6]]
    evidence += [f"cross-platform: {p} {m}" for p, m, _ in cross_platform[:6]]
    evidence += [f"duplicate name: '{n}' x{c} ({pl})" for n, c, pl, _ in dup_names[:6]]
    data = {"identical_scope_groups": [{"product": p, "market": m, "model": mod, "assets": n}
                                       for p, m, mod, n in scope_groups],
            "cross_platform_scopes": [{"product": p, "market": m, "platforms": n}
                                      for p, m, n in cross_platform],
            "duplicate_names": [{"asset_name": n, "count": c, "platforms": pl, "distinct_platforms": dp}
                                 for n, c, pl, dp in dup_names],
            "assets_with_duplicate_names": n_dup_assets}
    return {"tool": "find_duplicate_assets", "summary": summary, "evidence": evidence, "data": data}


def tool_asset_report(asset_id):
    r = one("SELECT a.asset_id, a.asset_name, a.asset_type, a.platform, a.lifecycle_status, a.endorsement, "
            "a.estimated_audience, a.product_scope, a.market_scope, a.created_date, a.last_modified, "
            "a.classification, a.delivery_model, w.workspace_name, o.owner_name, m.model_name, "
            "m.refresh_status, m.endorsement "
            "FROM Analytics_Assets a LEFT JOIN Workspaces w ON w.workspace_id = a.workspace_id "
            "LEFT JOIN Owners o ON o.owner_id = a.owner_id "
            "LEFT JOIN Semantic_Models m ON m.model_id = a.model_id WHERE a.asset_id = ?", asset_id)
    if r is None:
        similar = rows("SELECT asset_id, asset_name FROM Analytics_Assets WHERE asset_name LIKE '%' || ? || '%' "
                       "LIMIT 5", asset_id)
        return {"tool": "asset_report", "summary": f"Asset '{asset_id}' not found",
                "evidence": [], "data": {"similar": [{"asset": a, "name": n} for a, n in similar]}}
    (aid, name, atype, platform, life, endorse, audience, pscope, mscope, created, modified,
     classification, delivery, ws, owner, model_name, refresh, model_endorse) = r
    u = _usage()["assets"].get(aid, {})
    kpis = rows("SELECT k.kpi_id, k.kpi_name, k.canonical_metric, k.approval_status, km.usage_role "
                "FROM Asset_KPI_Map km JOIN KPI_Catalog k ON k.kpi_id = km.kpi_id WHERE km.asset_id = ?", aid)
    signals = rows("SELECT signal_code, severity, status FROM Governance_Signals WHERE asset_id = ?", aid)
    upstream = rows("SELECT e.source_id, m.model_name, m.refresh_status, m.endorsement FROM Lineage_Edges e "
                    "JOIN Semantic_Models m ON m.model_id = e.source_id "
                    "WHERE e.target_id = ? AND e.edge_type = 'MODEL_TO_ASSET'", aid)
    embeds = rows("SELECT e.source_id, a.asset_name FROM Lineage_Edges e JOIN Analytics_Assets a "
                  "ON a.asset_id = e.source_id WHERE e.target_id = ? AND e.edge_type = 'ASSET_TO_ASSET'", aid)
    embedded_by = rows("SELECT e.target_id, a.asset_name FROM Lineage_Edges e JOIN Analytics_Assets a "
                       "ON a.asset_id = e.target_id WHERE e.source_id = ? AND e.edge_type = 'ASSET_TO_ASSET'", aid)
    model_id = one("SELECT model_id FROM Analytics_Assets WHERE asset_id = ?", aid)
    dq = []
    ids = [aid] + ([model_id] if model_id else [])
    for rid in ids:
        dq += rows("SELECT sheet, field, issue_value, severity, impact FROM Data_Quality WHERE record_id = ?", rid)
    unappr_kpis = [k for k in kpis if k[3] != "approved"]
    parts = [f"{aid} '{name}' [{platform} {atype}, {life}, endorsement={endorse or 'none'}]",
             f"usage: {u.get('views', 0)} views ({u.get('decile', '?')} decile), "
             f"{u.get('avg_users', 0)} avg users, {u.get('errors', 0)} errors, "
             f"load {u.get('avg_load_ms', 0)}ms, momentum {u.get('recent_vs_prior_ratio', 'n/a')}"]
    if owner:
        parts.append(f"owner: {owner}")
    else:
        parts.append("owner: MISSING")
    if model_name:
        parts.append(f"model: {model_name} (refresh={refresh}, {model_endorse})")
    if kpis:
        parts.append(f"KPIs: {len(kpis)} mapped, {len(unappr_kpis)} unapproved")
    if signals:
        parts.append(f"governance signals: {', '.join(s[0] + '/' + s[1] for s in signals)}")
    if embedded_by:
        parts.append(f"embedded by {len(embedded_by)} other assets (retirement impact)")
    summary = "; ".join(parts)
    evidence = [f"{aid}: {name} ({platform}, {life})",
                f"views={u.get('views', 0)} ({u.get('decile', '?')} decile), audience={audience}"]
    evidence += [f"KPI {k} {kn} [{cm}] {ap}" for k, kn, cm, ap, _ in kpis[:10]]
    evidence += [f"signal {s}/{se} ({st})" for s, se, st in signals]
    evidence += [f"upstream model {s} '{mn}' refresh={rf}" for s, mn, rf, _ in upstream]
    data = {"asset_id": aid, "asset_name": name, "asset_type": atype, "platform": platform,
            "lifecycle_status": life, "endorsement": endorse, "estimated_audience": audience,
            "product_scope": pscope, "market_scope": mscope, "workspace": ws, "owner": owner,
            "model": model_name, "model_refresh_status": refresh, "model_endorsement": model_endorse,
            "usage": u, "kpis": [{"kpi": k, "name": kn, "canonical_metric": cm, "approval_status": ap,
                                  "usage_role": ur} for k, kn, cm, ap, ur in kpis],
            "governance_signals": [{"code": s, "severity": se, "status": st} for s, se, st in signals],
            "data_quality_issues": [{"sheet": s, "field": f, "value": v, "severity": se, "impact": im}
                                    for s, f, v, se, im in dq],
            "upstream_models": [{"model": s, "name": mn, "refresh": rf, "endorsement": en}
                                for s, mn, rf, en in upstream],
            "embeds_assets": [{"asset": s, "name": n} for s, n in embeds],
            "embedded_by": [{"asset": s, "name": n} for s, n in embedded_by]}
    return {"tool": "asset_report", "summary": summary, "evidence": evidence, "data": data}


def tool_blast_radius(model_id):
    m = one("SELECT model_id, model_name, endorsement, refresh_status, refresh_frequency "
            "FROM Semantic_Models WHERE model_id = ?", model_id)
    if m is None:
        known = rows("SELECT model_id, model_name FROM Semantic_ModelS WHERE model_name LIKE '%' || ? || '%' "
                     "LIMIT 5", model_id)
        return {"tool": "blast_radius", "summary": f"Model '{model_id}' not found",
                "evidence": [], "data": {"similar": [{"model": a, "name": n} for a, n in known]}}
    downstream = rows("SELECT a.asset_id, a.asset_name, a.platform, a.lifecycle_status "
                     "FROM Lineage_Edges e JOIN Analytics_Assets a ON a.asset_id = e.target_id "
                     "WHERE e.source_id = ? AND e.edge_type = 'MODEL_TO_ASSET'", model_id)
    down_models = rows("SELECT t.model_id, t.model_name, t.refresh_status FROM Lineage_Edges e "
                       "JOIN Semantic_Models t ON t.model_id = e.target_id "
                       "WHERE e.source_id = ? AND e.edge_type = 'MODEL_TO_MODEL'", model_id)
    up_models = rows("SELECT s.model_id, s.model_name, s.refresh_status FROM Lineage_Edges e "
                     "JOIN Semantic_Models s ON s.model_id = e.source_id "
                     "WHERE e.target_id = ? AND e.edge_type = 'MODEL_TO_MODEL'", model_id)
    flag = " FAILED REFRESH — downstream data is stale" if m[3] == "failed" else ""
    summary = (f"{m[0]} '{m[1]}' (endorsement={m[2]}, refresh={m[3]}): {len(downstream)} downstream assets, "
               f"{len(down_models)} downstream models, {len(up_models)} upstream models.{flag}")
    evidence = [f"{a} '{n}' ({p}, {l})" for a, n, p, l in downstream[:12]]
    if len(downstream) > 12:
        evidence.append(f"(+{len(downstream) - 12} more downstream assets)")
    data = {"model_id": m[0], "model_name": m[1], "endorsement": m[2], "refresh_status": m[3],
            "refresh_frequency": m[4],
            "downstream_assets": [{"asset": a, "name": n, "platform": p, "lifecycle": l}
                                  for a, n, p, l in downstream],
            "downstream_models": [{"model": a, "name": n, "refresh": rf} for a, n, rf in down_models],
            "upstream_models": [{"model": a, "name": n, "refresh": rf} for a, n, rf in up_models]}
    return {"tool": "blast_radius", "summary": summary, "evidence": evidence, "data": data}


def tool_migration_review(asset_id):
    b = one("SELECT source_asset_id, recommended_path_candidate, candidate_target_model_id, complexity, "
            "status, synthetic_reason FROM Migration_Backlog WHERE source_asset_id = ?", asset_id)
    a = one("SELECT asset_name, platform, lifecycle_status, product_scope, market_scope "
            "FROM Analytics_Assets WHERE asset_id = ?", asset_id)
    if b is None:
        return {"tool": "migration_review", "summary": f"{asset_id} is not in the migration backlog",
                "evidence": [f"{asset_id} {a[0] if a else '(unknown asset)'}"],
                "data": {"in_backlog": False, "asset": dict(zip(
                    ["asset_name", "platform", "lifecycle_status", "product_scope", "market_scope"], a)) if a else None}}
    u = _usage()["assets"].get(asset_id, {})
    target = one("SELECT model_name, refresh_status, endorsement FROM Semantic_Models "
                 "WHERE model_id = ?", b[2])
    sanity = None
    if b[1] in ("MIGRATE", "REBUILD_ON_SHARED_MODEL") and u.get("decile") == "bottom":
        sanity = f"SANITY FLAG: only {u.get('views', 0)} views ({u.get('decile')} decile) — consider retiring instead of migrating"
    if b[1] == "RETIRE" and u.get("decile") == "top":
        sanity = f"SANITY FLAG: {u.get('views', 0)} views ({u.get('decile')} decile) — still heavily used, verify before retiring"
    summary = (f"{asset_id} '{a[0] if a else '?'}': recommended path {b[1]} ({b[4]}, complexity {b[3]}), "
               f"target model {b[2]}{f' ({target[0]}, refresh={target[1]})' if target else ''}. "
               f"Usage: {u.get('views', 0)} views ({u.get('decile', '?')} decile).")
    if sanity:
        summary += f" {sanity}"
    evidence = [f"{asset_id} -> {b[1]} -> target {b[2]} ({b[3]}, {b[4]})",
                f"reason: {b[5]}",
                f"usage: {u.get('views', 0)} views ({u.get('decile', '?')} decile)"]
    data = {"asset_id": asset_id, "asset_name": a[0] if a else None,
            "recommended_path": b[1], "target_model": b[2],
            "target_model_name": target[0] if target else None,
            "target_model_refresh": target[1] if target else None,
            "complexity": b[3], "status": b[4], "reason": b[5], "usage": u, "sanity_flag": sanity}
    return {"tool": "migration_review", "summary": summary, "evidence": evidence, "data": data}


def tool_ground_metric(metric):
    backing = KPI_GROUNDING.get(metric)
    status = "not grounded" if backing is None else ("derived" if backing.startswith("derived:") else "grounded")
    variants = rows("SELECT kpi_id, kpi_name, definition_status, approval_status, domain, business_criticality "
                    "FROM KPI_Catalog WHERE UPPER(canonical_metric) = UPPER(?)", metric)
    if not variants and backing is None:
        known = sorted(KPI_GROUNDING) + [r[0] for r in rows(
            "SELECT DISTINCT canonical_metric FROM KPI_Catalog ORDER BY 1")]
        return {"tool": "ground_metric", "summary": f"Unknown metric '{metric}'",
                "evidence": [], "data": {"known_metrics": sorted(set(known))}}
    domains = sorted({v[4] for v in variants})
    summary = (f"{metric}: {status}"
               + (f" via {backing}" if backing else " — no backing data column exists in the context sheets")
               + f"; {len(variants)} KPI variants, domains: {', '.join(domains) or 'n/a'}")
    evidence = [f"{metric}: status={status}; backed_by={backing or '-'}"] + \
               [f"{v[0]} {v[1]} [{v[2]}/{v[3]}] {v[4]}" for v in variants[:6]]
    data = {"metric": metric, "status": status, "backed_by": backing or None,
            "domains": domains,
            "kpi_variants": [{"kpi": v[0], "name": v[1], "definition_status": v[2],
                              "approval_status": v[3], "domain": v[4], "criticality": v[5]}
                             for v in variants]}
    return {"tool": "ground_metric", "summary": summary, "evidence": evidence, "data": data}


def _resolve_market_ids(market):
    if not market or market == "Global" or market == "global":
        return None
    ids = rows("SELECT market_id FROM Markets WHERE UPPER(market_id) = UPPER(?)", market)
    if ids:
        return [ids[0][0]]
    ids = rows("SELECT market_id FROM Markets WHERE UPPER(region) = UPPER(?)", market)
    if ids:
        return [r[0] for r in ids]
    names = rows("SELECT market_id FROM Markets WHERE UPPER(market_name) = UPPER(?)", market)
    if names:
        return [names[0][0]]
    return False


def tool_find_reuse_candidates(product=None, market=None, domains=None):
    if not domains:
        domains = ["Commercial"]
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.split(",") if d.strip()]
    valid = sorted({r[0] for r in rows("SELECT DISTINCT domain FROM KPI_Catalog")})
    bad = [d for d in domains if d not in valid]
    if bad:
        return {"tool": "find_reuse_candidates",
                "summary": f"Unknown domain(s): {', '.join(bad)}",
                "evidence": [], "data": {"valid_domains": valid}}
    dph = ",".join("?" * len(domains))
    sql = ("SELECT DISTINCT a.asset_id, a.asset_name, a.platform, a.endorsement, a.product_scope, "
           "a.market_scope, sm.refresh_status FROM Analytics_Assets a "
           "JOIN Asset_KPI_Map km ON km.asset_id = a.asset_id "
           "JOIN KPI_Catalog k ON k.kpi_id = km.kpi_id "
           "LEFT JOIN Semantic_Models sm ON sm.model_id = a.model_id "
           f"WHERE a.lifecycle_status = 'active' AND k.domain IN ({dph})")
    params = list(domains)
    if product:
        sql += " AND (a.product_scope = ? OR a.product_scope = 'All Pharma')"
        params.append(product)
    mids = _resolve_market_ids(market)
    if mids is False:
        known = rows("SELECT market_id, region FROM Markets ORDER BY 1")
        return {"tool": "find_reuse_candidates", "summary": f"Unknown market '{market}'",
                "evidence": [], "data": {"valid_markets": [{"market": m, "region": r} for m, r in known]}}
    if mids:
        mph = ",".join("?" * len(mids))
        sql += f" AND (a.market_scope IN ({mph}) OR a.market_scope = 'Global')"
        params += mids
    found = rows(sql + " ORDER BY a.asset_id", *params)
    uc = _usage()["assets"]

    def score(r):
        end = {"certified": 3, "promoted": 2}.get(r[3] or "none", 1)
        ref = {"healthy": 3, "warning": 1, "failed": 0.5}.get(r[6] or "", 1)
        return (uc.get(r[0], {}).get("views", 0)) * end * ref

    found = sorted(found, key=score, reverse=True)
    capped, more = _cap(found, 15)
    out = []
    for aid, name, platform, endorse, pscope, mscope, refresh in capped:
        uu = uc.get(aid, {})
        out.append({"asset": aid, "name": name, "platform": platform, "endorsement": endorse or "none",
                    "product_scope": pscope, "market_scope": mscope, "model_refresh": refresh,
                    "views": uu.get("views", 0), "usage_decile": uu.get("decile"),
                    "avg_users": uu.get("avg_users", 0)})
    top = out[0] if out else None
    summary = (f"{len(found)} active assets already cover {product or 'any product'} x "
               f"{market or 'any market'} in {', '.join(domains)}"
               + (f"; top: {top['asset']} '{top['name']}' ({top['views']} views, {top['endorsement']})"
                  if top else " — no coverage found, candidate for genuine new build"))
    evidence = [f"{o['asset']} '{o['name']}' [{o['platform']}|{o['endorsement']}|{o['model_refresh']}] "
                f"{o['views']} views" for o in out[:10]]
    if len(found) > 15:
        evidence.append(f"(+{len(found) - 15} more)")
    return {"tool": "find_reuse_candidates", "summary": summary, "evidence": evidence,
            "data": {"covering_assets": len(found), "candidates": out, "truncated": more}}


def tool_usage_stats(asset_id):
    exists = one("SELECT COUNT(*) FROM Analytics_Assets WHERE asset_id = ?", asset_id)
    if not exists:
        return {"tool": "usage_stats", "summary": f"Asset '{asset_id}' not found", "evidence": [], "data": {}}
    monthly = rows("SELECT month, views, unique_users, exports, query_errors, avg_load_ms FROM Asset_Usage "
                   "WHERE asset_id = ? ORDER BY month", asset_id)
    u = _usage()["assets"].get(asset_id, {})
    mom = u.get("recent_vs_prior_ratio")
    mom_txt = f"{mom}x recent vs prior pace" if mom is not None else "n/a"
    summary = (f"{asset_id}: {u.get('views', 0)} total views over {len(monthly)} months "
               f"({u.get('decile', '?')} decile), {u.get('errors', 0)} errors, "
               f"momentum {mom_txt}")
    evidence = [f"{m}: {v} views, {e} errors" for m, v, _, _, e, _ in monthly[-6:]]
    data = {"asset_id": asset_id, "total_views": u.get("views"), "decile": u.get("decile"),
            "avg_users": u.get("avg_users"), "exports": u.get("exports"),
            "query_errors": u.get("errors"), "avg_load_ms": u.get("avg_load_ms"),
            "recent_vs_prior_ratio": mom,
            "monthly": [{"month": m, "views": v, "users": uu, "exports": ex, "errors": er, "load_ms": ld}
                        for m, v, uu, ex, er, ld in monthly]}
    return {"tool": "usage_stats", "summary": summary, "evidence": evidence, "data": data}


def tool_similar_requests(text):
    words = {w.strip(".,?!\"'()").lower() for w in text.split() if len(w) > 3}
    templates = rows("SELECT request_text, COUNT(*) FROM Business_Requests GROUP BY 1")
    scored = []
    for t, n in templates:
        tw = {w.strip(".,?!\"'()").lower() for w in t.split() if len(w) > 3}
        overlap = len(words & tw)
        scored.append((overlap, t, n))
    scored.sort(key=lambda s: -s[0])
    out = []
    for overlap, t, n in scored[:3]:
        if overlap == 0:
            continue
        ctx = rows("SELECT product_context, market_context FROM Business_Requests WHERE request_text = ?", t)
        products = sorted({c for c, _ in ctx})
        markets = sorted({c for _, c in ctx})
        out.append({"match_score": overlap, "requests": n, "intent": classify_intent(t), "text": t,
                    "product_contexts": products, "market_contexts": markets[:10]})
    summary = (f"{len(out)} similar past request template(s) found"
               + (f"; closest: [{out[0]['intent']}] x{out[0]['requests']} '{out[0]['text'][:80]}...'"
                  if out else " — no overlap with the 10 known templates"))
    return {"tool": "similar_requests", "summary": summary,
            "evidence": [f"[{o['intent']}] x{o['requests']}: {o['text']}" for o in out],
            "data": {"matches": out}}


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex)\b",
                       re.IGNORECASE)


def tool_run_readonly_sql(sql):
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return {"tool": "run_readonly_sql", "summary": "Rejected: multiple statements are not allowed",
                "evidence": [], "data": {"error": "multiple statements not allowed"}}
    lowered = stripped.lower()
    if not lowered.startswith(("select", "with")):
        return {"tool": "run_readonly_sql",
                "summary": "Rejected: only SELECT/WITH queries are allowed",
                "evidence": [], "data": {"error": "only read-only SELECT/WITH queries are allowed"}}
    if _FORBIDDEN.search(stripped):
        return {"tool": "run_readonly_sql",
                "summary": "Rejected: write/DDL keywords are not allowed",
                "evidence": [], "data": {"error": "forbidden keyword detected"}}
    cur = db().execute(stripped)
    cols = [d[0] for d in cur.description]
    fetched = cur.fetchmany(201)
    truncated = len(fetched) == 201
    out_rows = [[_clip(c, 200) for c in r] for r in fetched[:200]]
    summary = f"Query returned {len(out_rows)} rows{', truncated to 200' if truncated else ''} ({', '.join(cols[:6])})"
    return {"tool": "run_readonly_sql", "summary": summary, "evidence": [summary],
            "data": {"columns": cols, "rows": out_rows, "row_count": len(out_rows),
                     "truncated": truncated, "sql": stripped}}


TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "estate_overview",
        "description": "Get BI estate overview: asset/model/KPI/governance counts and platform x lifecycle split. "
                       "Good first call to understand scale.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "find_kpi_conflicts",
        "description": "Find canonical metrics with conflicting KPI definitions (multiple variants, "
                       "unapproved variants, assets mixing variants). Optionally focus on one canonical metric.",
        "parameters": {"type": "object", "properties": {
            "canonical_metric": {"type": "string", "description": "e.g. 'Net Sales'; omit for all"}}}}},
    {"type": "function", "function": {
        "name": "find_assets_using_kpi",
        "description": "Resolve a KPI name or canonical metric to its variants and the assets using each "
                       "(with approval status). Use when a business question mentions a metric.",
        "parameters": {"type": "object", "required": ["name"], "properties": {
            "name": {"type": "string", "description": "KPI name, KPI id (KPI-001) or canonical metric"}}}}},
    {"type": "function", "function": {
        "name": "find_duplicate_assets",
        "description": "Detect analytics sprawl: identical-scope asset groups, same product-market served on "
                       "both platforms, duplicate asset names.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "asset_report",
        "description": "Full report for one asset: usage decile, ownership, KPI mapping (incl. unapproved), "
                       "governance signals, data-quality issues, lineage/embedding. Use before any "
                       "reuse/retire/migrate recommendation.",
        "parameters": {"type": "object", "required": ["asset_id"], "properties": {
            "asset_id": {"type": "string", "description": "e.g. AST-0180"}}}}},
    {"type": "function", "function": {
        "name": "blast_radius",
        "description": "Downstream impact of a semantic model: dependent assets and model-to-model lineage. "
                       "Use to assess impact of failed refresh or model changes.",
        "parameters": {"type": "object", "required": ["model_id"], "properties": {
            "model_id": {"type": "string", "description": "e.g. SM-060"}}}}},
    {"type": "function", "function": {
        "name": "migration_review",
        "description": "Migration backlog status for an asset: recommended path, target model, complexity, "
                       "plus usage sanity checks (migrate-but-unused, retire-but-heavily-used).",
        "parameters": {"type": "object", "required": ["asset_id"], "properties": {
            "asset_id": {"type": "string", "description": "e.g. AST-0140"}}}}},
    {"type": "function", "function": {
        "name": "ground_metric",
        "description": "Check whether a canonical metric is computable from the pharma context data "
                       "(grounded / derived / not grounded) and list its KPI variants. Use to flag "
                       "requests for metrics with no backing data.",
        "parameters": {"type": "object", "required": ["metric"], "properties": {
            "metric": {"type": "string", "description": "canonical metric, e.g. 'Budget Variance'"}}}}},
    {"type": "function", "function": {
        "name": "find_reuse_candidates",
        "description": "Find active assets already covering a product/market/domain combination, ranked by "
                       "usage x endorsement x model health. The core 'build less' check before recommending "
                       "any new build.",
        "parameters": {"type": "object", "required": ["domains"], "properties": {
            "product": {"type": "string", "description": "e.g. 'Lynkuet' or 'All Pharma'"},
            "market": {"type": "string", "description": "market id (US), region (EMEA) or 'Global'"},
            "domains": {"type": "array", "items": {"type": "string"},
                        "description": "KPI domains: Commercial, Supply Chain, Launch Excellence, "
                                       "Market Access, Finance, BI Governance"}}}}},
    {"type": "function", "function": {
        "name": "usage_stats",
        "description": "Monthly usage history, decile and momentum for one asset.",
        "parameters": {"type": "object", "required": ["asset_id"], "properties": {
            "asset_id": {"type": "string", "description": "e.g. AST-0132"}}}}},
    {"type": "function", "function": {
        "name": "similar_requests",
        "description": "Match a business request text against the 10 known request templates and their "
                       "product/market contexts. Use when triaging an incoming business question.",
        "parameters": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string", "description": "the request text"}}}}},
    {"type": "function", "function": {
        "name": "run_readonly_sql",
        "description": "Escape hatch: run a read-only SELECT/WITH query against the SQLite database "
                       "(22 tables incl. Analytics_Assets, KPI_Catalog, Semantic_Models, Lineage_Edges, "
                       "Asset_Usage, Governance_Signals, Migration_Backlog, Business_Requests, "
                       "Product_Market_Monthly, Market_Access, Supply_Operations, Launch_Milestones). "
                       "Use when other tools cannot answer.",
        "parameters": {"type": "object", "required": ["sql"], "properties": {
            "sql": {"type": "string", "description": "single SELECT or WITH query"}}}}},
]

TOOL_FUNCS = {
    "estate_overview": tool_estate_overview,
    "find_kpi_conflicts": tool_find_kpi_conflicts,
    "find_assets_using_kpi": tool_find_assets_using_kpi,
    "find_duplicate_assets": tool_find_duplicate_assets,
    "asset_report": tool_asset_report,
    "blast_radius": tool_blast_radius,
    "migration_review": tool_migration_review,
    "ground_metric": tool_ground_metric,
    "find_reuse_candidates": tool_find_reuse_candidates,
    "usage_stats": tool_usage_stats,
    "similar_requests": tool_similar_requests,
    "run_readonly_sql": tool_run_readonly_sql,
}


def call_tool(name, **args):
    func = TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"unknown tool '{name}'", "available": sorted(TOOL_FUNCS)}
    return func(**args)


def dump_tool_result(result, limit=8000):
    s = json.dumps(result, default=str)
    return s if len(s) <= limit else json.dumps(
        {"summary": result.get("summary"), "evidence": result.get("evidence", []),
         "note": "data truncated"}, default=str)
