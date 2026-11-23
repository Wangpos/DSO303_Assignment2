# Building and simulating the design in the Cloud Architecture Lab (Task 3)

This is a step-by-step build sheet for the Cloud Architecture Lab. Place components tier by tier, matching [diagram.png](diagram.png), then run the three simulations and save screenshots in [`../evidence/`](../evidence/) using the file names given below.

## 1. Build order

| # | Add component | Place in | Connect to |
|---|---|---|---|
| 1 | Region `ap-south-1`, VPC `10.20.0.0/16` | – | – |
| 2 | Availability Zones **A** and **B** | VPC | – |
| 3 | Public subnet `10.20.0.0/24` (AZ A), `10.20.1.0/24` (AZ B) | each AZ | Internet Gateway |
| 4 | Private app subnet `10.20.10.0/24` (A), `10.20.11.0/24` (B) | each AZ | NAT gateway in the same AZ |
| 5 | Private data subnet `10.20.20.0/24` (A), `10.20.21.0/24` (B) | each AZ | no internet route |
| 6 | Internet Gateway; NAT Gateway in **each** public subnet | VPC / public subnets | app-subnet route tables |
| 7 | Route 53 → WAF → CloudFront | Edge (global) | Users; S3 frontend; API Gateway |
| 8 | Cognito user pool (groups students / tutors / admins) | Region | CloudFront (hosted UI), API Gateway authorizer |
| 9 | S3 frontend bucket (private, OAC) | Region | CloudFront |
| 10 | API Gateway HTTP API (JWT authorizer) | Region | CloudFront, Cognito, Lambda api |
| 11 | Lambda `api`, `marker`, `notifier` – ENIs in **both** app subnets | App subnets A + B | API Gateway, SQS, Aurora, S3, SES |
| 12 | Aurora PostgreSQL **writer (AZ A)** + **reader (AZ B)** | Data subnets | Lambdas (Data API) |
| 13 | S3 uploads bucket (KMS, versioning, lifecycle 30 d IA / 180 d Glacier IR / 2 y Deep Archive / delete 5 y) | Region | Users (presigned POST), SQS notify |
| 14 | SQS `marking` + DLQ, SQS `notify` + DLQ | Region | Lambdas, S3 event |
| 15 | SES | Region | Lambda notifier → users |
| 16 | Secrets Manager, KMS, IAM roles | Region | Lambdas, Aurora, S3 |
| 17 | CloudWatch (dashboard, alarms, logs), X-Ray, SNS, AWS Backup | Region | All tiers |
| 18 | CI/CD: GitHub → Actions → OIDC role → Terraform | External → account | All |

Save as: `evidence/lab-01-full-architecture.png` (whole canvas) and `evidence/lab-02-vpc-two-az.png` (zoomed into the VPC showing both AZs and all three subnet tiers).

## 2. Simulation A – a student opens an exam and answers autosave

Run a request from **Users** along this path:

`Users → Route 53 → WAF → CloudFront → (S3 frontend for the SPA) → Cognito sign-in → CloudFront /api/* → API Gateway (JWT) → λ api (AZ A) → Aurora writer`

Then repeat the autosave request (`PUT /api/attempts/{id}/answers`) a few times to show the 30-second loop. Finally, submit: `λ api → SQS marking → λ marker → Aurora`.

Save as: `evidence/lab-03-flow-exam-autosave.png` (and the lab's request log, if it has one).

## 3. Simulation B – a 40 MB upload and the tutor notification

`Users → CloudFront → API Gateway → λ api` (returns the presigned URL) → `Users → S3 uploads (40 MB direct)` → `S3 event → SQS notify → λ notifier → Aurora (status uploaded) → SES → Tutor`

Point out that the 40 MB file **does not** pass through API Gateway or Lambda.

Save as: `evidence/lab-04-flow-upload-notify.png`.

## 4. Simulation C – loss of one Availability Zone

1. Fail / disable **AZ A** in the lab. This takes down NAT A, the Lambda ENIs in app subnet A and the Aurora writer.
2. Show that:
   - Aurora **reader in AZ B is promoted to writer** (under 60 s)
   - Lambda keeps serving from app subnet B, through NAT B
   - CloudFront, Route 53, WAF, Cognito, API Gateway, S3, SQS and SES keep working (managed multi-AZ)
3. Re-run Simulation A. It succeeds, with the writer now in AZ B.
4. Restore AZ A. The old writer rejoins as a reader.

Save as: `evidence/lab-05-az-failure.png` (AZ A down, flow succeeding) and `evidence/lab-06-az-recovered.png`.

## 5. Matching evidence from the real AWS deployment (optional, strengthens the video)

| What | How | Save as |
|---|---|---|
| Real AZ failover | `./scripts/simulate-az-failure.sh` (forces an Aurora failover and polls `/api/health?deep=1`) | `evidence/az-failover-*.log` (written automatically) |
| Peak behaviour | `python3 scripts/load_test.py --url <site_url> --workers 20 --requests 25` | `evidence/load-test.txt` |
| Dashboard during test | CloudWatch dashboard `examhub-prod` | `evidence/aws-dashboard.png` |
| Pipeline run | GitHub → Actions → latest run on main | `evidence/github-actions.png` |
