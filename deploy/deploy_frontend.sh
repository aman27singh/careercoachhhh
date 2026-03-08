#!/usr/bin/env bash
# deploy/deploy_frontend.sh
# ─────────────────────────────────────────────────────────────────────────────
# Build the Vite/React frontend and deploy it to S3 + CloudFront.
#
# Usage:
#   bash deploy/deploy_frontend.sh [--bucket BUCKET] [--dist-id CF_DIST_ID]
#
# Prerequisites:
#   • Node.js ≥ 18 and npm installed
#   • AWS CLI configured
#   • S3 bucket configured for static website hosting (run setup_infra.py first)
#
# Environment variables (with defaults):
#   AWS_REGION              us-east-1
#   FRONTEND_BUCKET         careeros-frontend-<aws_account_id>   (auto-detected)
#   CF_DISTRIBUTION_ID      Auto-detected from CloudFront by bucket name if unset
#   VITE_API_URL            Backend API base URL injected into the build
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
FRONTEND_DIR="$(pwd)/frontend"

# ── Auto-detect account + bucket name ────────────────────────────────────────
if [[ -z "${FRONTEND_BUCKET:-}" ]]; then
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  FRONTEND_BUCKET="careeros-frontend-${ACCOUNT_ID}"
fi

echo "▶  Deploying CareerOS frontend"
echo "   bucket : ${FRONTEND_BUCKET}"
echo "   region : ${REGION}"
[[ -n "${VITE_API_URL:-}" ]] && echo "   api url: ${VITE_API_URL}"
echo

# ── 1. Install npm dependencies ───────────────────────────────────────────────
echo "[1/4] Installing npm dependencies …"
cd "${FRONTEND_DIR}"
npm ci --silent

# ── 2. Build Vite app ─────────────────────────────────────────────────────────
echo "[2/4] Building production bundle …"
if [[ -n "${VITE_API_URL:-}" ]]; then
  VITE_API_URL="${VITE_API_URL}" npm run build
else
  npm run build
fi

BUILD_SIZE="$(du -sh dist | cut -f1)"
echo "      Bundle size: ${BUILD_SIZE}"
cd - > /dev/null

# ── 3. Sync to S3 ─────────────────────────────────────────────────────────────
echo "[3/4] Syncing to s3://${FRONTEND_BUCKET} …"

# Long-lived cached assets (hashed filenames)
aws s3 sync "${FRONTEND_DIR}/dist/" "s3://${FRONTEND_BUCKET}/" \
  --region  "${REGION}" \
  --delete \
  --exclude "index.html" \
  --cache-control "public,max-age=31536000,immutable" \
  --quiet

# index.html — always revalidate
aws s3 cp "${FRONTEND_DIR}/dist/index.html" "s3://${FRONTEND_BUCKET}/index.html" \
  --region        "${REGION}" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type  "text/html" \
  --quiet

echo "      Sync complete"

# ── 4. CloudFront cache invalidation ─────────────────────────────────────────
if [[ -z "${CF_DISTRIBUTION_ID:-}" ]]; then
  echo "[4/4] Looking up CloudFront distribution ID …"
  CF_DISTRIBUTION_ID="$(
    aws cloudfront list-distributions \
      --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, '${FRONTEND_BUCKET}')].Id" \
      --output text 2>/dev/null || true
  )"
fi

if [[ -n "${CF_DISTRIBUTION_ID:-}" ]]; then
  echo "[4/4] Invalidating CloudFront cache (dist: ${CF_DISTRIBUTION_ID}) …"
  INVALIDATION_ID="$(
    aws cloudfront create-invalidation \
      --distribution-id "${CF_DISTRIBUTION_ID}" \
      --paths "/*" \
      --query "Invalidation.Id" \
      --output text
  )"
  echo "      Invalidation ${INVALIDATION_ID} submitted (propagation ~1 min)"

  # Get the CloudFront domain for the summary
  CF_DOMAIN="$(
    aws cloudfront get-distribution \
      --id "${CF_DISTRIBUTION_ID}" \
      --query "Distribution.DomainName" \
      --output text
  )"
  echo
  echo "✓ Frontend deployed"
  echo "  S3 bucket : s3://${FRONTEND_BUCKET}"
  echo "  CloudFront: https://${CF_DOMAIN}"
else
  echo "[4/4] No CloudFront distribution found — skipping invalidation"
  echo
  echo "✓ Frontend deployed to s3://${FRONTEND_BUCKET}"
  echo "  S3 website URL: http://${FRONTEND_BUCKET}.s3-website-${REGION}.amazonaws.com"
fi
