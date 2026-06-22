#!/usr/bin/env bash
# Bring up the GE Search Portal end to end.
#   infra : terraform apply (APIs, bucket, Firestore, VAIS data store, SAs, IAM,
#           Cloud Run service [IAP on] + ingest job)
#   build : Cloud Build -> image -> deploy service + job
#   data  : execute the ingest Cloud Run job (corpus -> import -> ACLs)
#
# Usage:
#   bash deploy-all.sh PROJECT_ID [REGION] [--steps infra,build,data]
set -euo pipefail
cd "$(dirname "$0")"

PROJECT_ID="${1:?usage: bash deploy-all.sh PROJECT_ID [REGION] [--steps infra,build,data]}"
shift || true
REGION="us-central1"
STEPS="infra,build,data"
while [ $# -gt 0 ]; do
  case "$1" in
    --steps) STEPS="$2"; shift 2;;
    *)       REGION="$1"; shift;;
  esac
done
has() { case ",${STEPS}," in *",$1,"*) return 0;; *) return 1;; esac; }

TFSTATE="${PROJECT_ID}-tfstate"
BUILD_SA="ge-search-build@${PROJECT_ID}.iam.gserviceaccount.com"

if has infra; then
  echo "== [infra] terraform =="
  # Bootstrap APIs Terraform itself needs (data sources + service enablement).
  # Wait for propagation so the first apply doesn't 403 on a fresh project.
  gcloud services enable cloudresourcemanager.googleapis.com serviceusage.googleapis.com \
    --project "${PROJECT_ID}"
  sleep 30
  gcloud storage buckets describe "gs://${TFSTATE}" --project "${PROJECT_ID}" >/dev/null 2>&1 \
    || gcloud storage buckets create "gs://${TFSTATE}" --project "${PROJECT_ID}" --location "${REGION}"
  # IAP access: if the operator hasn't supplied terraform.tfvars, auto-grant the deploying
  # gcloud user so they can open the site out of the box. With a tfvars present, that file
  # wins (set iap_members there to add a group/domain).
  IAP_VAR=()
  if [ ! -f terraform/terraform.tfvars ]; then
    ME="$(gcloud config get-value account 2>/dev/null || true)"
    if [ -n "${ME}" ]; then
      echo "   no terraform.tfvars — granting IAP access to ${ME} (edit terraform.tfvars to add a group/domain)"
      IAP_VAR=(-var="iap_members=[\"user:${ME}\"]")
    fi
  fi
  ( cd terraform
    terraform init -input=false -backend-config="bucket=${TFSTATE}"
    # The "(default)" Firestore DB can't be created twice. If the project already has one
    # (e.g. from a prior install or App Engine) and it isn't in state, import it so apply
    # doesn't fail trying to re-create it.
    if ! terraform state list 2>/dev/null | grep -q '^google_firestore_database.default$'; then
      if gcloud firestore databases describe --database='(default)' --project "${PROJECT_ID}" >/dev/null 2>&1; then
        echo "   importing existing (default) Firestore database into state"
        terraform import -input=false \
          -var="project_id=${PROJECT_ID}" -var="region=${REGION}" \
          google_firestore_database.default "${PROJECT_ID}/(default)" || true
      fi
    fi
    terraform apply -auto-approve -input=false \
      -var="project_id=${PROJECT_ID}" -var="region=${REGION}" ${IAP_VAR[@]+"${IAP_VAR[@]}"} )
fi

if has build; then
  echo "== [build] cloud build -> image -> deploy =="
  # caller must be able to actAs the build SA
  ME="$(gcloud config get-value account 2>/dev/null || true)"
  [ -n "${ME}" ] && gcloud iam service-accounts add-iam-policy-binding "${BUILD_SA}" \
    --project "${PROJECT_ID}" --member "user:${ME}" \
    --role roles/iam.serviceAccountUser --quiet >/dev/null || true
  gcloud builds submit . --project "${PROJECT_ID}" --config cloudbuild.yaml \
    --substitutions=_REGION="${REGION}" \
    --service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA}"
fi

if has data; then
  echo "== [data] run ingest job =="
  gcloud run jobs execute ge-search-ingest --region "${REGION}" --project "${PROJECT_ID}" --wait
fi

echo
echo "Service URL (access via IAP):"
( cd terraform && terraform output -raw service_uri 2>/dev/null || echo "  (run the infra step)" )
