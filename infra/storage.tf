# ======================= Frontend bucket (served only via CloudFront) =======================
resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name}-frontend-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontOAC"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.frontend.arn, "${aws_s3_bucket.frontend.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

locals {
  frontend_dir = "${path.module}/../app/frontend"
  mime_types = {
    html = "text/html; charset=utf-8"
    css  = "text/css; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    svg  = "image/svg+xml"
    png  = "image/png"
    ico  = "image/x-icon"
    json = "application/json"
  }
}

resource "aws_s3_object" "frontend" {
  # config.js is generated below from Terraform outputs, so never upload a local copy.
  for_each = setsubtract(fileset(local.frontend_dir, "**/*.{html,css,js,svg,png,ico,json}"), ["config.js"])

  bucket        = aws_s3_bucket.frontend.id
  key           = each.value
  source        = "${local.frontend_dir}/${each.value}"
  etag          = filemd5("${local.frontend_dir}/${each.value}")
  content_type  = lookup(local.mime_types, reverse(split(".", each.value))[0], "application/octet-stream")
  cache_control = endswith(each.value, ".html") ? "no-cache" : "public, max-age=300"
}

# Runtime configuration generated from the infrastructure outputs.
resource "aws_s3_object" "frontend_config" {
  bucket        = aws_s3_bucket.frontend.id
  key           = "config.js"
  content_type  = "application/javascript; charset=utf-8"
  cache_control = "no-cache"
  content = <<-EOT
    window.APP_CONFIG = ${jsonencode({
  region        = var.region
  userPoolId    = aws_cognito_user_pool.main.id
  clientId      = aws_cognito_user_pool_client.web.id
  cognitoDomain = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
  redirectUri   = "${local.site_url}/"
  apiBase       = "/api"
  maxUploadMb   = 50
  autosaveSec   = 30
})};
  EOT
}

# ======================= Assignment uploads bucket =======================
resource "aws_s3_bucket" "uploads" {
  bucket        = "${local.name}-uploads-${local.account_id}"
  force_destroy = !var.deletion_protection
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}

# Records must be kept for 5 years; access drops sharply after the semester.
resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    id     = "submissions-5-year-retention"
    status = "Enabled"
    filter {
      prefix = "submissions/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 180
      storage_class = "GLACIER_IR"
    }
    transition {
      days          = 730
      storage_class = "DEEP_ARCHIVE"
    }
    expiration {
      days = 1826 # 5 years
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.uploads]
}

resource "aws_s3_bucket_cors_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  cors_rule {
    allowed_methods = ["POST", "GET"]
    allowed_origins = compact([local.site_url, "http://localhost:8080"])
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

resource "aws_s3_bucket_policy" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.uploads.arn, "${aws_s3_bucket.uploads.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.uploads]
}

# New object -> SQS -> notifier Lambda (validates file, notifies tutor).
resource "aws_s3_bucket_notification" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  queue {
    queue_arn     = aws_sqs_queue.notify.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "submissions/"
  }

  depends_on = [aws_sqs_queue_policy.notify]
}
