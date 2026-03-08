#!/usr/bin/env python3
"""Idempotent AWS infrastructure setup for CareerOS.

Creates / verifies all required AWS resources in the correct order.
Safe to re-run — every step checks for existence before creating.

Usage:
    AWS_REGION=us-east-1 python deploy/setup_infra.py [--dry-run]

Resources created
-----------------
1. S3 bucket — resume storage           (CAREEROS_RESUME_BUCKET)
2. S3 bucket — frontend static hosting  (CAREEROS_FRONTEND_BUCKET)
3. CloudFront distribution              — points at frontend bucket
4. IAM role — Lambda execution role     (careeros-lambda-role)
5. Lambda function                      (careeros-api)
6. API Gateway HTTP API (v2)            (careeros-api-gw)
7. CloudWatch log group                 (/aws/lambda/careeros-api)
8. CloudWatch alarms                    (5xx rate, p99 latency)

Environment variables
---------------------
AWS_REGION                  Required
AWS_ACCOUNT_ID              Optional — auto-detected from STS if omitted
CAREEROS_RESUME_BUCKET      default: careeros-resumes-<account_id>
CAREEROS_FRONTEND_BUCKET    default: careeros-frontend-<account_id>
CAREEROS_LAMBDA_NAME        default: careeros-api
CAREEROS_ALARM_EMAIL        SNS email for alarms (optional)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

REGION      = os.getenv("AWS_REGION", "us-east-1")
LAMBDA_NAME = os.getenv("CAREEROS_LAMBDA_NAME", "careeros-api")
CW_GROUP    = f"/aws/lambda/{LAMBDA_NAME}"

# ── helpers ────────────────────────────────────────────────────────────────────

def _account_id(sts) -> str:
    return sts.get_caller_identity()["Account"]


def _bucket_exists(s3, name: str) -> bool:
    try:
        s3.head_bucket(Bucket=name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            return False
        raise


def _create_s3_bucket(s3, name: str, public: bool = False) -> None:
    if _bucket_exists(s3, name):
        log.info("  S3 bucket '%s' already exists — skip", name)
        return
    kwargs: dict = {"Bucket": name}
    if REGION != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": REGION}
    s3.create_bucket(**kwargs)
    log.info("  Created S3 bucket '%s'", name)

    if not public:
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
    s3.put_bucket_versioning(
        Bucket=name,
        VersioningConfiguration={"Status": "Enabled"},
    )


def _setup_frontend_bucket(s3, name: str) -> None:
    """Create private frontend bucket (CloudFront OAC provides access)."""
    _create_s3_bucket(s3, name, public=False)  # stays private — OAC handles access
    log.info("  Frontend bucket '%s' ready (private, OAC access)", name)


def _get_or_create_iam_role(iam, account_id: str) -> str:
    """Return the ARN of the Lambda execution role, creating it if needed."""
    role_name = "careeros-lambda-role"
    try:
        arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
        log.info("  IAM role '%s' already exists — skip", role_name)
        return arn
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise

    trust = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    })
    role = iam.create_role(RoleName=role_name, AssumeRolePolicyDocument=trust)
    arn  = role["Role"]["Arn"]
    log.info("  Created IAM role '%s'", role_name)

    # Attach managed policies
    for policy_arn in [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonS3FullAccess",
        "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
    ]:
        iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
        log.info("    Attached %s", policy_arn.split("/")[-1])

    time.sleep(10)  # IAM propagation delay
    return arn


def _ensure_lambda(lam, role_arn: str, resume_bucket: str) -> str:
    """Create Lambda function stub if it doesn't exist. Returns function ARN."""
    try:
        arn = lam.get_function(FunctionName=LAMBDA_NAME)["Configuration"]["FunctionArn"]
        log.info("  Lambda '%s' already exists — skip creation", LAMBDA_NAME)
        # Update env vars
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Environment={"Variables": {
                "CAREEROS_RESUME_BUCKET":   resume_bucket,
                "CAREEROS_CW_LOG_GROUP":    CW_GROUP,
            }},
        )
        return arn
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    # Minimal stub zip (real code deployed by deploy_backend.sh)
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app/lambda_handler.py", "def handler(event, context): return {'statusCode': 200, 'body': 'stub'}")
    buf.seek(0)

    fn = lam.create_function(
        FunctionName=LAMBDA_NAME,
        Runtime="python3.12",
        Role=role_arn,
        Handler="app.lambda_handler.handler",
        Code={"ZipFile": buf.read()},
        Timeout=30,
        MemorySize=512,
        Environment={"Variables": {
            "CAREEROS_RESUME_BUCKET":   resume_bucket,
            "CAREEROS_CW_LOG_GROUP":    CW_GROUP,
        }},
    )
    arn = fn["FunctionArn"]
    log.info("  Created Lambda stub '%s'", LAMBDA_NAME)
    return arn


def _ensure_api_gateway(apigw, lambda_arn: str, account_id: str) -> str:
    """Create an HTTP API (v2) pointing at the Lambda. Returns invoke URL."""
    paginator = apigw.get_paginator("get_apis")
    for page in paginator.paginate():
        for api in page["Items"]:
            if api["Name"] == "careeros-api-gw":
                url = api["ApiEndpoint"]
                log.info("  API Gateway '%s' already exists — skip", api["Name"])
                return url

    api = apigw.create_api(
        Name="careeros-api-gw",
        ProtocolType="HTTP",
        CorsConfiguration={
            "AllowOrigins": ["*"],
            "AllowMethods": ["*"],
            "AllowHeaders": ["*"],
        },
    )
    api_id = api["ApiId"]
    log.info("  Created HTTP API '%s'", api_id)

    # Lambda integration
    integration = apigw.create_integration(
        ApiId=api_id,
        IntegrationType="AWS_PROXY",
        IntegrationUri=lambda_arn,
        PayloadFormatVersion="2.0",
    )
    integration_id = integration["IntegrationId"]

    # Catch-all route → Lambda
    apigw.create_route(
        ApiId=api_id,
        RouteKey="$default",
        Target=f"integrations/{integration_id}",
    )

    # Auto-deploy stage
    apigw.create_stage(
        ApiId=api_id,
        StageName="$default",
        AutoDeploy=True,
    )

    # Grant API Gateway permission to invoke Lambda
    lam = boto3.client("lambda", region_name=REGION)
    try:
        lam.add_permission(
            FunctionName=LAMBDA_NAME,
            StatementId="apigateway-invoke",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{account_id}:{api_id}/*",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceConflictException":
            raise

    url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com"
    log.info("  API Gateway invoke URL: %s", url)
    return url


def _ensure_cloudfront(cf, s3, frontend_bucket: str, account_id: str) -> str:
    """Create CloudFront distribution with OAC for private S3 bucket. Returns domain."""
    # Check for existing distribution
    paginator = cf.get_paginator("list_distributions")
    for page in paginator.paginate():
        items = page.get("DistributionList", {}).get("Items", [])
        for dist in items:
            for origin in dist.get("Origins", {}).get("Items", []):
                if frontend_bucket in origin.get("DomainName", ""):
                    domain = dist["DomainName"]
                    log.info("  CloudFront distribution already exists: %s", domain)
                    return domain

    # Create Origin Access Control (modern OAC — replaces legacy OAI)
    oac = cf.create_origin_access_control(
        OriginAccessControlConfig={
            "Name":                          f"careeros-oac-{frontend_bucket}",
            "Description":                   "CareerOS frontend OAC",
            "OriginAccessControlOriginType": "s3",
            "SigningBehavior":               "always",
            "SigningProtocol":               "sigv4",
        }
    )
    oac_id = oac["OriginAccessControl"]["Id"]
    log.info("  Created CloudFront OAC '%s'", oac_id)

    origin_id  = f"S3-{frontend_bucket}"
    origin_dns = f"{frontend_bucket}.s3.{REGION}.amazonaws.com"

    dist = cf.create_distribution(DistributionConfig={
        "CallerReference": str(int(time.time())),
        "Comment": "CareerOS frontend",
        "DefaultRootObject": "index.html",
        "Origins": {"Quantity": 1, "Items": [{
            "Id":         origin_id,
            "DomainName": origin_dns,
            "S3OriginConfig": {"OriginAccessIdentity": ""},
            "OriginAccessControlId": oac_id,
        }]},
        "DefaultCacheBehavior": {
            "TargetOriginId":       origin_id,
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2, "Items": ["GET", "HEAD"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
            },
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",  # CachingOptimized
            "Compress": True,
        },
        "CustomErrorResponses": {"Quantity": 1, "Items": [{
            "ErrorCode":            403,
            "ResponsePagePath":     "/index.html",
            "ResponseCode":         "200",
            "ErrorCachingMinTTL":   0,
        }]},
        "Enabled":      True,
        "HttpVersion":  "http2",
        "PriceClass":   "PriceClass_100",
    })
    dist_id = dist["Distribution"]["Id"]
    domain  = dist["Distribution"]["DomainName"]
    log.info("  CloudFront distribution created: https://%s  (deploy takes ~15 min)", domain)

    # Grant CloudFront OAC read access to the private S3 bucket
    s3.put_bucket_policy(
        Bucket=frontend_bucket,
        Policy=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid":       "AllowCloudFrontOAC",
                "Effect":    "Allow",
                "Principal": {"Service": "cloudfront.amazonaws.com"},
                "Action":    "s3:GetObject",
                "Resource":  f"arn:aws:s3:::{frontend_bucket}/*",
                "Condition": {"StringEquals": {
                    "AWS:SourceArn": f"arn:aws:cloudfront::{account_id}:distribution/{dist_id}"
                }},
            }],
        }),
    )
    log.info("  S3 bucket policy updated — CloudFront OAC read access granted")
    return domain


def _ensure_cloudwatch(cw, alarm_email: str | None) -> None:
    """Create log group + metric alarms."""
    # Log group
    try:
        cw.create_log_group(logGroupName=CW_GROUP)
        cw.put_retention_policy(logGroupName=CW_GROUP, retentionInDays=30)
        log.info("  Created CloudWatch log group '%s' (30-day retention)", CW_GROUP)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            log.info("  CloudWatch log group '%s' already exists — skip", CW_GROUP)
        else:
            raise

    # Optional SNS topic for alarms
    sns_arn: str | None = None
    if alarm_email:
        sns = boto3.client("sns", region_name=REGION)
        topic = sns.create_topic(Name="careeros-alarms")
        sns_arn = topic["TopicArn"]
        sns.subscribe(TopicArn=sns_arn, Protocol="email", Endpoint=alarm_email)
        log.info("  SNS alarm topic created — confirm subscription in your email")

    cw_alarms = boto3.client("cloudwatch", region_name=REGION)

    # Lambda error rate alarm
    alarm_kwargs: dict = dict(
        AlarmName="careeros-lambda-errors",
        AlarmDescription="Lambda error rate > 5 in 5 minutes",
        Namespace="AWS/Lambda",
        MetricName="Errors",
        Dimensions=[{"Name": "FunctionName", "Value": LAMBDA_NAME}],
        Period=300,
        EvaluationPeriods=1,
        Threshold=5,
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        Statistic="Sum",
        TreatMissingData="notBreaching",
    )
    if sns_arn:
        alarm_kwargs["AlarmActions"] = [sns_arn]
    cw_alarms.put_metric_alarm(**alarm_kwargs)
    log.info("  CloudWatch alarm 'careeros-lambda-errors' set")

    # Lambda p99 duration alarm
    duration_kwargs: dict = dict(
        AlarmName="careeros-lambda-p99-duration",
        AlarmDescription="Lambda p99 duration > 10 seconds",
        Namespace="AWS/Lambda",
        MetricName="Duration",
        Dimensions=[{"Name": "FunctionName", "Value": LAMBDA_NAME}],
        Period=300,
        EvaluationPeriods=1,
        Threshold=10000,  # ms
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        ExtendedStatistic="p99",
        TreatMissingData="notBreaching",
    )
    if sns_arn:
        duration_kwargs["AlarmActions"] = [sns_arn]
    cw_alarms.put_metric_alarm(**duration_kwargs)
    log.info("  CloudWatch alarm 'careeros-lambda-p99-duration' set")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="CareerOS infrastructure setup")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, don't create resources")
    parser.add_argument("--alarm-email", default=os.getenv("CAREEROS_ALARM_EMAIL", ""))
    args = parser.parse_args()

    if args.dry_run:
        log.info("DRY-RUN mode — no resources will be created")
        return

    sts = boto3.client("sts",       region_name=REGION)
    s3  = boto3.client("s3",        region_name=REGION)
    iam = boto3.client("iam",       region_name=REGION)
    lam = boto3.client("lambda",    region_name=REGION)
    apigw = boto3.client("apigatewayv2", region_name=REGION)
    cf  = boto3.client("cloudfront")
    cw_logs = boto3.client("logs",  region_name=REGION)

    account_id       = _account_id(sts)
    resume_bucket    = os.getenv("CAREEROS_RESUME_BUCKET",   f"careeros-resumes-{account_id}")
    frontend_bucket  = os.getenv("CAREEROS_FRONTEND_BUCKET", f"careeros-frontend-{account_id}")

    log.info("=== CareerOS Infrastructure Setup ===")
    log.info("Account:  %s  |  Region: %s", account_id, REGION)

    log.info("\n[1/7] Resume S3 bucket")
    _create_s3_bucket(s3, resume_bucket)

    log.info("\n[2/7] Frontend S3 bucket")
    _setup_frontend_bucket(s3, frontend_bucket)

    log.info("\n[3/7] IAM Lambda execution role")
    role_arn = _get_or_create_iam_role(iam, account_id)

    log.info("\n[4/7] Lambda function")
    lambda_arn = _ensure_lambda(lam, role_arn, resume_bucket)

    log.info("\n[5/7] API Gateway HTTP API")
    api_url = _ensure_api_gateway(apigw, lambda_arn, account_id)

    log.info("\n[6/7] CloudFront distribution")
    cf_domain = _ensure_cloudfront(cf, s3, frontend_bucket, account_id)

    log.info("\n[7/7] CloudWatch log group + alarms")
    _ensure_cloudwatch(cw_logs, args.alarm_email or None)

    log.info("\n✓ Infrastructure ready")
    log.info("  API endpoint:  %s", api_url)
    log.info("  Frontend CDN:  https://%s", cf_domain)
    log.info("  Resume bucket: s3://%s", resume_bucket)
    log.info("\nNext: run  bash deploy/deploy_backend.sh  to deploy the Lambda code.")


if __name__ == "__main__":
    main()
