#!/usr/bin/env bash
# Provision a Gemini Enterprise FREE-TRIAL subscription so the GE engine's assistant
# (:streamAssist) serves in this project — required once per project; without an ACTIVE
# licenseConfig, assist calls fail with "User must be assigned a license".
#
# What it does (verified flow, idempotent):
#   1. creates a 30-day free-trial licenseConfig (SEARCH_AND_ASSISTANT tier)
#      - licenseConfigs.create is only permitted for free trials; PAID tiers are bought
#        through Cloud Billing / the Gemini Enterprise console instead
#      - startDate must be a future date, but the config activates immediately
#   2. sets it as the default_user_store's default + enables seat auto-register
#      (human users get a seat on first sign-in; the app's service account is covered
#      by the project subscription and needs no seat)
#   3. optionally pre-assigns a seat: pass an email as the 2nd arg
#
# Prereqs: the GE engine must already exist (run the deploy's infra step first — the
# user store is created with the engine), and the caller needs discoveryengine admin.
#
# Usage: bash scripts/setup_ge_license.sh PROJECT_ID [user@example.com]
set -euo pipefail
P="${1:?usage: setup_ge_license.sh PROJECT_ID [seat-user-email]}"
SEAT="${2:-}"
SEATS="${LICENSE_COUNT:-50}"
API="https://discoveryengine.googleapis.com/v1alpha/projects/${P}/locations/global"
TOKEN="$(gcloud auth print-access-token)"

req() { # METHOD URL [JSON]
  curl -sS -X "$1" -H "Authorization: Bearer ${TOKEN}" -H "x-goog-user-project: ${P}" \
    -H "Content-Type: application/json" "${2}" ${3:+-d "$3"}
}

echo "== 1/3 licenseConfig (free trial, ${SEATS} seats) =="
if req GET "${API}/licenseConfigs" | grep -q '"name"'; then
  echo "   a licenseConfig already exists — leaving it untouched:"
  req GET "${API}/licenseConfigs" | grep -E '"name"|"state"|"endDate"' | head -6
else
  START=$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d '+1 day' +%Y-%m-%d)  # macOS | GNU
  Y=${START:0:4}; M=$((10#${START:5:2})); D=$((10#${START:8:2}))
  OUT=$(req POST "${API}/licenseConfigs?licenseConfigId=free_trial_gemini" "{
    \"licenseCount\": \"${SEATS}\",
    \"subscriptionTier\": \"SUBSCRIPTION_TIER_SEARCH_AND_ASSISTANT\",
    \"subscriptionTerm\": \"SUBSCRIPTION_TERM_ONE_MONTH\",
    \"freeTrial\": true,
    \"startDate\": {\"year\": ${Y}, \"month\": ${M}, \"day\": ${D}}
  }")
  echo "${OUT}" | grep -qE '"state": *"ACTIVE"' \
    && echo "   created free_trial_gemini — ACTIVE" \
    || { echo "${OUT}"; echo "   FAILED — is the engine deployed yet (infra step)?"; exit 1; }
fi

echo "== 2/3 user store default + auto-register =="
req PATCH "${API}/userStores/default_user_store?updateMask=defaultLicenseConfig,enableLicenseAutoRegister" "{
  \"defaultLicenseConfig\": \"projects/${P}/locations/global/licenseConfigs/free_trial_gemini\",
  \"enableLicenseAutoRegister\": true
}" > /dev/null && echo "   default_user_store -> free_trial_gemini (auto-register on)"

if [ -n "${SEAT}" ]; then
  echo "== 3/3 assign seat: ${SEAT} =="
  req POST "${API}/userStores/default_user_store:batchUpdateUserLicenses" "{
    \"inlineSource\": {
      \"userLicenses\": [{\"userPrincipal\": \"${SEAT}\",
        \"licenseConfig\": \"projects/${P}/locations/global/licenseConfigs/free_trial_gemini\"}],
      \"updateMask\": \"licenseConfig\"
    }
  }" | grep -q ASSIGNED && echo "   ${SEAT} ASSIGNED"
else
  echo "== 3/3 no seat email passed — users auto-register on first sign-in =="
fi

echo
echo "Done. Trial expires in ~1 month — check state with:"
echo "  curl -s -H \"Authorization: Bearer \$(gcloud auth print-access-token)\" -H \"x-goog-user-project: ${P}\" ${API}/licenseConfigs"
