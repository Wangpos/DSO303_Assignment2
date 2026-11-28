# DSO303 Assignment 2 – ExamHub: online exams & assignment submissions on AWS

A university with 8,000 students and 400 staff is moving exams and assignment submissions online. This repository contains the production architecture, service documentation and a **working, fully code-defined AWS deployment** with a CI/CD pipeline. Pushing to `main` redeploys everything.

![Architecture](architecture/diagram.png)

## Summary

- **Edge:** Route 53 → **WAF** → **CloudFront**. CloudFront serves the SPA from a private S3 bucket and proxies `/api/*` to the API.
- **Auth:** Cognito user pool with `students` / `tutors` / `admins` groups, hosted UI and OAuth code + PKCE.
- **API and compute:** API Gateway HTTP API with a Cognito JWT authorizer, in front of Python Lambdas in **private subnets in two AZs**.
- **Database:** production design is Aurora PostgreSQL Serverless v2 (**writer in AZ A, reader in AZ B**). The deployed build uses **Amazon RDS for PostgreSQL Multi-AZ** (**primary in AZ A, synchronous standby in AZ B**, automatic failover) because the AWS Free plan blocks Aurora. See [Deployed build](#deployed-build-aws-free-plan).
- **Files:** S3 with presigned POST (PDF/ZIP ≤ 50 MB), KMS encryption, versioning, and a lifecycle of IA → Glacier IR → Deep Archive → delete at 5 years.
- **Async:** SQS `marking` and `notify` queues with DLQs. Lambda workers auto-mark MCQs, verify uploads and send SES email.
- **Operations:** Secrets Manager, a KMS customer-managed key, CloudWatch dashboard and alarms → SNS, X-Ray, VPC flow logs, AWS Backup (monthly snapshots kept 5 years).
- **Delivery:** Terraform (S3 remote state) and GitHub Actions via OIDC. Pull requests run tests and `plan`; a push to `main` runs tests, `apply`, a cache invalidation and a smoke test.

| Requirement | Met by |
|---|---|
| 300–500 users normally, 3,000 exam starts in 5 min | CloudFront cache, API Gateway + Lambda autoscaling, provisioned concurrency, Data API (no connection pool), Aurora Serverless v2, SQS buffering |
| 99.9 % and survives loss of one AZ | Two-AZ VPC, Lambda in both AZs, NAT per AZ (production), database Multi-AZ automatic failover (Aurora < 60 s; deployed RDS 60–120 s) |
| RPO ≤ 5 min / RTO ≤ 1 h | Synchronous replication to the second AZ (RPO 0 for committed answers), browser-side answer buffer (≤ 30 s), PITR (35 d in production, 1 d on the Free-plan account), Terraform rebuild |
| 5-year records | S3 lifecycle expiry at 1,826 d; AWS Backup monthly snapshots kept 1,826 d |
| Encryption in transit / at rest | TLS everywhere (S3 denies non-TLS, database `rds.force_ssl=1` with CA-verified TLS from Lambda), KMS customer key |

## Deployed build (AWS Free plan)

The diagram and [docs/services.md](docs/services.md) describe the production design. The AWS account used for this assignment is on the **Free plan**, which only allows Aurora in "express configuration": a single instance outside the VPC, reachable from the internet. That would break the private, two-AZ database requirement (see the failed attempt in `evidence/cli-03c-deploy-failed-express-config.txt`). The deployed build therefore swaps only the database tier:

| | Production design | Deployed build (Free plan) |
|---|---|---|
| Engine | Aurora PostgreSQL Serverless v2 | RDS for PostgreSQL 17, `db.t4g.micro` |
| Two AZs | Writer AZ A + reader AZ B, storage in 3 AZs | **Multi-AZ**: primary AZ A + synchronous standby AZ B |
| Failover | Reader promoted, < 60 s | Standby promoted, DNS moved, 60–120 s |
| Network | Private data subnets, SG from Lambda only | Same |
| Encryption | KMS CMK at rest, `rds.force_ssl` | Same, plus TLS verified against the RDS CA bundle |
| Access from Lambda | RDS Data API (HTTPS) | `pg8000` driver over TLS on 5432, credentials from Secrets Manager, auto-reconnect on failover (`app/backend/src/lib/db.py`) |
| Peak-load headroom | Scales 2–16 ACU, no connection limit | Fixed size; connections alarm at 70. For a real exam week switch back to Aurora or add RDS Proxy |

Everything else (edge, auth, API, Lambda, S3, SQS, SES, monitoring, backup, CI/CD) is identical to the design.

## Report: deployment evidence

The platform was deployed to **ap-south-1 (Mumbai)** with `scripts/deploy.sh` and tested end to end with the three demo users. Each section below matches one part of the architecture and shows the evidence for it. Most images are AWS Console or browser screenshots of the live system. The `cli-*` images are terminal output from real commands; the `.txt` file with the same name holds the full log.

> **Note on items 7.2–7.5.** Console access to the account was lost after the deployment (IAM sign-in and CLI keys both rejected). The Cognito, WAF, Secrets Manager/KMS and dashboard evidence is therefore taken from the Terraform deploy log (real resource IDs created in the account) together with the Terraform configuration that set them up, not from the console.

### 1. Infrastructure as code

The whole platform is defined in Terraform under `infra/`. Before deploying, the backend unit tests and Terraform validation both pass.

![Unit tests](evidence/cli-01-unit-tests.png)
*19 backend unit tests pass (database conversions, exam validation, roles, routing, MCQ scoring, upload validation).*

![Terraform validate](evidence/cli-02-terraform-validate.png)
*`terraform fmt -check`, and `terraform validate` for both `infra/` and `infra/bootstrap/`, succeed.*

![Deploy](evidence/cli-03-deploy.png)
*`scripts/deploy.sh` finishes with `Apply complete!` and prints the site URL and the GitHub CI/CD settings.*

**Troubleshooting during deployment.** The first attempts used Aurora PostgreSQL Serverless v2 as designed and were rejected by the AWS Free plan:

| Attempt | Error | Response |
|---|---|---|
| [cli-03a](evidence/cli-03a-deploy-failed-free-plan.png) | `FreeTierRestrictionError`: backup retention above the Free-plan maximum | Lowered retention to 1 day |
| [cli-03b](evidence/cli-03b-deploy-failed-acu-limit.png) | `FreeTierRestrictionError`: maximum capacity above 4 ACUs | Lowered max ACU |
| [cli-03c](evidence/cli-03c-deploy-failed-express-config.png) | Aurora on the Free plan requires `WithExpressConfiguration` (single instance, outside the VPC) | Not acceptable for the private, two-AZ requirement, so the database tier was switched to **RDS PostgreSQL Multi-AZ** |
| [cli-03d](evidence/cli-03d-deploy-failed-network.png) | `no such host` (local network dropped mid-apply) | Re-ran the deploy; Terraform resumed from remote state |

### 2. Frontend and edge (CloudFront)

![Landing page](evidence/aws-site-login.png)
*The single-page app served over HTTPS from the CloudFront domain.*

![CloudFront origins](evidence/aws-cloudfront.png)
*CloudFront has two origins: `frontend-s3` (private S3 bucket reached through Origin Access Control) for `/`, and `api` (API Gateway) for `/api/*`. AWS WAF is attached to the distribution.*

### 3. Walkthrough 1: sitting an exam with autosave

**Student view.** `student1` signs in through Cognito and sees the exams and assignments open to them.

![Student dashboard](evidence/aws-student-dashboard.png)
*The student dashboard lists the seeded exam (with its window and duration) and the assignment upload.*

![Exam autosave](evidence/aws-exam-autosave.png)
*During the exam the page shows "Saved 3 answer(s) at …" and the countdown timer.*

![Autosave network](evidence/aws-autosave-network.png)
*Browser DevTools: each autosave is a `PUT …/answers` request that returns **200** in about 225–265 ms.*

**Request path.** Browser → CloudFront → API Gateway → `examhub-prod-api` Lambda → RDS.

![API Gateway routes](evidence/aws-api-gateway.png)
*HTTP API `examhub-prod-api`: the public `GET /api/health` and `ANY /api/{proxy+}`, which is protected by the Cognito JWT authorizer and integrated with the API Lambda.*

![Lambda functions](evidence/aws-lambda-functions.png)
*Four Python 3.13 functions: `api` (HTTP API), `marker` (auto-marks MCQs from the marking queue), `notifier` (verifies uploads and sends SES email) and `migrate` (schema and seed data).*

![Lambda VPC](evidence/aws-lambda-vpc.png)
*The API Lambda runs in `examhub-prod-vpc` (10.20.0.0/16) in two private app subnets, **10.20.10.0/24 in ap-south-1a** and **10.20.11.0/24 in ap-south-1b**, with security group `examhub-prod-lambda-sg`.*

### 4. Two-AZ database and failover

![RDS before failover](evidence/aws-rds-two-az.png)
*RDS `examhub-prod-db`: PostgreSQL 17.9, **Multi-AZ: Yes**, with the standby in a different AZ (secondary zone ap-south-1a).*

![RDS configuration](evidence/aws-rds-config.png)
*Storage encryption is enabled with the customer-managed KMS key `examhub-prod`. Storage is 20 GiB gp3 and logs are published to CloudWatch.*

**Simulated loss of an AZ.** `scripts/simulate-az-failure.sh` forces a Multi-AZ failover (`reboot-db-instance --force-failover`) while calling `/api/health` every 3 seconds.

![AZ failover](evidence/cli-04-az-failover.png)
*The primary moved from ap-south-1b to ap-south-1a. The API kept answering 200 throughout, apart from one timed-out health check.*

| Measure | Result | Target |
|---|---|---|
| Failover time | **72 s** | RTO ≤ 1 h ✅ |
| Health checks failed | 1 (single timeout at +24 s) | Covered by API retries and the browser's local answer buffer |
| Data lost | 0 committed answers (synchronous standby) | RPO ≤ 5 min ✅ |

![RDS events](evidence/aws-rds-after-failover.png)
*RDS events: "Multi-AZ instance failover started", "failover completed", "DB instance restarted". Earlier events show the conversion to Multi-AZ and the automated backups.*

![RDS after failover](evidence/aws-rds-after-failover-2.png)
*After the failover the standby is in ap-south-1b: the two AZs swapped roles.*

### 5. Walkthrough 2: 40 MB assignment upload and tutor notification

The browser asks the API for a presigned POST and uploads the file **directly to S3**, so large files never pass through Lambda. The S3 event goes to the `notify` queue, and the notifier Lambda checks the file and emails the tutor.

![Upload](evidence/aws-upload-40mb.png)
*After the upload the submission shows "uploaded: report.pdf".*

![S3 object](evidence/aws-s3-object.png)
*The 40.0 MB `report.pdf` stored under `submissions/<assignment-id>/<submission-id>/` in the uploads bucket.*

![S3 lifecycle](evidence/aws-s3-lifecycle.png)
*Lifecycle rule `submissions-5-year-retention`: Standard-IA at day 30, Glacier Instant Retrieval at day 180, Glacier Deep Archive at day 730, and expiry at day 1,826 (5 years). Old versions are deleted after 30 days.*

![Tutor email](evidence/aws-tutor-email.png)
*SES email to the tutor: "student1 submitted 'report.pdf' (40.0 MB) for 'Demo: Architecture Report'".*

![Tutor submissions](evidence/aws-tutor-submissions.png)
*The tutor's submissions page lists the file, its size, upload time and status, with a presigned download.*

### 6. Asynchronous marking and results release

![SQS queues](evidence/aws-sqs-queues.png)
*Four queues: `marking` and `notify`, each with a dead-letter queue. All are encrypted with SSE-SQS and were empty after processing.*

![Marking](evidence/aws-marking.png)
*After submission the `marker` Lambda auto-marked the MCQs (2 marks, status "auto marked"). The tutor then marks the short answer.*

![Results email](evidence/aws-results-email.png)
*When the tutor releases results, the student receives a "Results released" email through SES.*

![Student result](evidence/aws-student-result.png)
*The student now sees "Result: 2 / 5". The second exam is still "Submitted – awaiting results".*

![Notifier logs](evidence/cli-07-notifier-logs.png)
*Structured JSON logs from the notifier Lambda for both jobs: `upload processed` (size 41,943,049 bytes) and `results emails processed`.*

### 7. Administration, security and monitoring

#### 7.1 User administration

![Admin users](evidence/aws-admin-users.png)
*`admin1` manages users: creating a user in Cognito sends them a temporary password. The three demo users are CONFIRMED in their roles.*

#### 7.2 Cognito groups

![Cognito groups](evidence/cli-08-cognito-groups.png)
*The groups `students`, `tutors` and `admins` exist in user pool `ap-south-1_qFoZibCMA`, with precedence admins 1, tutors 2, students 3. The API reads the group from the JWT to decide what a user may do.*

#### 7.3 AWS WAF

![WAF rules](evidence/cli-09-waf-rules.png)
*Web ACL `examhub-prod-edge` (CLOUDFRONT scope) with three AWS managed rule sets (Common, Known Bad Inputs, IP Reputation) and a per-IP rate limit.*

#### 7.4 Secrets Manager and KMS

![Secrets and KMS](evidence/cli-10-secrets-kms.png)
*The database credentials and the CloudFront origin-verify header are stored in Secrets Manager under `examhub-prod/…`. The customer-managed KMS key has automatic key rotation enabled.*

#### 7.5 CloudWatch dashboard and alarms

![Dashboard](evidence/cli-11-dashboard.png)
*The `examhub-prod` dashboard was created with six graphs: API requests and errors, API latency, Lambda concurrency and throttles, database, queues, and WAF allowed vs blocked.*

![CloudWatch overview](evidence/aws-cloudwatch-overview.png)
*CloudWatch overview: 11 alarms across API Gateway, Lambda, RDS and SQS, all OK.*

![Alarms](evidence/aws-alarms.png)
*Alarms notify through SNS. They cover API 5xx, throttles, p95 latency, Lambda errors (api, marker, notifier), database CPU and connections, both dead-letter queues, and the age of the marking backlog.*

#### 7.6 Load test

![Load test](evidence/cli-05-load-test.png)
*400 requests at 45 req/s through CloudFront and the API: **all 200**, p50 162 ms, p95 211 ms.*

![Load test quota](evidence/cli-05b-load-test-quota-limit.png)
*With 20 parallel workers (137 req/s), 490 of 500 requests returned **503**. A new account's Lambda concurrency quota is only 10. This is why the exam-week settings below include raising that quota to 1,000 and adding provisioned concurrency before a real exam.*

### 8. CI/CD

`.github/workflows/deploy.yml` runs unit tests on every push and pull request. Pull requests also get a read-only `terraform plan`, and a push to `main` runs `terraform apply`, a CloudFront invalidation and a smoke test. The pipeline signs in to AWS through GitHub OIDC roles created by `infra/bootstrap`, so no access keys are stored in GitHub.

![Pipeline run](evidence/cli-12-pipeline-run.png)
*The first push to `main` started the pipeline automatically. The `test` job passed. The `deploy` job stopped at "configure AWS credentials" because the repository variables (`AWS_DEPLOY_ROLE_ARN`, `AWS_PLAN_ROLE_ARN`, `TF_STATE_BUCKET`) had not yet been set.*

### 9. Limitations and lessons

- **Free plan.** Aurora could not be deployed privately on the Free plan, so the deployed build uses RDS Multi-AZ. Failover took 72 s instead of Aurora's < 60 s, and the database size is fixed.
- **Lambda quota.** The default concurrency of 10 is far below exam-day demand (3,000 starts in 5 minutes). A quota increase and provisioned concurrency are required before production use.
- **SES sandbox.** All demo email goes to one verified address. Production access is needed to email real students.
- **Account access.** Console access was lost after deployment, so items 7.2–7.5 are evidenced from the deploy log and Terraform rather than the console.

## Repository layout

```
README.md                    this file – summary, deploy, tear-down
architecture/
  diagram.png / diagram.svg  production architecture (generated by generate_diagram.py)
  README.md                  tiers, both request walkthroughs, peak + AZ-loss explanation
  cloud-architecture-lab.md  build + simulation sheet for the Cloud Architecture Lab
docs/services.md             every service: role, why over an alternative, configuration, connections
evidence/                    Cloud Architecture Lab screenshots + AWS deployment evidence
infra/                       Terraform for the whole platform (network, edge, auth, db, storage, compute, async, monitoring, backup)
infra/bootstrap/             one-time: Terraform state bucket + GitHub OIDC deploy/plan roles
app/frontend/                single-page app (vanilla JS, no build step)
app/backend/src/             Lambda handlers: api.py, marker.py, notifier.py, migrate.py
app/backend/tests/           unit tests (python -m unittest)
scripts/                     deploy.sh, destroy.sh, simulate-az-failure.sh, load_test.py
.github/workflows/deploy.yml CI/CD pipeline
```

## Deploy

### Prerequisites

- An AWS account and CLI credentials with admin rights (only needed for the one-time bootstrap)
- Terraform ≥ 1.10, AWS CLI v2, Python 3 with pip, curl, git
- An email address you can receive mail at. It is the SES sender, and in the SES sandbox it is also the only recipient, so all demo users use it.

### Option A – first deploy from your machine (also bootstraps CI/CD)

```bash
NOTIFICATION_EMAIL=you@example.com ./scripts/deploy.sh
```

This:

1. Applies `infra/bootstrap`, creating the state bucket `examhub-tfstate-<account>` and the IAM roles `examhub-github-deploy` (main branch only) and `examhub-github-plan` (PRs, read-only). It reuses the GitHub OIDC provider if one already exists.
2. Builds the Lambda layer (`scripts/build.sh`: `pg8000` from `app/backend/requirements.txt` plus the RDS CA bundle).
3. Runs `terraform apply` on `infra/`. This takes about 20–25 minutes, mostly for CloudFront and the Multi-AZ database. It finishes by invoking the `migrate` Lambda to create the schema and seed a demo exam and assignment.
4. Prints the site URL and the GitHub variables to set.

After the first apply:

- **Click both AWS emails**: the SES identity verification and the SNS alarm subscription.
- Get the demo passwords: `terraform -chdir=infra output -json demo_credentials` (users `student1`, `tutor1`, `admin1`).
- Open `site_url` and sign in.

### Option B – CI/CD (push to `main` redeploys)

After the bootstrap has run once, set these in GitHub → *Settings → Secrets and variables → Actions*:

| Type | Name | Value |
|---|---|---|
| Variable | `AWS_DEPLOY_ROLE_ARN` | output `deploy_role_arn` of `infra/bootstrap` |
| Variable | `AWS_PLAN_ROLE_ARN` | output `plan_role_arn` |
| Variable | `TF_STATE_BUCKET` | output `state_bucket` |
| Secret | `NOTIFICATION_EMAIL` | the same email address |

From then on, each push to `main` runs unit tests, `terraform fmt`, builds the Lambda layer, runs `terraform apply`, the CloudFront invalidation and a `/api/health?deep=1` smoke test. Pull requests run tests plus `terraform plan` using the read-only role. No AWS access keys are stored in GitHub.

### Exam-week settings

Before a real exam week:

1. Request a **Lambda concurrent executions quota of 1,000** in Service Quotas. New accounts start at 10.
2. Request **SES production access**.
3. Set these Terraform variables:
   ```hcl
   high_availability_nat       = true
   db_instance_class           = "db.r7g.large"   # or move back to Aurora Serverless v2 on a Paid-plan account
   db_backup_retention_days    = 35
   api_provisioned_concurrency = 50
   deletion_protection         = true
   campus_cidrs                = ["<campus NAT IP>/32"]
   ```

## Using the platform

| Role | Can do |
|---|---|
| `student1` | Start the seeded *Cloud Fundamentals Quiz*, watch "Saved … at hh:mm:ss" every 30 s, submit, upload a PDF/ZIP to *Architecture Report*, see results once released |
| `tutor1` | Create exams (MCQ + short answer), see attempts, mark short answers, **release results** (emails students), create assignments, download submissions |
| `admin1` | Create users in any role (Cognito emails an invite), edit exam schedules, see all exams and assignments |

## Simulations

```bash
./scripts/simulate-az-failure.sh                        # forces an RDS Multi-AZ failover AZ A→B, logs API health to evidence/
python3 scripts/load_test.py --url <site_url> --workers 20 --requests 25
python3 -m unittest discover -s app/backend/tests -v    # unit tests
```

The Cloud Architecture Lab simulations are described in [architecture/cloud-architecture-lab.md](architecture/cloud-architecture-lab.md).

## Tear down

```bash
NOTIFICATION_EMAIL=you@example.com ./scripts/destroy.sh         # remove the platform
NOTIFICATION_EMAIL=you@example.com ./scripts/destroy.sh --all   # also remove state bucket + CI roles
```

The lab defaults (`deletion_protection = false`, `force_destroy` on buckets and the backup vault, no final DB snapshot) let `destroy` finish cleanly. Lambda network interfaces in the VPC can take 10–20 minutes to release. Check AWS Billing the next day.

**Cost while running (lab defaults, approximate):** NAT gateway ≈ US$1.4/day, RDS Multi-AZ `db.t4g.micro` + 20 GB gp3 ≈ US$1.1/day, WAF ≈ US$0.3/day, KMS and Secrets ≈ US$0.1/day. Everything else stays within free tiers at demo volume. That is about **US$3 per day**, so tear down after recording the video.

## Documentation

- [architecture/README.md](architecture/README.md): tiers, walkthroughs (with sequence diagrams), peak and AZ-loss reasoning
- [docs/services.md](docs/services.md): service table
- [architecture/cloud-architecture-lab.md](architecture/cloud-architecture-lab.md): lab build and simulation guide
- [evidence/](evidence/): screenshots and logs
