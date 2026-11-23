#!/usr/bin/env bash
# Tear everything down. Pass --all to also delete the bootstrap (state bucket + CI roles).
#   NOTIFICATION_EMAIL=you@example.com ./scripts/destroy.sh [--all]
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-south-1}"
: "${NOTIFICATION_EMAIL:?set NOTIFICATION_EMAIL (same value used to deploy)}"
STATE_BUCKET=$(terraform -chdir=infra/bootstrap output -raw state_bucket)

./scripts/build.sh >/dev/null # terraform reads the layer folder even when destroying
terraform -chdir=infra init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET" -backend-config="key=examhub/prod.tfstate" \
  -backend-config="region=$REGION" -backend-config="use_lockfile=true" >/dev/null
TF_VAR_notification_email="$NOTIFICATION_EMAIL" terraform -chdir=infra destroy -input=false

if [[ "${1:-}" == "--all" ]]; then
  GITHUB_REPO="${GITHUB_REPO:-$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')}"
  CREATE_OIDC=$(terraform -chdir=infra/bootstrap state list | grep -q 'aws_iam_openid_connect_provider.github\[0\]' && echo true || echo false)
  terraform -chdir=infra/bootstrap destroy -input=false \
    -var "region=$REGION" -var "github_repo=$GITHUB_REPO" -var "create_oidc_provider=$CREATE_OIDC"
fi

echo "Done. Check the AWS Billing console the next day to confirm nothing is still charging."
