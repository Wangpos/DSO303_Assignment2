# ======================= Lambda package =======================
# Function code = app/backend/src. Third-party dependencies (pg8000) and the RDS
# CA bundle go in a layer built by scripts/build.sh from requirements.txt.
data "archive_file" "backend" {
  type        = "zip"
  source_dir  = "${path.module}/../app/backend/src"
  output_path = "${path.module}/build/backend.zip"
  excludes    = ["**/__pycache__/**"]
}

data "archive_file" "layer" {
  type        = "zip"
  source_dir  = "${path.module}/build/layer"
  output_path = "${path.module}/build/layer.zip"
  excludes    = ["**/__pycache__/**"]
}

resource "aws_lambda_layer_version" "deps" {
  layer_name               = "${local.name}-deps"
  description              = "pg8000 PostgreSQL driver + Amazon RDS CA bundle"
  filename                 = data.archive_file.layer.output_path
  source_code_hash         = data.archive_file.layer.output_base64sha256
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["arm64"]
}

locals {
  common_env = {
    DB_SECRET_ARN = aws_secretsmanager_secret.db.arn
    DB_CA_BUNDLE  = "/opt/rds-global-bundle.pem"
    UPLOAD_BUCKET = aws_s3_bucket.uploads.id
    MARKING_QUEUE = aws_sqs_queue.marking.url
    NOTIFY_QUEUE  = aws_sqs_queue.notify.url
    SENDER_EMAIL  = var.notification_email
    SITE_URL      = local.site_url
    USER_POOL_ID  = aws_cognito_user_pool.main.id
    MAX_UPLOAD_MB = "50"
  }

  functions = {
    api = {
      handler     = "api.handler"
      timeout     = 15
      memory      = 512
      description = "HTTP API for exams, autosave, uploads and admin"
    }
    marker = {
      handler     = "marker.handler"
      timeout     = 30
      memory      = 256
      description = "Auto-marks MCQ answers from the marking queue"
    }
    notifier = {
      handler     = "notifier.handler"
      timeout     = 60
      memory      = 256
      description = "Validates uploads and sends SES notifications"
    }
    migrate = {
      handler     = "migrate.handler"
      timeout     = 300
      memory      = 256
      description = "Applies the database schema and seeds demo data"
    }
  }
}

# ======================= IAM (one least-privilege role per function) =======================
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.functions
  name               = "${local.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "vpc" {
  for_each   = local.functions
  role       = aws_iam_role.fn[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "xray" {
  for_each   = local.functions
  role       = aws_iam_role.fn[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# Every function reads the database credentials from Secrets Manager and then
# connects to PostgreSQL over TLS inside the VPC (port 5432, Lambda SG -> DB SG).
data "aws_iam_policy_document" "db_access" {
  statement {
    sid       = "DbSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.db.arn]
  }
  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.main.arn]
  }
}

resource "aws_iam_role_policy" "db_access" {
  for_each = local.functions
  name     = "db-access"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.db_access.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "OriginSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.origin_verify.arn]
  }
  statement {
    sid       = "Uploads"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/submissions/*"]
  }
  statement {
    sid       = "Queues"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.marking.arn, aws_sqs_queue.notify.arn]
  }
  statement {
    sid       = "AdminUsers"
    actions   = ["cognito-idp:ListUsers", "cognito-idp:AdminCreateUser", "cognito-idp:AdminAddUserToGroup", "cognito-idp:AdminListGroupsForUser", "cognito-idp:ListUsersInGroup"]
    resources = [aws_cognito_user_pool.main.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "api"
  role   = aws_iam_role.fn["api"].id
  policy = data.aws_iam_policy_document.api.json
}

data "aws_iam_policy_document" "marker" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.marking.arn]
  }
}

resource "aws_iam_role_policy" "marker" {
  name   = "marker"
  role   = aws_iam_role.fn["marker"].id
  policy = data.aws_iam_policy_document.marker.json
}

data "aws_iam_policy_document" "notifier" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.notify.arn]
  }
  statement {
    actions   = ["s3:GetObject", "s3:GetObjectTagging", "s3:PutObjectTagging"]
    resources = ["${aws_s3_bucket.uploads.arn}/submissions/*"]
  }
  statement {
    actions   = ["ses:SendEmail"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.notification_email]
    }
  }
}

resource "aws_iam_role_policy" "notifier" {
  name   = "notifier"
  role   = aws_iam_role.fn["notifier"].id
  policy = data.aws_iam_policy_document.notifier.json
}

# ======================= Functions =======================
resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${local.name}-${each.key}"
  description      = each.value.description
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = each.value.handler
  timeout          = each.value.timeout
  memory_size      = each.value.memory
  filename         = data.archive_file.backend.output_path
  source_code_hash = data.archive_file.backend.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]
  publish          = true

  vpc_config {
    subnet_ids         = aws_subnet.app[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = merge(local.common_env, {
      ORIGIN_SECRET_ARN = each.key == "api" ? aws_secretsmanager_secret.origin_verify.arn : ""
    })
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_cloudwatch_log_group.fn,
    aws_iam_role_policy_attachment.vpc,
    aws_iam_role_policy.db_access,
  ]
}

resource "aws_lambda_alias" "api_live" {
  name             = "live"
  function_name    = aws_lambda_function.fn["api"].function_name
  function_version = aws_lambda_function.fn["api"].version
}

# Pre-warmed environments for exam week (needs the account concurrency quota raised first).
resource "aws_lambda_provisioned_concurrency_config" "api" {
  count                             = var.api_provisioned_concurrency > 0 ? 1 : 0
  function_name                     = aws_lambda_alias.api_live.function_name
  qualifier                         = aws_lambda_alias.api_live.name
  provisioned_concurrent_executions = var.api_provisioned_concurrency
}

resource "aws_lambda_event_source_mapping" "marking" {
  event_source_arn                   = aws_sqs_queue.marking.arn
  function_name                      = aws_lambda_function.fn["marker"].arn
  batch_size                         = 10
  maximum_batching_window_in_seconds = 2
  function_response_types            = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 5 # protects the database; the queue absorbs bursts
  }
}

resource "aws_lambda_event_source_mapping" "notify" {
  event_source_arn                   = aws_sqs_queue.notify.arn
  function_name                      = aws_lambda_function.fn["notifier"].arn
  batch_size                         = 10
  maximum_batching_window_in_seconds = 2
  function_response_types            = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 2 # stay under the SES sending rate
  }
}

# Apply the schema on every deploy (idempotent) - keeps the database reproducible from code.
resource "aws_lambda_invocation" "migrate" {
  function_name = aws_lambda_function.fn["migrate"].function_name
  input = jsonencode({
    action       = "migrate"
    code_version = data.archive_file.backend.output_base64sha256
    seed = var.create_demo_users ? {
      tutor_sub   = aws_cognito_user.demo["tutor1"].sub
      tutor_name  = "tutor1"
      tutor_email = var.notification_email
    } : null
  })

  depends_on = [
    aws_db_instance.main,
    aws_secretsmanager_secret_version.db,
    aws_route.app_nat,
    aws_route_table_association.app,
  ]
}

# ======================= API Gateway (HTTP API) =======================
resource "aws_apigatewayv2_api" "http" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
  description   = "Exam platform API (reached through CloudFront)"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.http.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
    audience = [aws_cognito_user_pool_client.web.id]
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.api_live.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 15000
}

resource "aws_apigatewayv2_route" "health" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /api/health"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "ANY /api/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 3000
    throttling_rate_limit  = 1500
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      ip        = "$context.identity.sourceIp"
      route     = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
      user      = "$context.authorizer.claims.sub"
      error     = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api"].function_name
  qualifier     = aws_lambda_alias.api_live.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
