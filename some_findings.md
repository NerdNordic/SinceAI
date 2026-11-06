
==========================================================================
1. ESTATE OVERVIEW
==========================================================================

-- Core counts
  metric              value
  ------------------  -----
  assets              360
  semantic_models     75
  kpis                56
  lineage_edges       438
  usage_rows          3600
  governance_signals  410
  migration_items     94
  business_requests   150

-- Assets: platform x lifecycle
  platform  active  candidate_retire  legacy  total
  --------  ------  ----------------  ------  -----
  Power BI  148     62                56      266
  Tableau   53      24                17      94
  total     201     86                73      360

-- Assets: type x platform
  asset_type  Power BI  Tableau  total
  ----------  --------  -------  -----
  App         86        0        86
  Dashboard   85        0        85
  Report      95        0        95
  Workbook    0         94       94
  total       266       94       360

-- Semantic models: endorsement x refresh status
  endorsement  failed  healthy  warning  total
  -----------  ------  -------  -------  -----
  certified    3       11       4        18
  none         8       22       9        39
  promoted     3       9        6        18
  total        14      42       19       75

-- Coverage gaps
  models with no downstream assets: 1
  model   name             endorsement  refresh
  ------  ---------------  -----------  -------
  SM-009  Gross-to-Net 09  none         warning
  assets with no lineage edge at all: 0

-- Busiest workspaces (by asset count)
  workspace                  platform  assets
  -------------------------  --------  ------
  Pharma Finance             Power BI  30
  Oncology Commercial        Power BI  29
  LATAM Commercial           Power BI  28
  North America Commercial   Power BI  26
  Cardiovascular Commercial  Power BI  24
  EMEA Commercial            Power BI  23
  APAC Commercial            Power BI  23
  Ophthalmology Commercial   Power BI  22

==========================================================================
2. DUPLICATE / OVERLAP DETECTION
==========================================================================

-- Asset groups sharing identical scope (product x market x model)
  3 scope-groups contain multiple assets, covering 6 assets in total
  product    market  model   assets
  ---------  ------  ------  ------
  Beyonttra  ES      SM-074  2
  Lynkuet    CN      SM-063  2
  Lynkuet    Global  SM-019  2

-- Cross-platform overlap: same product x market served on both platforms
  60 product-market scopes served on more than one platform
  product    market  platforms
  ---------  ------  ---------
  Eylea      US      2
  Hyrnuo     US      2
  Lynkuet    US      2
  Nubeqa     US      2
  Xarelto    US      2
  Beyonttra  UK      2
  Eylea      UK      2
  Lynkuet    UK      2
  Xarelto    UK      2
  Eylea      SE      2

-- Exact duplicate asset names
  40 asset names are shared by 84 assets
  asset_name                        count  platforms                   distinct_platforms
  --------------------------------  -----  --------------------------  ------------------
  Xarelto Budget New                3      Power BI,Power BI,Tableau   2
  Nubeqa Budget Mgmt                3      Power BI,Power BI,Power BI  1
  Eylea Inventory Final             3      Tableau,Power BI,Tableau    2
  All Pharma Supply                 3      Power BI,Power BI,Power BI  1
  Xarelto Product Performance - US  2      Power BI,Tableau            2
  Nubeqa Supply - US                2      Power BI,Power BI           1
  Nubeqa Net Sales Mgmt             2      Power BI,Power BI           1
  Nubeqa Gross-to-Net               2      Power BI,Power BI           1
  Nubeqa Forecast Monthly           2      Power BI,Power BI           1
  Nubeqa Executive Final            2      Power BI,Power BI           1

==========================================================================
3. USAGE PROFILING
==========================================================================
  usage window: 2026-01-01 .. 2026-10-01 (recent 3 months from 2026-08-01)
  per-asset total views: min=37, p10=45, median=2680, p90=11879, max=13379

-- Monthly estate usage trend
  month       views   exports  errors
  ----------  ------  -------  ------
  2026-01-01  119379  4525     1524
  2026-02-01  122664  5050     1576
  2026-03-01  120854  4447     1618
  2026-04-01  120555  4760     1793
  2026-05-01  122692  4781     1658
  2026-06-01  120349  4753     1673
  2026-07-01  121938  4675     1693
  2026-08-01  118171  4437     1683
  2026-09-01  123708  4695     1728
  2026-10-01  120927  4633     1798

-- Active assets with bottom-decile usage (views <= 45) — waste candidates
  29 active assets with near-zero consumption
  asset     name                            platform  views  avg_users
  --------  ------------------------------  --------  -----  ---------
  AST-0132  Nubeqa Net Sales                Power BI  37     0.2
  AST-0161  Hyrnuo Inventory - Global       Power BI  37     0.2
  AST-0129  All Pharma Portfolio Monthly    Power BI  38     0.1
  AST-0159  Eylea Commercial Reach - EMEA   Power BI  40     0.1
  AST-0053  All Pharma Launch Mgmt          Tableau   41     0.3
  AST-0210  Beyonttra Executive Copy        Power BI  41     0.2
  AST-0058  Eylea Budget - Global           Tableau   42     0.3
  AST-0236  Lynkuet Forecast - Global       Power BI  42     0.3
  AST-0266  Nubeqa Inventory Final          Power BI  42     0.3
  AST-0270  Nubeqa Commercial Reach Legacy  Power BI  42     0.6

-- Legacy / retire-candidate assets with top-decile usage (views >= 11879) — risky retirement
  17 non-active assets still heavily used
  asset     name                                lifecycle         views  avg_users
  --------  ----------------------------------  ----------------  -----  ---------
  AST-0180  Kerendia Executive - EMEA           candidate_retire  13376  225.3
  AST-0293  Kerendia Supply - Global            legacy            13199  235.3
  AST-0089  All Pharma Demand Legacy            legacy            12930  309.4
  AST-0086  Kerendia Executive - EMEA           candidate_retire  12674  280.1
  AST-0050  Hyrnuo Demand Legacy                legacy            12606  253.1
  AST-0233  Nubeqa Forecast - Global            candidate_retire  12598  264.0
  AST-0140  Eylea Inventory Final               legacy            12426  192.6
  AST-0195  Xarelto Digital Engagement Monthly  candidate_retire  12384  255.5
  AST-0095  Xarelto Launch Monthly              legacy            12364  262.0
  AST-0047  Kerendia Budget v2                  legacy            12341  218.3

-- Usage momentum: recent 3 months vs prior 7 months (top decliners among active assets)
  0 active assets with recent usage under 50% of prior pace
  (none)

-- Worst performers: load time and query errors
  asset     name                            avg_load_ms  errors
  --------  ------------------------------  -----------  ------
  AST-0060  Eylea Product Performance Copy  8287         3
  AST-0082  Hyrnuo Gross-to-Net Final       8202         44
  AST-0027  Lynkuet Net Sales Final         8002         38
  AST-0009  Nubeqa Supply - US              7831         0
  AST-0193  Kerendia Demand New             7826         3
  asset     name                      errors  views
  --------  ------------------------  ------  -----
  AST-0091  Hyrnuo Growth - US        247     13035
  AST-0316  Nubeqa Gross-to-Net Copy  239     13379
  AST-0194  Eylea Net Sales v2        238     12036
  AST-0217  Xarelto Supply - US       228     11740
  AST-0059  Xarelto Launch - US       227     11915

==========================================================================
4. KPI GOVERNANCE & CONFLICTS
==========================================================================

-- Canonical metrics with conflicting definitions
  18 canonical metrics have more than one KPI variant
  canonical_metric               variants  detail                                                                                                                                                            canonical  approved
  -----------------------------  --------  ----------------------------------------------------------------------------------------------------------------------------------------------------------------  ---------  --------
  Demand Forecast Accuracy       4         KPI-006 - Demand Forecast Accuracy | KPI-007 - Demand Forecast Accuracy Mgmt | KPI-008 - Demand Forecast Accuracy v2 | KPI-009 - Demand Forecast Accuracy Legacy  1          1
  Demand Forecast Bias           4         KPI-010 - Demand Forecast Bias | KPI-011 - Demand Forecast Bias Local | KPI-012 - Demand Forecast Bias Legacy | KPI-013 - Demand Forecast Bias Adjusted           1          1
  Forecast Variance              4         KPI-042 - Forecast Variance | KPI-043 - Forecast Variance Adjusted | KPI-044 - Forecast Variance Adjusted | KPI-045 - Forecast Variance Mgmt                      1          1
  Inventory Coverage             4         KPI-016 - Inventory Coverage | KPI-017 - Inventory Coverage Legacy | KPI-018 - Inventory Coverage Mgmt | KPI-019 - Inventory Coverage Mgmt                        1          1
  Launch Adoption Index          4         KPI-023 - Launch Adoption Index | KPI-024 - Launch Adoption Index Adjusted | KPI-025 - Launch Adoption Index v2 | KPI-026 - Launch Adoption Index Adjusted        1          1
  Market Access Coverage         4         KPI-027 - Market Access Coverage | KPI-028 - Market Access Coverage Legacy | KPI-029 - Market Access Coverage Mgmt | KPI-030 - Market Access Coverage Local       1          1
  Budget Variance                3         KPI-039 - Budget Variance | KPI-040 - Budget Variance Mgmt | KPI-041 - Budget Variance v2                                                                         1          1
  Certified Asset Share          3         KPI-054 - Certified Asset Share | KPI-055 - Certified Asset Share Legacy | KPI-056 - Certified Asset Share v2                                                     1          1
  Commercial Reach Index         3         KPI-046 - Commercial Reach Index | KPI-047 - Commercial Reach Index Local | KPI-048 - Commercial Reach Index Adjusted                                             1          1
  Gross-to-Net Rate              3         KPI-034 - Gross-to-Net Rate | KPI-035 - Gross-to-Net Rate Legacy | KPI-036 - Gross-to-Net Rate Legacy                                                             1          1
  Net Sales                      3         KPI-001 - Net Sales | KPI-002 - Net Sales Local | KPI-003 - Net Sales v2                                                                                          1          1
  On-Time In-Full                3         KPI-020 - On-Time In-Full | KPI-021 - On-Time In-Full Mgmt | KPI-022 - On-Time In-Full Local                                                                      1          1
  Reimbursement Status Coverage  3         KPI-031 - Reimbursement Status Coverage | KPI-032 - Reimbursement Status Coverage Legacy | KPI-033 - Reimbursement Status Coverage v2                             1          1
  Report Adoption                3         KPI-051 - Report Adoption | KPI-052 - Report Adoption Adjusted | KPI-053 - Report Adoption Legacy                                                                 1          1
  Digital Engagement Index       2         KPI-049 - Digital Engagement Index | KPI-050 - Digital Engagement Index Adjusted                                                                                  1          1
  Net Sales Growth               2         KPI-004 - Net Sales Growth | KPI-005 - Net Sales Growth Local                                                                                                     1          1
  Operating Contribution         2         KPI-037 - Operating Contribution | KPI-038 - Operating Contribution Mgmt                                                                                          1          1
  Units Shipped                  2         KPI-014 - Units Shipped | KPI-015 - Units Shipped v2                                                                                                              1          1

-- Definition / approval status across KPI catalog
  definition_status    approval_status  count
  -------------------  ---------------  -----
  canonical            approved         18
  duplicate_candidate  local            8
  definition_conflict  local            7
  definition_conflict  unapproved       5
  duplicate_candidate  draft            4
  duplicate_candidate  unapproved       4
  local_variant        local            4
  local_variant        draft            3
  local_variant        unapproved       2
  definition_conflict  draft            1

-- Assets referencing unapproved KPI variants
  349 assets reference at least one unapproved KPI variant
  kpi      name                                  canonical                      assets_using
  -------  ------------------------------------  -----------------------------  ------------
  KPI-033  Reimbursement Status Coverage v2      Reimbursement Status Coverage  36
  KPI-005  Net Sales Growth Local                Net Sales Growth               34
  KPI-002  Net Sales Local                       Net Sales                      33
  KPI-036  Gross-to-Net Rate Legacy              Gross-to-Net Rate              33
  KPI-041  Budget Variance v2                    Budget Variance                32
  KPI-028  Market Access Coverage Legacy         Market Access Coverage         31
  KPI-032  Reimbursement Status Coverage Legacy  Reimbursement Status Coverage  30
  KPI-040  Budget Variance Mgmt                  Budget Variance                30
  KPI-003  Net Sales v2                          Net Sales                      29
  KPI-019  Inventory Coverage Mgmt               Inventory Coverage             29
  KPI-024  Launch Adoption Index Adjusted        Launch Adoption Index          29
  KPI-045  Forecast Variance Mgmt                Forecast Variance              29
  KPI-007  Demand Forecast Accuracy Mgmt         Demand Forecast Accuracy       28
  KPI-018  Inventory Coverage Mgmt               Inventory Coverage             28
  KPI-038  Operating Contribution Mgmt           Operating Contribution         28

-- Assets mixing multiple KPI variants of the same canonical metric
  15 asset/canonical-metric combinations mix conflicting definitions (top 15 shown)
  asset     name                                  canonical_metric               kpi_variants_used
  --------  ------------------------------------  -----------------------------  -----------------
  AST-0155  Xarelto Inventory New                 Demand Forecast Accuracy       3
  AST-0321  All Pharma Launch - EMEA              Report Adoption                3
  AST-0010  All Pharma Commercial Reach - Global  Demand Forecast Accuracy       2
  AST-0012  All Pharma Gross-to-Net - Global      Certified Asset Share          2
  AST-0013  Beyonttra Budget Final                Net Sales                      2
  AST-0018  All Pharma Market Access - US         Certified Asset Share          2
  AST-0019  All Pharma Forecast                   Gross-to-Net Rate              2
  AST-0024  Hyrnuo Product Performance - US       Inventory Coverage             2
  AST-0026  Nubeqa Growth v2                      Budget Variance                2
  AST-0026  Nubeqa Growth v2                      Market Access Coverage         2
  AST-0033  Kerendia Portfolio Legacy             Inventory Coverage             2
  AST-0035  Nubeqa Budget Monthly                 Market Access Coverage         2
  AST-0040  Beyonttra Digital Engagement New      Market Access Coverage         2
  AST-0042  Eylea Net Sales Final                 Reimbursement Status Coverage  2
  AST-0044  Eylea Executive Final                 Net Sales                      2

==========================================================================
5. LINEAGE & BLAST RADIUS
==========================================================================

-- Edge types
  edge_type       count
  --------------  -----
  MODEL_TO_ASSET  360
  ASSET_TO_ASSET  56
  MODEL_TO_MODEL  22

-- Downstream blast radius per semantic model (top 10)
  model   name                      refresh  endorsement  downstream_assets
  ------  ------------------------  -------  -----------  -----------------
  SM-062  Channel Performance 62    healthy  none         12
  SM-040  Launch Excellence 40      healthy  none         10
  SM-060  Pharma Finance 60         failed   certified    9
  SM-008  Pharma Finance 08         warning  certified    8
  SM-019  Portfolio Performance 19  warning  promoted     8
  SM-037  Market Access 37          healthy  certified    8
  SM-047  Regional Commercial 47    failed   none         8
  SM-013  Pharma Finance 13         warning  promoted     7
  SM-016  Portfolio Performance 16  healthy  none         7
  SM-017  Gross-to-Net 17           healthy  none         7

-- Models with failed refresh and their downstream exposure
  14 failed models affect 69 downstream assets
  model   name                           downstream_assets
  ------  -----------------------------  -----------------
  SM-060  Pharma Finance 60              9
  SM-047  Regional Commercial 47         8
  SM-068  Demand Forecast 68             6
  SM-063  Demand Forecast 63             6
  SM-043  Executive Pharma 43            6
  SM-004  Launch Excellence 04           6
  SM-035  Launch Excellence 35           5
  SM-021  Product Market Performance 21  5
  SM-064  Demand Forecast 64             4
  SM-034  Regional Commercial 34         4
  SM-044  Portfolio Performance 44       3
  SM-029  Market Access 29               3
  SM-028  Channel Performance 28         3
  SM-003  Gross-to-Net 03                1

-- Model-to-model dependencies
  22 model-to-model dependency edges
  from    name                           to      name
  ------  -----------------------------  ------  -----------------------------
  SM-007  Portfolio Performance 07       SM-053  Pharma Finance 53
  SM-011  Regional Commercial 11         SM-048  Market Access 48
  SM-019  Portfolio Performance 19       SM-068  Demand Forecast 68
  SM-019  Portfolio Performance 19       SM-069  Launch Excellence 69
  SM-029  Market Access 29               SM-034  Regional Commercial 34
  SM-033  Executive Pharma 33            SM-072  Executive Pharma 72
  SM-037  Market Access 37               SM-004  Launch Excellence 04
  SM-039  Pharma Commercial Core 39      SM-017  Gross-to-Net 17
  SM-041  Launch Excellence 41           SM-001  Executive Pharma 01
  SM-042  Product Market Performance 42  SM-025  Product Market Performance 25

-- Asset-to-asset embedded/derived links
  56 assets embed or derive from another asset (impacts retirement decisions)

==========================================================================
6. GOVERNANCE OVERLAY
==========================================================================

-- Signal codes x severity
  signal_code              high  medium  total
  -----------------------  ----  ------  -----
  HIGH_REACH_UNENDORSED    152   0       152
  LIFECYCLE_REVIEW         0     86      86
  MIGRATION_CANDIDATE      0     94      94
  MISSING_OWNER            21    0       21
  SELF_SERVICE_HIGH_REACH  0     57      57
  total                    173   237     410

-- Signal statuses
  status        count
  ------------  -----
  acknowledged  122
  open          288

-- Assets with missing owner
  21 assets have no owner
  asset     name                                platform  audience
  --------  ----------------------------------  --------  --------
  AST-0127  Lynkuet Budget Copy                 Tableau   2043
  AST-0196  Xarelto Forecast v2                 Power BI  1958
  AST-0107  Eylea Market Access Legacy          Power BI  1865
  AST-0046  Lynkuet Supply - US                 Power BI  1770
  AST-0121  Kerendia Inventory Monthly          Tableau   1548
  AST-0324  Lynkuet Digital Engagement Monthly  Tableau   1351
  AST-0080  Eylea Executive Legacy              Power BI  1288
  AST-0060  Eylea Product Performance Copy      Power BI  1237
  AST-0314  Eylea Portfolio New                 Power BI  1207
  AST-0239  Nubeqa Net Sales Copy               Power BI  1206

-- Unendorsed assets with highest reach
  top 10 by estimated audience
  asset     name                                audience  endorsement  platform
  --------  ----------------------------------  --------  -----------  --------
  AST-0016  All Pharma Launch - EMEA            2180      none         Power BI
  AST-0222  Lynkuet Budget v2                   2177      none         Tableau
  AST-0217  Xarelto Supply - US                 2175      none         Power BI
  AST-0117  Beyonttra Commercial Reach Monthly  2146      none         Power BI
  AST-0212  Lynkuet Product Performance v2      2144      none         Power BI
  AST-0110  All Pharma Demand - US              2123      none         Power BI
  AST-0023  Nubeqa Growth Final                 2113      none         Power BI
  AST-0041  Xarelto Product Performance v2      2112      none         Power BI
  AST-0152  Hyrnuo Portfolio Monthly            2111      none         Power BI
  AST-0303  Hyrnuo Growth Legacy                2107      none         Power BI

-- Data quality issues: sheet x severity
  sheet             high  low  medium  total
  ----------------  ----  ---  ------  -----
  Analytics_Assets  21    0    0       21
  Semantic_Models   39    23   64      126
  total             60    23   64      147

-- Most flagged fields (Semantic_Models sheet)
  field             count
  ----------------  -----
  ai_issue_pattern  48
  ai_readiness      45
  refresh_status    33

-- Composite asset risk score (top 10)
  score  asset     name                                lifecycle         signals  dq_issues  model_refresh
  -----  --------  ----------------------------------  ----------------  -------  ---------  -------------
  15     AST-0080  Eylea Executive Legacy              candidate_retire  4        1          failed
  14     AST-0196  Xarelto Forecast v2                 candidate_retire  3        1          failed
  12     AST-0268  Nubeqa Budget Monthly               legacy            3        1          warning
  12     AST-0314  Eylea Portfolio New                 active            2        1          failed
  11     AST-0027  Lynkuet Net Sales Final             candidate_retire  2        1          failed
  11     AST-0060  Eylea Product Performance Copy      legacy            3        1          healthy
  11     AST-0121  Kerendia Inventory Monthly          candidate_retire  4        1          warning
  11     AST-0324  Lynkuet Digital Engagement Monthly  active            4        1          healthy
  10     AST-0046  Lynkuet Supply - US                 legacy            2        1          healthy
  10     AST-0107  Eylea Market Access Legacy          legacy            2        1          healthy

==========================================================================
7. MIGRATION BACKLOG REALITY CHECK
==========================================================================

-- Recommended path x status
  recommended_path              assessed  in_progress  not_started  total
  ----------------------------  --------  -----------  -----------  -----
  CONSOLIDATE_BEFORE_MIGRATION  5         4            3            12
  HUMAN_REVIEW                  5         7            8            20
  MIGRATE                       11        5            6            22
  REBUILD_ON_SHARED_MODEL       5         6            7            18
  RETIRE                        8         10           4            22
  total                         34        32           28           94

-- Complexity
  complexity  count
  ----------  -----
  high        31
  low         25
  medium      38

-- Duplicate target models (several backlog items pointed at the same semantic model)
  12 target models receive more than one migrated asset
  target_model  name                           incoming_items
  ------------  -----------------------------  --------------
  SM-067        Market Access 67               5
  SM-075        Channel Performance 75         4
  SM-037        Market Access 37               4
  SM-070        Launch Excellence 70           3
  SM-045        Demand Forecast 45             3
  SM-040        Launch Excellence 40           3
  SM-036        Demand Forecast 36             3
  SM-023        Pharma Finance 23              3
  SM-022        Product Market Performance 22  3
  SM-021        Product Market Performance 21  3
  SM-014        Executive Pharma 14            3
  SM-011        Regional Commercial 11         3

-- Target model occupancy (assets already living on each target)
  target_model  name                           incoming  already_there
  ------------  -----------------------------  --------  -------------
  SM-062        Channel Performance 62         2         9
  SM-040        Launch Excellence 40           3         8
  SM-008        Pharma Finance 08              2         8
  SM-067        Market Access 67               5         6
  SM-060        Pharma Finance 60              2         6
  SM-047        Regional Commercial 47         1         6
  SM-043        Executive Pharma 43            2         6
  SM-037        Market Access 37               4         6
  SM-022        Product Market Performance 22  3         6
  SM-050        Pharma Finance 50              1         5
  SM-045        Demand Forecast 45             3         5
  SM-038        Supply & Inventory 38          2         5

-- Lifecycle of backlog source assets
  lifecycle         count
  ----------------  -----
  active            53
  candidate_retire  24
  legacy            17

-- Usage cross-check: migrate-vs-retire sanity
  4 MIGRATE/REBUILD items have bottom-decile usage (views <= 45) — retire instead?
  asset     path                     views
  --------  -----------------------  -----
  AST-0028  MIGRATE                  44
  AST-0053  REBUILD_ON_SHARED_MODEL  41
  AST-0096  MIGRATE                  44
  AST-0232  REBUILD_ON_SHARED_MODEL  45
  2 RETIRE items have top-decile usage (views >= 11879) — verify before retiring
  asset     views  name
  --------  -----  ---------------------
  AST-0140  12426  Eylea Inventory Final
  AST-0149  12001  Eylea Budget New

==========================================================================
8. BUSINESS REQUESTS
==========================================================================
  150 requests, only 10 distinct texts (templated corpus)

-- Intent mix over distinct request templates
  intent           requests
  ---------------  --------
  new build        89
  other            25
  replace/migrate  22
  consolidate      14

-- Templates (intent, count, text)
  [replace/migrate] x22: Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook.
  [new build] x20: Can we have a new finance dashboard for net sales, gross-to-net and budget variance by product?
  [new build] x17: Can we build a launch dashboard for Lynkuet with market access, first sales and adoption indicators?
  [new build] x16: Please build a new report for market access coverage and reimbursement status by product.
  [other] x16: I need a dashboard comparing product performance across oncology brands and markets.
  [consolidate] x14: We need one executive view combining net sales, forecast accuracy and inventory coverage for Bayer Pharma.
  [new build] x14: I need a new Kerendia management report for monthly performance in EMEA and North America.
  [new build] x13: Can you create a country-level Beyonttra report for launch readiness and reimbursement progress?
  [other] x9: We need a monthly supply-risk dashboard by medicine and country.
  [new build] x9: Create a global Nubeqa dashboard showing sales growth, forecast variance and market access by country.

-- Request context
  product_context  count
  ---------------  -----
  Lynkuet          24
  Beyonttra        23
  All Pharma       23
  Xarelto          21
  Kerendia         19
  Hyrnuo           16
  Nubeqa           13
  Eylea            11
  market_context  count
  --------------  -----
  UK              14
  CN              14
  SE              12
  FR              11
  Asia Pacific    11
  IT              10
  MX              9
  EMEA            9
  JP              8
  AU              8
  urgency  status   count
  -------  -------  -----
  normal   new      39
  normal   triaged  39
  urgent   new      23
  urgent   triaged  18
  high     new      16
  high     triaged  15

==========================================================================
9. PHARMA CONTEXT DATA INVENTORY
==========================================================================

-- Sheet inventory (grain and row counts)
  sheet                   grain                       rows
  ----------------------  --------------------------  ----
  Products                product                     7
  Markets                 market                      14
  Product_Market_Monthly  product x market x month    980
  Launch_Milestones       product x market milestone  35
  Market_Access           product x market            98
  Supply_Operations       product x market            98

-- Product_Market_Monthly coverage
  months: 2026-01-01 .. 2026-10-01 (10 distinct months)
  product    rows
  ---------  ----
  Beyonttra  140
  Eylea      140
  Hyrnuo     140
  Kerendia   140
  Lynkuet    140
  Nubeqa     140
  Xarelto    140
  value_type               rows
  -----------------------  ----
  actual_like_synthetic    491
  forecast_like_synthetic  489

-- Markets: region x maturity
  region         growth  launch-heavy  mature  total
  -------------  ------  ------------  ------  -----
  Asia Pacific   1       0             2       3
  EMEA           1       1             5       7
  Latin America  1       0             1       2
  North America  0       2             0       2
  total          3       3             8       14

-- Market access: reimbursement status x trend status
  reimbursement  improving  launch_build  review  stable  total
  -------------  ---------  ------------  ------  ------  -----
  listed         4          9             9       11      33
  not_launched   6          6             6       1       19
  partial        6          2             4       3       15
  pending        10         8             5       8       31
  total          26         25            24      23      98

-- Supply operations: risk status
  risk_status  rows  avg_otif_pct  avg_inventory_weeks
  -----------  ----  ------------  -------------------
  green        43    83.1          6.2
  red          29    80.7          6.7
  amber        26    82.6          6.4
  55 non-green product-market hot spots (10 worst OTIF shown)
  product    market          otif_pct  inv_weeks  risk
  ---------  --------------  --------  ---------  -----
  Beyonttra  Finland         65.3      2.1        amber
  Xarelto    Japan           66.0      2.0        red
  Nubeqa     Mexico          66.9      6.0        amber
  Eylea      United Kingdom  66.9      10.0       amber
  Lynkuet    Sweden          67.2      4.3        amber
  Nubeqa     Sweden          69.0      8.8        red
  Nubeqa     Canada          69.8      5.7        red
  Eylea      Germany         70.6      2.3        red
  Beyonttra  United Kingdom  71.2      4.7        red
  Xarelto    France          71.6      9.1        red

-- Launch milestones: type x status
  milestone_type          completed  in_progress  planned  total
  ----------------------  ---------  -----------  -------  -----
  first_commercial_sale   3          4            1        8
  launch_wave             3          1            0        4
  pricing_decision        3          1            4        8
  regulatory_approval     6          1            1        8
  reimbursement_decision  1          3            1        5
  salesforce_readiness    1          1            0        2
  total                   17         11           7        35
  18 milestones not completed yet (10 by date shown)
  product    market          type                    date        status
  ---------  --------------  ----------------------  ----------  -----------
  Kerendia   Finland         pricing_decision        2025-01-07  in_progress
  Lynkuet    Italy           first_commercial_sale   2025-02-17  in_progress
  Lynkuet    United States   first_commercial_sale   2025-04-08  in_progress
  Hyrnuo     Finland         regulatory_approval     2025-04-12  in_progress
  Hyrnuo     Spain           pricing_decision        2025-07-06  planned
  Beyonttra  United Kingdom  reimbursement_decision  2025-08-27  in_progress
  Beyonttra  United States   salesforce_readiness    2025-09-21  in_progress
  Nubeqa     Finland         pricing_decision        2025-11-28  planned
  Nubeqa     Japan           reimbursement_decision  2026-01-05  in_progress
  Hyrnuo     Australia       first_commercial_sale   2026-04-17  in_progress

==========================================================================
10. KPI GROUNDING (METADATA vs CONTEXT DATA)
==========================================================================

-- Canonical metrics mapped to context-sheet columns
  canonical_metric               kpi_variants  backed_by                                                                               status
  -----------------------------  ------------  --------------------------------------------------------------------------------------  ------------
  Budget Variance                3             -                                                                                       not grounded
  Certified Asset Share          3             -                                                                                       not grounded
  Commercial Reach Index         3             -                                                                                       not grounded
  Demand Forecast Accuracy       4             Supply_Operations.forecast_accuracy_pct_syn                                             grounded
  Demand Forecast Bias           4             derived: Product_Market_Monthly forecast vs net sales                                   derived
  Digital Engagement Index       2             -                                                                                       not grounded
  Forecast Variance              4             Product_Market_Monthly.forecast_variance_pct                                            grounded
  Gross-to-Net Rate              3             -                                                                                       not grounded
  Inventory Coverage             4             Product_Market_Monthly.inventory_weeks_syn / Supply_Operations.inventory_weeks_syn      grounded
  Launch Adoption Index          4             derived: Launch_Milestones.first_commercial_sale + Product_Market_Monthly.net_sales     derived
  Market Access Coverage         4             Market_Access.coverage_pct_syn / Product_Market_Monthly.market_access_coverage_pct_syn  grounded
  Net Sales                      3             Product_Market_Monthly.net_sales_m_eur_syn                                              grounded
  Net Sales Growth               2             derived: Product_Market_Monthly.net_sales_m_eur_syn MoM                                 derived
  On-Time In-Full                3             Product_Market_Monthly.otif_pct_syn / Supply_Operations.otif_pct_syn                    grounded
  Operating Contribution         2             -                                                                                       not grounded
  Reimbursement Status Coverage  3             Market_Access.reimbursement_status                                                      grounded
  Report Adoption                3             -                                                                                       not grounded
  Units Shipped                  2             Product_Market_Monthly.units_shipped_syn                                                grounded
  8 grounded, 3 derivable, 7 not grounded (of 18 canonical metrics)

-- Ungrounded metrics and the assets that depend on them
  ungrounded_metric         assets_using
  ------------------------  ------------
  Budget Variance           86
  Certified Asset Share     74
  Report Adoption           68
  Gross-to-Net Rate         68
  Operating Contribution    63
  Commercial Reach Index    59
  Digital Engagement Index  49
  14 assets reference ONLY ungrounded canonical metrics

==========================================================================
11. REQUEST TRIAGE (BUILD-LESS CHECK)
==========================================================================

-- Per-template triage

  [replace/migrate] x22: Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook.
   scope: products=Xarelto; markets=AU, BR, CA, CN, DE, ES, FI, FR, IT, JP, MX, SE, UK, US
   metrics: (none named)
   domains: Commercial
   covering active assets: 30
     AST-0067  Xarelto Budget New  [Power BI | none | healthy]  views=12537
     AST-0217  Xarelto Supply - US  [Power BI | none | healthy]  views=11740
     AST-0030  Xarelto Budget Copy  [Power BI | certified | healthy]  views=3038
   verdict: CONSOLIDATE FIRST (30 overlapping assets)

  [new build] x20: Can we have a new finance dashboard for net sales, gross-to-net and budget variance by product?
   scope: products=All Pharma, Beyonttra, Eylea, Hyrnuo, Kerendia, Lynkuet, Nubeqa, Xarelto; markets=AU, BR, CA, CN, DE, FI, IT, JP, MX, SE, UK
   metrics: Net Sales (grounded), Gross-to-Net Rate (not grounded), Budget Variance (not grounded)
   domains: Finance, Commercial
   covering active assets: 143
     AST-0220  Xarelto Net Sales Final  [Tableau | certified | healthy]  views=12641
     AST-0287  All Pharma Executive Legacy  [Power BI | promoted | healthy]  views=12603
     AST-0075  Hyrnuo Net Sales Final  [Power BI | promoted | healthy]  views=11888
   verdict: CONSOLIDATE FIRST (143 overlapping assets)  (data gap: Gross-to-Net Rate, Budget Variance)

  [new build] x17: Can we build a launch dashboard for Lynkuet with market access, first sales and adoption indicators?
   scope: products=Lynkuet; markets=BR, CA, CN, DE, FR, JP, MX, SE, UK
   metrics: Market Access Coverage (grounded), Launch Adoption Index (derived)
   domains: Market Access, Launch Excellence
   covering active assets: 19
     AST-0287  All Pharma Executive Legacy  [Power BI | promoted | healthy]  views=12603
     AST-0353  All Pharma Market Access Final  [Tableau | promoted | healthy]  views=11581
     AST-0133  All Pharma Supply  [Power BI | none | healthy]  views=12497
   verdict: CONSOLIDATE FIRST (19 overlapping assets)

  [new build] x16: Please build a new report for market access coverage and reimbursement status by product.
   scope: products=All Pharma, Beyonttra, Eylea, Hyrnuo, Kerendia, Lynkuet, Nubeqa, Xarelto; markets=BR, CA, CN, DE, FI, IT, JP, MX, SE, UK, US
   metrics: Market Access Coverage (grounded), Reimbursement Status Coverage (grounded)
   domains: Market Access
   covering active assets: 71
     AST-0220  Xarelto Net Sales Final  [Tableau | certified | healthy]  views=12641
     AST-0287  All Pharma Executive Legacy  [Power BI | promoted | healthy]  views=12603
     AST-0064  Eylea Market Access New  [Power BI | promoted | healthy]  views=12071
   verdict: CONSOLIDATE FIRST (71 overlapping assets)

  [other] x16: I need a dashboard comparing product performance across oncology brands and markets.
   scope: products=Nubeqa, Hyrnuo; markets=AU, BR, CA, CN, DE, ES, FI, FR, IT, JP, SE, UK, US
   metrics: (none named)
   domains: Commercial
   covering active assets: 51
     AST-0316  Nubeqa Gross-to-Net Copy  [Power BI | none | healthy]  views=13379
     AST-0091  Hyrnuo Growth - US  [Power BI | certified | warning]  views=13035
     AST-0158  Hyrnuo Portfolio Final  [Power BI | none | healthy]  views=11915
   verdict: CONSOLIDATE FIRST (51 overlapping assets)

  [consolidate] x14: We need one executive view combining net sales, forecast accuracy and inventory coverage for Bayer Pharma.
   scope: products=All Pharma, Beyonttra, Kerendia, Lynkuet, Nubeqa, Xarelto; markets=AU, BR, CA, CN, DE, ES, FI, FR, IT, JP, MX, SE, UK, US
   metrics: Net Sales (grounded), Demand Forecast Accuracy (grounded), Inventory Coverage (grounded)
   domains: Supply Chain, Finance, Commercial
   covering active assets: 141
     AST-0220  Xarelto Net Sales Final  [Tableau | certified | healthy]  views=12641
     AST-0287  All Pharma Executive Legacy  [Power BI | promoted | healthy]  views=12603
     AST-0353  All Pharma Market Access Final  [Tableau | promoted | healthy]  views=11581
   verdict: CONSOLIDATE FIRST (141 overlapping assets)

  [new build] x14: I need a new Kerendia management report for monthly performance in EMEA and North America.
   scope: products=Kerendia; markets=CA, DE, ES, FI, FR, IT, SE, UK, US
   metrics: (none named)
   domains: Commercial
   covering active assets: 20
     AST-0164  Kerendia Gross-to-Net New  [Power BI | promoted | healthy]  views=2601
     AST-0106  All Pharma Budget Copy  [Tableau | none | healthy]  views=2974
     AST-0038  All Pharma Commercial Reach v2  [Tableau | none | healthy]  views=2934
   verdict: CONSOLIDATE FIRST (20 overlapping assets)

  [new build] x13: Can you create a country-level Beyonttra report for launch readiness and reimbursement progress?
   scope: products=Beyonttra; markets=AU, BR, CA, CN, DE, ES, FI, FR, IT, JP, MX, SE, UK, US
   metrics: Reimbursement Status Coverage (grounded)
   domains: Market Access, Launch Excellence
   covering active assets: 35
     AST-0287  All Pharma Executive Legacy  [Power BI | promoted | healthy]  views=12603
     AST-0353  All Pharma Market Access Final  [Tableau | promoted | healthy]  views=11581
     AST-0133  All Pharma Supply  [Power BI | none | healthy]  views=12497
   verdict: CONSOLIDATE FIRST (35 overlapping assets)

  [other] x9: We need a monthly supply-risk dashboard by medicine and country.
   scope: products=All Pharma, Eylea, Kerendia, Lynkuet, Xarelto; markets=BR, CA, CN, DE, FR, JP, MX
   metrics: (none named)
   domains: Supply Chain
   covering active assets: 42
     AST-0133  All Pharma Supply  [Power BI | none | healthy]  views=12497
     AST-0149  Eylea Budget New  [Tableau | none | healthy]  views=12001
     AST-0217  Xarelto Supply - US  [Power BI | none | healthy]  views=11740
   verdict: CONSOLIDATE FIRST (42 overlapping assets)

  [new build] x9: Create a global Nubeqa dashboard showing sales growth, forecast variance and market access by country.
   scope: products=Nubeqa; markets=AU, BR, CA, CN, DE, ES, FI, FR, IT, JP, MX, SE, UK, US
   metrics: Net Sales Growth (derived), Forecast Variance (grounded), Market Access Coverage (grounded)
   domains: Market Access, Finance, Commercial
   covering active assets: 52
     AST-0287  All Pharma Executive Legacy  [Power BI | promoted | healthy]  views=12603
     AST-0353  All Pharma Market Access Final  [Tableau | promoted | healthy]  views=11581
     AST-0316  Nubeqa Gross-to-Net Copy  [Power BI | none | healthy]  views=13379
   verdict: CONSOLIDATE FIRST (52 overlapping assets)

-- Triage summary
  intent           requests  covering_assets  verdict
  ---------------  --------  ---------------  ------------------------------------------
  replace/migrate  22        30               CONSOLIDATE FIRST (30 overlapping assets)
  new build        20        143              CONSOLIDATE FIRST (143 overlapping assets)
  new build        17        19               CONSOLIDATE FIRST (19 overlapping assets)
  new build        16        71               CONSOLIDATE FIRST (71 overlapping assets)
  other            16        51               CONSOLIDATE FIRST (51 overlapping assets)
  consolidate      14        141              CONSOLIDATE FIRST (141 overlapping assets)
  new build        14        20               CONSOLIDATE FIRST (20 overlapping assets)
  new build        13        35               CONSOLIDATE FIRST (35 overlapping assets)
  other            9         42               CONSOLIDATE FIRST (42 overlapping assets)
  new build        9         52               CONSOLIDATE FIRST (52 overlapping assets)
  10/10 templates have active assets already covering the requested scope
  89 of 89 new-build requests already covered — candidates for reuse instead of new build

==========================================================================
KEY FINDINGS
==========================================================================
  - Sprawl: 3 scope-groups hold 6 assets; 60 product-market scopes served on both platforms; 84 assets share 40 duplicate names
  - Waste: 29 active assets with bottom-decile usage; 0 active assets with usage collapsing vs prior months
  - Retirement risk: 17 legacy/retire-candidate assets still in top usage decile
  - KPI governance: 18 canonical metrics have conflicting variants; 349 assets reference unapproved KPIs; 15 asset/metric pairs mix variants
  - Lineage: 14 failed-refresh models affect 69 downstream assets; 1 orphan models; 56 embedded asset links
  - Ownership: 21 assets missing owner; 152 high-reach unendorsed assets
  - Migration: 94 backlog items; 12 duplicate targets; 4 migrate-items near-zero usage; 2 retire-items top-decile usage
  - Requests: 150 requests from 10 templates; intent mix {'replace/migrate': 22, 'new build': 89, 'other': 25, 'consolidate': 14}
  - KPI grounding: 8 grounded + 3 derived vs 7 ungrounded canonical metrics; 14 assets depend only on ungrounded metrics
  - Build less: 89 of 89 new-build requests already covered by active assets; 10/10 templates have reuse candidates

Findings written to /c/Users/miska.aaltonen/sinceai/findings.json
