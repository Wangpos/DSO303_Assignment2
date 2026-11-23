#!/usr/bin/env bash
# Builds the Lambda layer: pure-Python dependencies from app/backend/requirements.txt
# plus the Amazon RDS CA bundle used to verify the database's TLS certificate.
# Run by deploy.sh and by the GitHub Actions pipeline before terraform plan/apply.
set -euo pipefail
cd "$(dirname "$0")/.."

LAYER=infra/build/layer
rm -rf "$LAYER"
mkdir -p "$LAYER/python"
python3 -m pip install --quiet --disable-pip-version-check --no-compile \
  --target "$LAYER/python" -r app/backend/requirements.txt
curl -fsSL https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o "$LAYER/rds-global-bundle.pem"
find "$LAYER" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "Lambda layer ready: $(du -sh "$LAYER" | cut -f1) in $LAYER"
