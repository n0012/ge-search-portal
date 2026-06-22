-- GE Search Portal — log analytics (BigQuery dataset: ge_search_logs)
--
-- Tables:
--   searches      one row per /api/search        (search_id, user, query, groups[], filters, result_count, result_doc_ids[])
--   ai_turns      one row per AI generation       (search_id, feature answer|ask|doc_qa, query, question, document_id,
--                                                  model_requested, model_used, used_search, result_count, latency_ms)
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


-- 2) Model mix + failover: what was requested vs what actually ran ------------------
--    (model_requested = "" means the UI default; model_used differs on overflow failover)
SELECT
  feature,
  model_requested,
  model_used,
  COUNT(*) AS turns,
  COUNTIF(model_requested != "" AND model_requested != model_used) AS failovers
FROM `ge_search_logs.ai_turns`
GROUP BY feature, model_requested, model_used
ORDER BY turns DESC;


-- 3) Web search adoption: how often Google Search grounding was used, by feature ----
SELECT
  feature,
  COUNT(*)                                  AS turns,
  COUNTIF(used_search)                      AS web_search_turns,
  ROUND(COUNTIF(used_search) / COUNT(*), 3) AS web_search_rate
FROM `ge_search_logs.ai_turns`
GROUP BY feature
ORDER BY turns DESC;


-- 4) Latency by feature + model (p50 / p95 / max, ms) ------------------------------
SELECT
  feature,
  model_used,
  COUNT(*)                                                       AS turns,
  CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(50)] AS INT64)   AS p50_ms,
  CAST(APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS INT64)   AS p95_ms,
  MAX(latency_ms)                                                AS max_ms
FROM `ge_search_logs.ai_turns`
GROUP BY feature, model_used
ORDER BY turns DESC;


-- 5) Search → AI follow-ups, correlated by search_id -------------------------------
SELECT
  s.event_time,
  s.user,
  s.query,
  ARRAY_AGG(STRUCT(t.feature, t.model_used, t.used_search, t.latency_ms)
            ORDER BY t.event_time) AS ai_turns
FROM `ge_search_logs.searches` s
JOIN `ge_search_logs.ai_turns` t USING (search_id)
GROUP BY s.event_time, s.user, s.query
ORDER BY s.event_time DESC
LIMIT 50;


-- 6) AI usage by persona / group ---------------------------------------------------
SELECT
  t.user,
  g AS group_id,
  COUNT(*)             AS ai_turns,
  COUNTIF(used_search) AS web_search_turns
FROM `ge_search_logs.ai_turns` t, UNNEST(t.`groups`) AS g
GROUP BY t.user, group_id
ORDER BY ai_turns DESC;


-- 7) Feedback funnel: votes tied back to their search + query ----------------------
SELECT
  f.vote,
  COUNT(*) AS votes,
  COUNT(DISTINCT f.search_id) AS distinct_searches
FROM `ge_search_logs.feedback` f
GROUP BY f.vote
ORDER BY votes DESC;


-- 8) Top queries that drive AI follow-ups ------------------------------------------
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


-- 9) Ingestion health: per-stage status counts (initial load + incremental) --------
SELECT stage, status, COUNT(*) AS docs, SUM(bytes) AS bytes
FROM `ge_search_logs.ingestion_log`
WHERE event_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY stage, status
ORDER BY stage, docs DESC;
