#!/usr/bin/env bash
# Local deploy: bootstrap (once) + main stack. CI does the same on every push to main.
#   NOTIFICATION_EMAIL=you@example.com GITHUB_REPO=owner/repo ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-south-1}"
: "${NOTIFICATION_EMAIL:?set NOTIFICATION_EMAIL (SES sender / demo mailbox)}"
GITHUB_REPO="${GITHUB_REPO:-$(git remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')}"

echo "==> Bootstrap (state bucket + GitHub OIDC roles) for $GITHUB_REPO"
CREATE_OIDC=true
if aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text | grep -q token.actions.githubusercontent.com; then
  CREATE_OIDC=false
fi
terraform -chdir=infra/bootstrap init -input=false >/dev/null
terraform -chdir=infra/bootstrap apply -auto-approve -input=false \
  -var "region=$REGION" -var "github_repo=$GITHUB_REPO" -var "create_oidc_provider=$CREATE_OIDC"
STATE_BUCKET=$(terraform -chdir=infra/bootstrap output -raw state_bucket)

echo "==> Build Lambda layer (pg8000 + RDS CA bundle)"
./scripts/build.sh

echo "==> Main stack"
terraform -chdir=infra init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET" -backend-config="key=examhub/prod.tfstate" \
  -backend-config="region=$REGION" -backend-config="use_lockfile=true"
TF_VAR_notification_email="$NOTIFICATION_EMAIL" terraform -chdir=infra apply -input=false "$@"

DIST_ID=$(terraform -chdir=infra output -raw cloudfront_distribution_id)
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" >/dev/null

echo
echo "Site:        $(terraform -chdir=infra output -raw site_url)"
echo "Health:      $(terraform -chdir=infra output -raw api_health_url)?deep=1"
echo "Credentials: terraform -chdir=infra output -json demo_credentials"
echo
echo "GitHub settings for CI/CD (Settings > Secrets and variables > Actions):"
echo "  variable AWS_DEPLOY_ROLE_ARN = $(terraform -chdir=infra/bootstrap output -raw deploy_role_arn)"
echo "  variable AWS_PLAN_ROLE_ARN   = $(terraform -chdir=infra/bootstrap output -raw plan_role_arn)"
echo "  variable TF_STATE_BUCKET     = $STATE_BUCKET"
echo "  secret   NOTIFICATION_EMAIL  = $NOTIFICATION_EMAIL"
