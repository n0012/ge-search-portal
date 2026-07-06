-- GE Search Portal — log analytics (BigQuery dataset: ge_search_logs)
--
-- Tables:
--   searches      one row per /api/search        (search_id, user, query, groups[], filters, result_count, result_doc_ids[])
--   ai_turns      one row per AI generation       (search_id, feature answer|ask|doc_qa, query, question, document_id,
--                                                  model_used [always "ge-assist" — the GE engine assistant],
--                                                  result_count, latency_ms; model_requested/used_search are legacy
--                                                  columns from the removed direct-Gemini path, now constant)
--   feedback      one row per thumbs up/down      (search_id, user, query, document_id, title, vote)
--   ingestion_log one row per doc lifecycle event (task, source, document_id, stage, status, bytes, error)
--
-- `search_id` is the join key tying an AI turn / feedback back to the search that produced
-- the result set. Run with your project set, e.g.:
--   bq query --use_legacy_sql=false --project_id=YOUR_PROJECT_ID '<query>'
-- Reserved words (user, groups, rows) must be back-ticked.


-- 1) AI-usage funnel: how often a search leads to an AI answer/ask -----------------
SELECT
  COUNT(DISTINCT s.search_id)                                   AS searches,
  COUNT(DISTINCT t.search_id)                                   AS searches_with_ai,
  ROUND(COUNT(DISTINCT t.search_id) / COUNT(DISTINCT s.search_id), 3) AS ai_attach_rate
FROM `ge_search_logs.searches` s
LEFT JOIN `ge_search_logs.ai_turns` t USING (search_id)
WHERE s.event_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY);


-- 2) AI feature mix: which AI surfaces get used --------------------------------------
--    (all answers come from the GE engine assistant — no model picker / failover)
SELECT
  feature,
  COUNT(*)                     AS turns,
  COUNT(DISTINCT search_id)    AS distinct_searches,
  ROUND(AVG(result_count), 1)  AS avg_docs_in_scope
FROM `ge_search_logs.ai_turns`
GROUP BY feature
ORDER BY turns DESC;


-- 3) Latency by AI feature (p50 / p95 / max, ms) ------------------------------------
SELECT
  feature,
  COUNT(*)                                                       AS turns,
  CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(50)] AS INT64)   AS p50_ms,
  CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS INT64)   AS p95_ms,
  MAX(latency_ms)                                                AS max_ms
FROM `ge_search_logs.ai_turns`
GROUP BY feature
ORDER BY turns DESC;


-- 4) Search → AI follow-ups, correlated by search_id -------------------------------
SELECT
  s.event_time,
  s.user,
  s.query,
  ARRAY_AGG(STRUCT(t.feature, t.latency_ms)
            ORDER BY t.event_time) AS ai_turns
FROM `ge_search_logs.searches` s
JOIN `ge_search_logs.ai_turns` t USING (search_id)
GROUP BY s.event_time, s.user, s.query
ORDER BY s.event_time DESC
LIMIT 50;


-- 5) AI usage by persona / group ---------------------------------------------------
SELECT
  t.user,
  g AS group_id,
  COUNT(*) AS ai_turns
FROM `ge_search_logs.ai_turns` t, UNNEST(t.`groups`) AS g
GROUP BY t.user, group_id
ORDER BY ai_turns DESC;


-- 6) Feedback funnel: votes tied back to their search + query ----------------------
SELECT
  f.vote,
  COUNT(*) AS votes,
  COUNT(DISTINCT f.search_id) AS distinct_searches
FROM `ge_search_logs.feedback` f
GROUP BY f.vote
ORDER BY votes DESC;


-- 7) Top queries that drive AI follow-ups ------------------------------------------
SELECT
  s.query,
  COUNT(DISTINCT s.search_id) AS searches,
  COUNT(t.search_id)          AS ai_turns
FROM `ge_search_logs.searches` s
LEFT JOIN `ge_search_logs.ai_turns` t USING (search_id)
GROUP BY s.query
HAVING ai_turns > 0
ORDER BY ai_turns DESC
LIMIT 25;


-- 8) Ingestion health: per-stage status counts (initial load + incremental) --------
SELECT stage, status, COUNT(*) AS docs, SUM(bytes) AS bytes
FROM `ge_search_logs.ingestion_log`
WHERE event_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY stage, status
ORDER BY stage, docs DESC;


-- ==================================================================================
-- Reranker cost tracking (only when RERANK=on — the standalone Ranking API, billed
-- outside the GE subscription). Requires the optional exports:
--   --billing-export  → dataset billing_export  (actual $ per SKU)
--   --logging-export  → dataset ge_search_app_logs (call volume, the cost driver)
-- ==================================================================================

-- 9) Reranker + subscription-coverage spend, by day — actual cost from the billing export.
--    Two SKUs to watch (both under service "Vertex AI Search"):
--      EE89-3EE8-2541  "Vertex AI Search: Ranking"   = the reranker ($1/1,000, no free tier);
--                                                       nonzero ONLY when RERANK=on.
--      93D6-7280-CF05  "Search API Request Count - Enterprise" = standalone Enterprise search
--                                                       ($4/1,000); should be ~$0 because all
--                                                       search rides the GE subscription.
--    (BADA-EE26-7BDA is the Standard-tier search SKU, $1.50/1,000 — also expect ~$0.)
--    Table name is gcp_billing_export_resource_v1_<BILLING_ACCOUNT_ID> — set yours.
SELECT
  DATE(usage_start_time)                              AS day,
  sku.id                                              AS sku_id,
  sku.description                                     AS sku,
  ROUND(SUM(cost), 2)                                 AS cost,
  ANY_VALUE(currency)                                 AS currency
FROM `billing_export.gcp_billing_export_resource_v1_XXXXXX_XXXXXX_XXXXXX`
WHERE sku.id IN ('EE89-3EE8-2541', '93D6-7280-CF05', 'BADA-EE26-7BDA')  -- rerank + standalone search
  AND usage_start_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY day, sku_id, sku
ORDER BY day DESC, cost DESC;


-- 10) Reranker call VOLUME (the cost driver) — from the app's stdout logs export.
--     Each search that reranks logs one 'rerank ok: ...' line; count them per day so you
--     can correlate volume → the $ in query 9 and get an effective per-call rate.
SELECT
  DATE(timestamp)                                     AS day,
  COUNTIF(textPayload LIKE 'rerank ok:%')             AS rerank_calls,
  COUNTIF(textPayload LIKE 'rerank skipped:%')        AS rerank_skipped_or_failed
FROM `ge_search_app_logs.run_googleapis_com_stdout`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY day
ORDER BY day DESC;
