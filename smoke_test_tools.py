import json
import sys
import threading

from govagent import tools as T

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


r = T.tool_estate_overview()
check("estate_overview: 360 assets", r["data"]["counts"]["assets"] == 360, str(r["data"]["counts"]))
check("estate_overview: 75 models", r["data"]["counts"]["semantic_models"] == 75)

r = T.tool_find_kpi_conflicts()
check("kpi_conflicts: 18 conflicting canonical metrics",
      len(r["data"]["conflicts"]) == 18, f"got {len(r['data']['conflicts'])}")
check("kpi_conflicts: Net Sales has 3 variants",
      any(c["canonical_metric"] == "Net Sales" and c["variant_count"] == 3
          for c in r["data"]["conflicts"]))

r = T.tool_find_kpi_conflicts("Net Sales")
check("kpi_conflicts('Net Sales'): focused", len(r["data"]["conflicts"]) == 1)
r = T.tool_find_kpi_conflicts("DoesNotExist")
check("kpi_conflicts(unknown): suggests known metrics",
      len(r["data"]["known_canonical_metrics"]) == 18)

r = T.tool_find_assets_using_kpi("Net Sales")
kpis = r["data"]["kpis"]
check("assets_using_kpi('Net Sales'): 3 variants", len(kpis) == 3, f"got {len(kpis)}")
check("assets_using_kpi('Net Sales'): unapproved variant flagged",
      any(k["approval_status"] != "approved" for k in kpis))
r = T.tool_find_assets_using_kpi("KPI-001")
check("assets_using_kpi('KPI-001'): resolves by id", len(r["data"]["kpis"]) == 1)
r = T.tool_find_assets_using_kpi("forecast")
check("assets_using_kpi('forecast'): LIKE fallback finds variants",
      len(r["data"]["kpis"]) >= 4)

r = T.tool_find_duplicate_assets()
check("duplicates: 3 identical-scope groups",
      len(r["data"]["identical_scope_groups"]) == 3)
check("duplicates: 60 cross-platform scopes",
      len(r["data"]["cross_platform_scopes"]) == 60,
      f"got {len(r['data']['cross_platform_scopes'])}")
check("duplicates: 84 assets with duplicate names",
      r["data"]["assets_with_duplicate_names"] == 84)

r = T.tool_asset_report("AST-0180")
d = r["data"]
check("asset_report(AST-0180): candidate_retire", d["lifecycle_status"] == "candidate_retire")
check("asset_report(AST-0180): 13376 views", d["usage"]["views"] == 13376, str(d["usage"]))
check("asset_report(AST-0180): top decile", d["usage"]["decile"] == "top")
r = T.tool_asset_report("AST-0080")
check("asset_report(AST-0080): owner missing flagged", r["data"]["owner"] is None)
check("asset_report(AST-0080): governance MISSING_OWNER signal",
      any(s["code"] == "MISSING_OWNER" for s in r["data"]["governance_signals"]))
r = T.tool_asset_report("AST-9999")
check("asset_report(unknown): helpful error", "similar" in r["data"])

r = T.tool_blast_radius("SM-060")
check("blast_radius(SM-060): 9 downstream assets",
      len(r["data"]["downstream_assets"]) == 9, f"got {len(r['data']['downstream_assets'])}")
check("blast_radius(SM-060): failed refresh", r["data"]["refresh_status"] == "failed")

r = T.tool_migration_review("AST-0140")
d = r["data"]
check("migration_review(AST-0140): RETIRE path", d["recommended_path"] == "RETIRE")
check("migration_review(AST-0140): sanity flag on heavy usage", d["sanity_flag"] is not None)
r = T.tool_migration_review("AST-0001")
d = r["data"]
check("migration_review(non-backlog): reports not in backlog", d["in_backlog"] is False)

r = T.tool_ground_metric("Budget Variance")
check("ground_metric('Budget Variance'): not grounded", r["data"]["status"] == "not grounded")
r = T.tool_ground_metric("Net Sales")
check("ground_metric('Net Sales'): grounded", r["data"]["status"] == "grounded")
r = T.tool_ground_metric("Demand Forecast Bias")
check("ground_metric('Demand Forecast Bias'): derived", r["data"]["status"] == "derived")

r = T.tool_find_reuse_candidates(product="Lynkuet", market="Global",
                                 domains=["Market Access", "Launch Excellence"])
check("reuse_candidates(Lynkuet): >=19 covering assets",
      r["data"]["covering_assets"] >= 19, f"got {r['data']['covering_assets']}")
check("reuse_candidates: candidates carry usage evidence",
      r["data"]["candidates"] and r["data"]["candidates"][0]["views"] > 0)
r = T.tool_find_reuse_candidates(product="Xarelto", market="US", domains=["FakeDomain"])
check("reuse_candidates(bad domain): suggests valid domains",
      "valid_domains" in r["data"])
r = T.tool_find_reuse_candidates(product="Xarelto", market="Mars", domains=["Commercial"])
check("reuse_candidates(bad market): suggests valid markets", "valid_markets" in r["data"])

r = T.tool_usage_stats("AST-0132")
check("usage_stats(AST-0132): bottom decile", r["data"]["decile"] == "bottom")
check("usage_stats(AST-0132): 10 monthly rows", len(r["data"]["monthly"]) == 10)

r = T.tool_similar_requests("launch dashboard for Lynkuet with market access and adoption")
check("similar_requests: finds Lynkuet launch template",
      r["data"]["matches"] and r["data"]["matches"][0]["requests"] == 17,
      str(r["data"]["matches"][:1]))

r = T.tool_run_readonly_sql("SELECT COUNT(*) AS n FROM Analytics_Assets")
check("readonly_sql: count 360", r["data"]["rows"][0][0] == 360)
r = T.tool_run_readonly_sql("DELETE FROM Analytics_Assets")
check("readonly_sql: rejects DELETE", "error" in r["data"])
r = T.tool_run_readonly_sql("SELECT 1; DROP TABLE x")
check("readonly_sql: rejects multi-statement", "error" in r["data"])
r = T.tool_run_readonly_sql("SELECT asset_id FROM Asset_Usage")
check("readonly_sql: auto-limits to 200", r["data"]["row_count"] == 200 and r["data"]["truncated"])

serialized = {name: T.dump_tool_result(T.call_tool(name)) for name in
              ["find_kpi_conflicts", "find_duplicate_assets", "find_reuse_candidates"]}
check("tool results serialize and stay under size cap",
      all(len(s) <= 8000 for s in serialized.values()))

thread_errors = []
thread_barrier = threading.Barrier(4)


def _thread_worker(asset):
    try:
        thread_barrier.wait()
        r = T.tool_asset_report(asset)
        if r["data"].get("asset_id") != asset:
            thread_errors.append(f"wrong asset returned for {asset}")
        T.tool_estate_overview()
        T.tool_usage_stats(asset)
    except Exception as e:
        thread_errors.append(f"{asset}: {e}")


threads = [threading.Thread(target=_thread_worker, args=(a,))
           for a in ["AST-0180", "AST-0080", "AST-0132", "AST-0140"]]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("threaded tool calls succeed (Streamlit rerun simulation)",
      not thread_errors, str(thread_errors[:2]))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL CHECKS PASSED")
