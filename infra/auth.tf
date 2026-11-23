# Cognito user pool with role groups. Users sign in through the Cognito hosted
# UI (authorization code + PKCE), so the SPA never handles passwords.

resource "aws_cognito_user_pool" "main" {
  name                = "${local.name}-users"
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  username_configuration {
    case_sensitive = false
  }

  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = true # no self sign-up; admins create accounts
    invite_message_template {
      email_subject = "Your exam platform account"
      email_message = "Hello {username}, your temporary password is {####}. Sign in at ${local.site_url}"
      sms_message   = "Username {username}, temporary password {####}"
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = 3
      max_length = 256
    }
  }
}

resource "aws_cognito_user_group" "roles" {
  for_each = {
    admins   = 1
    tutors   = 2
    students = 3
  }
  name         = each.key
  user_pool_id = aws_cognito_user_pool.main.id
  precedence   = each.value
  description  = "${title(each.key)} role"
}

resource "random_string" "cognito_domain" {
  length  = 6
  special = false
  upper   = false
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${local.name}-${random_string.cognito_domain.result}"
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false # public SPA client, protected by PKCE
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["${local.site_url}/", "http://localhost:8080/"]
  logout_urls                          = ["${local.site_url}/", "http://localhost:8080/"]

  explicit_auth_flows           = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  # A 3-hour exam must not be interrupted by an expired token.
  id_token_validity      = 4
  access_token_validity  = 4
  refresh_token_validity = 1
  token_validity_units {
    id_token      = "hours"
    access_token  = "hours"
    refresh_token = "days"
  }
}

# ---------- Demo users (lab only) ----------
locals {
  demo_users = var.create_demo_users ? {
    student1 = "students"
    tutor1   = "tutors"
    admin1   = "admins"
  } : {}
}

resource "random_password" "demo" {
  for_each         = local.demo_users
  length           = 16
  min_lower        = 2
  min_upper        = 2
  min_numeric      = 2
  special          = true
  override_special = "!#%*-_"
}

resource "aws_cognito_user" "demo" {
  for_each     = local.demo_users
  user_pool_id = aws_cognito_user_pool.main.id
  username     = each.key
  password     = random_password.demo[each.key].result

  attributes = {
    email          = var.notification_email
    email_verified = true
  }
}

resource "aws_cognito_user_in_group" "demo" {
  for_each     = local.demo_users
  user_pool_id = aws_cognito_user_pool.main.id
  group_name   = aws_cognito_user_group.roles[each.value].name
  username     = aws_cognito_user.demo[each.key].username
}
