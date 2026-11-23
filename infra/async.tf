# ======================= SQS queues =======================
# marking queue : submitted attempts -> marker Lambda (auto-marks MCQs)
# notify queue  : S3 upload events + "results released" -> notifier Lambda (SES email)
# Each has a dead-letter queue so a poison message never blocks the rest.

resource "aws_sqs_queue" "marking_dlq" {
  name                      = "${local.name}-marking-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "marking" {
  name                       = "${local.name}-marking"
  visibility_timeout_seconds = 180 # 6 x marker timeout
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.marking_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "notify_dlq" {
  name                      = "${local.name}-notify-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "notify" {
  name                       = "${local.name}-notify"
  visibility_timeout_seconds = 360 # 6 x notifier timeout
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notify_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_policy" "notify" {
  queue_url = aws_sqs_queue.notify.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3UploadEvents"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.notify.arn
      Condition = {
        ArnEquals    = { "aws:SourceArn" = aws_s3_bucket.uploads.arn }
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })
}

# ======================= SES =======================
# A verification link is emailed to this address on first deploy - click it.
resource "aws_sesv2_email_identity" "sender" {
  email_identity = var.notification_email
}
