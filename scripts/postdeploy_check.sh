#!/usr/bin/env bash
# Post-deployment smoke check for the GE Search Portal.
#   1. Cloud Run service Ready + serving the latest revision
#   2. Public URL gated by IAP (expects 302 redirect to login)
#   3. Eval suite: retrieval relevance + per-persona security trim (live VAIS+Firestore)
#   4. No ERROR logs on the serving revision
#
# Usage: bash scripts/postdeploy_check.sh PROJECT_ID [REGION]
set -uo pipefail
cd "$(dirname "$0")/.."
P="${1:?usage: postdeploy_check.sh PROJECT_ID [REGION]}"
R="${2:-us-central1}"
SVC=ge-search-portal
fail=0

echo "== 1. Cloud Run service =="
read -r REV PCT URL < <(gcloud run services describe $SVC --region "$R" --project "$P" \
  --format="value(status.traffic[0].revisionName,status.traffic[0].percent,status.url)" 2>/dev/null)
echo "   revision=$REV traffic=${PCT}% url=$URL"
[ "${PCT:-0}" = "100" ] && echo "   ✓ serving" || { echo "   ✗ not at 100%"; fail=1; }

echo "== 2. IAP gate (expect 302) =="
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$URL/")
[ "$code" = "302" ] && echo "   ✓ HTTP $code (IAP up)" || { echo "   ✗ HTTP $code"; fail=1; }

echo "== 3. Eval suite =="
PROJECT_ID="$P" LOCATION="${LOCATION:-global}" DATA_STORE_ID="${DATA_STORE_ID:-ge-search-demo}" \
  FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-(default)}" python3 scripts/de_eval.py
[ $? -eq 0 ] && echo "   ✓ eval passed" || { echo "   ✗ eval failed"; fail=1; }

echo "== 4. Error logs on $REV (last 15m) =="
errs=$(gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$SVC AND resource.labels.revision_name=$REV AND severity>=ERROR" \
  --project "$P" --limit 5 --freshness=15m --format="value(textPayload)" 2>/dev/null | grep -cvE "^$")
[ "${errs:-0}" -eq 0 ] && echo "   ✓ no errors" || { echo "   ✗ $errs error log lines"; fail=1; }

echo "------------------------------------------------------------"
[ "$fail" -eq 0 ] && echo "POST-DEPLOY CHECK: PASS" || echo "POST-DEPLOY CHECK: FAIL"
echo "(For the IAP'd endpoints, reload $URL in a browser as an authorized user.)"
exit $fail
