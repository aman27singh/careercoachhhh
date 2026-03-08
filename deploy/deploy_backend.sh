#!/usr/bin/env bash
# deploy/deploy_backend.sh
# ─────────────────────────────────────────────────────────────────────────────
# Build a Lambda deployment package from the CareerOS FastAPI app and push it
# to AWS Lambda via S3.
#
# Usage:
#   bash deploy/deploy_backend.sh [--function-name NAME] [--region REGION]
#
# Prerequisites:
#   • AWS CLI configured (aws configure or env vars AWS_ACCESS_KEY_ID / SECRET)
#   • Python venv at .venv/  (created by: python -m venv .venv && pip install -r requirements.txt)
#   • DEPLOY_BUCKET env var set — S3 bucket used to stage the zip
#     (same bucket works for both resume storage and deployment staging)
#
# Environment variables (with defaults):
#   AWS_REGION            us-east-1
#   LAMBDA_FUNCTION_NAME  careeros-api
#   DEPLOY_BUCKET         careeros-resumes-<aws_account_id>   (auto-detected)
#   PYTHON_CMD            .venv/bin/python
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
LAMBDA_NAME="${LAMBDA_FUNCTION_NAME:-careeros-api}"
PYTHON_CMD="${PYTHON_CMD:-.venv/bin/python}"
BUILD_DIR="$(pwd)/.lambda_build"
ZIP_PATH="$(pwd)/careeros_lambda.zip"

# Auto-detect deploy bucket if not set
if [[ -z "${DEPLOY_BUCKET:-}" ]]; then
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  DEPLOY_BUCKET="careeros-resumes-${ACCOUNT_ID}"
fi

echo "▶  Building Lambda package"
echo "   function : ${LAMBDA_NAME}"
echo "   region   : ${REGION}"
echo "   bucket   : ${DEPLOY_BUCKET}"
echo

# ── 1. Clean build directory ─────────────────────────────────────────────────
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# ── 2. Install Python dependencies into build dir ────────────────────────────
echo "[1/4] Installing dependencies …"
"${PYTHON_CMD}" -m pip install \
  --quiet \
  --target "${BUILD_DIR}" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --upgrade \
  --requirement requirements.txt \
  mangum \
  watchtower

# ── 3. Copy application code ──────────────────────────────────────────────────
echo "[2/4] Copying application source …"
cp -r app/       "${BUILD_DIR}/app/"
cp -r scripts/   "${BUILD_DIR}/scripts/" 2>/dev/null || true

# ── 4. Zip everything ─────────────────────────────────────────────────────────
echo "[3/4] Creating deployment zip …"
cd "${BUILD_DIR}"
zip -r "${ZIP_PATH}" . --quiet
cd - > /dev/null

ZIP_SIZE_MB="$(du -sh "${ZIP_PATH}" | cut -f1)"
echo "      Package size: ${ZIP_SIZE_MB}"

# ── 5. Upload zip to S3 ───────────────────────────────────────────────────────
S3_KEY="deployments/careeros_lambda_$(date +%Y%m%d_%H%M%S).zip"
echo "[4/4] Uploading to s3://${DEPLOY_BUCKET}/${S3_KEY} …"
aws s3 cp "${ZIP_PATH}" "s3://${DEPLOY_BUCKET}/${S3_KEY}" --region "${REGION}"

# Also update the 'latest' pointer
aws s3 cp "${ZIP_PATH}" "s3://${DEPLOY_BUCKET}/deployments/latest.zip" --region "${REGION}"

# ── 6. Update Lambda function code ───────────────────────────────────────────
echo "▶  Deploying to Lambda '${LAMBDA_NAME}' …"
aws lambda update-function-code \
  --function-name "${LAMBDA_NAME}" \
  --s3-bucket     "${DEPLOY_BUCKET}" \
  --s3-key        "deployments/latest.zip" \
  --region        "${REGION}" \
  --output        text \
  --query         "CodeSize"

# Wait for update to complete
echo "   Waiting for Lambda update to complete …"
aws lambda wait function-updated \
  --function-name "${LAMBDA_NAME}" \
  --region        "${REGION}"

# ── 7. Update handler + env vars ─────────────────────────────────────────────
# Build env vars string — always include base vars, append API keys if set locally
ENV_VARS="CAREEROS_RESUME_BUCKET=${DEPLOY_BUCKET},CAREEROS_CW_LOG_GROUP=/aws/lambda/${LAMBDA_NAME}"
[[ -n "${RAPIDAPI_KEY:-}"    ]] && ENV_VARS="${ENV_VARS},RAPIDAPI_KEY=${RAPIDAPI_KEY}"
[[ -n "${ADZUNA_APP_ID:-}"   ]] && ENV_VARS="${ENV_VARS},ADZUNA_APP_ID=${ADZUNA_APP_ID}"
[[ -n "${ADZUNA_APP_KEY:-}"  ]] && ENV_VARS="${ENV_VARS},ADZUNA_APP_KEY=${ADZUNA_APP_KEY}"
[[ -n "${OPENSEARCH_ENDPOINT:-}" ]] && ENV_VARS="${ENV_VARS},OPENSEARCH_ENDPOINT=${OPENSEARCH_ENDPOINT}"

aws lambda update-function-configuration \
  --function-name "${LAMBDA_NAME}" \
  --handler       "app.lambda_handler.handler" \
  --runtime       "python3.12" \
  --timeout       120 \
  --memory-size   512 \
  --environment   "Variables={${ENV_VARS}}" \
  --region "${REGION}" \
  --output text \
  --query "LastModified"

# ── 8. Publish a new version ──────────────────────────────────────────────────
VERSION="$(aws lambda publish-version \
  --function-name "${LAMBDA_NAME}" \
  --region        "${REGION}" \
  --query         "Version" \
  --output        text)"

echo
echo "✓ Lambda '${LAMBDA_NAME}' updated — version ${VERSION}"
echo "  Deployment zip: s3://${DEPLOY_BUCKET}/${S3_KEY}"
echo
echo "Next: run  bash deploy/deploy_frontend.sh  to update the frontend."

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
