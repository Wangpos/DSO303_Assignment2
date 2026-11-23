# Complete screenshot guide for the report

This guide explains, for **every** screenshot the report needs:

- **Where:** which app or website to open (Terminal, browser, AWS Console, GitHub, Gmail, Cloud Architecture Lab)
- **Steps:** exactly what to click or type to reach the right screen
- **Must be visible:** what has to be in the frame for the marker to accept it
- **Capture:** which screenshot method to use
- **Save as:** the file name (always inside the `evidence/` folder)
- **Caption:** text to paste under the image in your report

Work through the parts **in order**. Earlier steps create the data that later screenshots show; for example, the student must submit the exam before the tutor can release results.

---

## Part A – Before you start

### A1. How to take screenshots on a Mac

| Method | Keys | Use it for |
|---|---|---|
| **Window** | `Cmd + Shift + 4`, then press `Space`, then click the window | Terminal and browser windows. Clean edges, no desktop. |
| **Area** | `Cmd + Shift + 4`, then drag a box | Part of a page, e.g. one table in the AWS Console |
| **Full screen** | `Cmd + Shift + 3` | Only when you need two windows side by side |
| **Options / save folder** | `Cmd + Shift + 5` → **Options** → *Save to* → **Other Location…** → choose `DSO303_Assignment2/evidence` | Do this once, so every screenshot lands in `evidence/` |

New screenshots are named like `Screenshot 2026-11-19 at 15.20.11.png`. **Rename each one** straight away to the name in this guide: click the file in Finder, press `Enter`, type the new name.

### A2. How to blur private information

Before putting any image in the report, hide:

- your **email address**
- your **AWS account ID** (12 digits, top-right of the AWS Console and inside ARNs)
- any **password**

Steps: double-click the image (opens in **Preview**) → **Tools → Annotate → Rectangle** → draw over the text → in the shape style menu choose a **filled** black box → `Cmd + S`.

### A3. Things to open and have ready

1. **Terminal:** open it in the project folder:
   ```bash
   cd ~/Desktop/DSO303_Assignment2
   ```
2. **Site URL and demo passwords** (run in Terminal; keep the window open):
   ```bash
   terraform -chdir=infra output -raw site_url
   terraform -chdir=infra output -json demo_credentials
   ```
3. **Two browser windows** (Chrome or Safari):
   - **Window 1 (normal):** used for `student1`
   - **Window 2 (private):** `Cmd + Shift + N` in Chrome or `Cmd + Shift + N` in Safari, used for `tutor1` and later `admin1`

   The Cognito sign-in remembers who is logged in per browser. Without a separate private window, the student and tutor accounts get mixed up.
4. **AWS Console:** sign in at https://console.aws.amazon.com. In the top-right region menu choose **Asia Pacific (Mumbai) ap-south-1**. WAF is the one exception (see C24).
5. **Gmail:** open your inbox. On the first deploy, click the links in both AWS emails:
   - *"Amazon Web Services – Email Address Verification Request"* (SES; without it no notification emails are sent)
   - *"AWS Notification – Subscription Confirmation"* (SNS alarm emails)
6. **40 MB test file** for the upload screenshots (run in Terminal):
   ```bash
   python3 -c "open('report.pdf','wb').write(b'%PDF-1.7\n' + b'0' * 40 * 1024 * 1024)"
   ```
   This creates `report.pdf` (40 MB) in the project folder. It starts with the real PDF header, so it passes the platform's file-type check. You can also use any real PDF of 30–50 MB.

---

## Part B – Terminal screenshots

Screenshots B1–B4 already exist in `evidence/`. They were captured with `scripts/capture.py`, which runs the real command and saves both a `.png` (in your terminal style) and a `.txt` (full log). For B5 onwards, either ask Claude to capture them the same way, or take them yourself: run the command in **your** Terminal, wait for it to finish, then take a **Window** screenshot (`Cmd + Shift + 4`, `Space`, click Terminal).

### B1. `cli-01-unit-tests.png` (done)
- **Where:** Terminal, project folder
- **Steps:** run `python3 -m unittest discover -s app/backend/tests -v`
- **Must be visible:** the command, 19 test lines ending in `ok`, `Ran 19 tests`, `OK`
- **Caption:** *Backend unit tests (marking, upload validation, roles, routing) pass; the same tests run in the CI pipeline.*

### B2. `cli-02-terraform-validate.png` (done)
- **Where:** Terminal, project folder
- **Steps:** run `terraform -chdir=infra fmt -check -recursive && terraform -chdir=infra validate && terraform -chdir=infra/bootstrap validate`
- **Must be visible:** two lines `Success! The configuration is valid.`
- **Caption:** *Both Terraform stacks are correctly formatted and valid.*

### B3. `cli-03a/b/c-deploy-failed-*.png` (done, optional troubleshooting section)
- **What they show:** three real deploy attempts stopped by AWS Free-plan restrictions: backup retention, the 4-ACU cap, and Aurora "express configuration". The first two were fixed with Terraform variables; the third cannot be met with a private two-AZ database, so the deployed build switched to RDS PostgreSQL Multi-AZ.
- **Caption:** *Deployment troubleshooting: the AWS Free plan only allows a single, internet-reachable Aurora instance, so the deployed build uses RDS PostgreSQL Multi-AZ to keep the database private and in two AZs.*

### B4. `cli-03-deploy.png` (successful deploy)
- **Where:** Terminal, project folder
- **Steps:** run `NOTIFICATION_EMAIL=<your email> ./scripts/deploy.sh -auto-approve` and wait about 20 minutes
- **Must be visible:** `Apply complete! Resources: … added`, then the `Site:` URL and `Health:` URL printed at the end
- **Capture:** Window. If the output is too long, scroll so the end is visible.
- **Caption:** *The whole platform is created from code with one command (Terraform).*

### B5. `cli-04-az-failover.png`
- **Where:** Terminal, project folder
- **Steps:**
  1. Run `./scripts/simulate-az-failure.sh`
  2. Wait 2–5 minutes until it prints `primary after:` and `Saved evidence/az-failover-….log`
- **Must be visible:** the `primary:` and `standby:` AZs before, the health-check lines (`/api/health -> 200` / `503`), `primary after:` showing the other AZ, and the failover / degraded-window lines
- **Caption:** *Simulated loss of the primary's Availability Zone: RDS promotes the standby in the other AZ and the API recovers automatically.*

### B6. `cli-05-load-test.png`
- **Where:** Terminal, project folder
- **Steps:** run `python3 scripts/load_test.py --url $(terraform -chdir=infra output -raw site_url) --workers 20 --requests 25`
- **Must be visible:** `requests: 500 in …s (… req/s)`, the status codes, p50/p95 latency
- **Caption:** *Load test against the live API; results feed the CloudWatch dashboard in C26.*

### B7. `cli-06-destroy.png` (do this LAST, after recording your video)
- **Where:** Terminal, project folder
- **Steps:** run `NOTIFICATION_EMAIL=<your email> ./scripts/destroy.sh`, type `yes` when asked, wait 15–25 minutes
- **Must be visible:** `Destroy complete! Resources: … destroyed.`
- **Caption:** *All resources removed with one command; the platform is fully reproducible from code.*

---

## Part C – Live AWS deployment

### Frontend

#### C1. `aws-site-login.png`
- **Where:** Browser window 1
- **Steps:**
  1. Paste the `site_url` into the address bar and press Enter
  2. The ExamHub landing page appears with a **Sign in** button. Screenshot 1.
  3. Click **Sign in**. The Cognito sign-in page opens. Screenshot 2.
- **Must be visible:** the address bar with `https://…cloudfront.net` and the padlock icon; the Cognito page with its `amazoncognito.com` address
- **Capture:** Window (two images; place them side by side in the report)
- **Caption:** *The single-page app is served over HTTPS by CloudFront from a private S3 bucket; sign-in uses the Cognito hosted UI.*

#### C2. `aws-cloudfront.png`
- **Where:** AWS Console → search bar: type **CloudFront** → open it
- **Steps:**
  1. Left menu **Distributions** → click the distribution **ID** (comment "examhub-prod exam platform")
  2. **Origins** tab: two rows, `frontend-s3` and `api`. Screenshot.
  3. **Behaviors** tab: `/api/*` → `api` and `Default (*)` → `frontend-s3`. Screenshot.
  4. **Security** tab: web ACL `examhub-prod-edge`. Screenshot.
- **Capture:** Area (just the tab content)
- **Caption:** *CloudFront sends `/` to the S3 frontend (via OAC) and `/api/*` to API Gateway, with AWS WAF attached.*

### Walkthrough 1 – exam and autosave

#### C3. `aws-student-dashboard.png`
- **Where:** Browser window 1
- **Steps:** on the Cognito page enter `student1` and the password from A3 → **Sign in**
- **Must be visible:** the **My exams** table with *Demo: Cloud Fundamentals Quiz* and a **Start exam** button, the **Assignments** table, and `student1 · student` at the top right
- **Capture:** Window
- **Caption:** *Student dashboard after role-based sign-in (Cognito group `students`).*

#### C4. `aws-exam-autosave.png`
- **Where:** Browser window 1
- **Steps:**
  1. **First**, open DevTools: `Cmd + Option + I` → **Network** tab → type `answers` in the Filter box. This is needed for C5.
  2. Click **Start exam**
  3. Pick an answer for each of the 3 multiple-choice questions and type one sentence in question 4
  4. **Wait about 60 seconds** without leaving the page
- **Must be visible:** the exam title, the countdown **timer**, and the green status text **"Saved N answer(s) at hh:mm:ss"**
- **Capture:** Window (you can close DevTools for this one and reopen it for C5)
- **Caption:** *Timed exam with a server-side deadline; answers are autosaved every 30 seconds.*

#### C5. `aws-autosave-network.png`
- **Where:** Browser window 1, DevTools → Network tab (opened in C4)
- **Steps:** after 60+ seconds you'll see at least 2 requests named `answers`. Click one → **Payload** tab to show it contains only the changed answers.
- **Must be visible:** two or more `answers` rows, method **PUT**, status **200**, timestamps about 30 s apart (Time or Waterfall column)
- **Capture:** Window (browser + DevTools)
- **Caption:** *Autosave requests (`PUT /api/attempts/{id}/answers`) every 30 seconds, each returning 200.*
- ⚠️ **Do not submit the exam yet.** Leave this tab open; it is used in C16.

#### C6. `aws-api-gateway.png`
- **Where:** AWS Console → search **API Gateway**
- **Steps:**
  1. Click **examhub-prod-api**
  2. Left menu **Routes**: `GET /api/health` and `ANY /api/{proxy+}`
  3. Click `ANY /api/{proxy+}`. The right panel shows **Authorization: JWT (cognito)**.
- **Must be visible:** the routes list and the JWT authorizer
- **Capture:** Area
- **Caption:** *HTTP API with a Cognito JWT authorizer protecting every route except the health check.*

#### C7. `aws-lambda-functions.png`
- **Where:** AWS Console → search **Lambda**
- **Steps:** **Functions** → type `examhub` in the search box
- **Must be visible:** 4 functions (`examhub-prod-api`, `-marker`, `-notifier`, `-migrate`), runtime Python 3.13
- **Capture:** Area
- **Caption:** *Serverless compute: four Python 3.13 (arm64) Lambda functions.*

#### C8. `aws-lambda-vpc.png`
- **Where:** Lambda → click **examhub-prod-api**
- **Steps:** **Configuration** tab → left sub-menu **VPC**
- **Must be visible:** the VPC ID, **two subnets** named `examhub-prod-app-ap-south-1a` and `…-1b` (hover or click to show the names), and the security group
- **Capture:** Area
- **Caption:** *The API Lambda runs in private app subnets in two Availability Zones.*

### Two-AZ database

#### C9. `aws-rds-two-az.png`
- **Where:** AWS Console → search **RDS** → left menu **Databases**
- **Steps:** click `examhub-prod-db`, open the **Configuration** tab (or **Connectivity & security**)
- **Must be visible:** **Multi-AZ: Yes**, **Availability zone** (primary, e.g. `ap-south-1b`) and **Secondary zone** (standby, the other AZ, e.g. `ap-south-1a`), Status *Available*, *Publicly accessible: No*
- **Capture:** Area
- **Caption:** *RDS PostgreSQL Multi-AZ: primary in AZ A, synchronous standby in AZ B, not publicly accessible.*

#### C10. `aws-rds-config.png`
- **Where:** RDS → Databases → click **examhub-prod-db**
- **Steps:**
  1. **Configuration** tab: *Encryption: Enabled*, KMS key `examhub-prod`, parameter group `examhub-prod-pg17` (`rds.force_ssl=1`). Screenshot.
  2. **Maintenance & backups** tab: *Backup retention period*. Screenshot.
- **Capture:** Area (two images)
- **Caption:** *Encrypted at rest with a customer-managed KMS key, TLS enforced, automated backups.*

#### C11. `aws-rds-after-failover.png`
- **Where:** RDS → Databases (same view as C9)
- **Steps:** **after B5 has finished**, click the refresh icon ⟳
- **Must be visible:** **Availability zone** and **Secondary zone** are swapped compared with C9. The **Logs & events** tab also shows *Multi-AZ instance failover started / completed*.
- **Capture:** Area
- **Caption:** *After failover the primary has moved to the other Availability Zone.*

### Walkthrough 2 – 40 MB upload and tutor notification

#### C12. `aws-upload-40mb.png`
- **Where:** Browser window 1. Open a **new tab** (`Cmd + T`) with the site URL, so the exam tab stays open.
- **Steps:**
  1. In the **Assignments** table, row *Demo: Architecture Report* → **Choose File** → select `report.pdf` from the project folder
  2. Click **Upload**
  3. Take screenshot 1 **while the blue progress bar is moving**, or of the message "Uploaded report.pdf (40.0 MB)…"
  4. After about 5 seconds the page refreshes and *My submission* shows **uploaded: report.pdf**. Take screenshot 2.
- **Capture:** Window
- **Caption:** *A 40 MB file uploads directly from the browser to S3 with a presigned POST, bypassing API Gateway and Lambda.*

#### C13. `aws-s3-object.png`
- **Where:** AWS Console → search **S3** → **Buckets**
- **Steps:**
  1. Click `examhub-prod-uploads-<account id>`
  2. Click `submissions/` → the assignment folder → the submission folder → **report.pdf**
  3. On the **Properties** tab, scroll to **Server-side encryption settings** and **Tags**
- **Must be visible:** size ≈ 40 MB, encryption **SSE-KMS**, tag **validation = uploaded**
- **Capture:** Area (one or two images)
- **Caption:** *The upload is stored encrypted with KMS and tagged by the notifier after it validated the PDF header.*

#### C14. `aws-s3-lifecycle.png`
- **Where:** S3 → `examhub-prod-uploads-…` bucket
- **Steps:** **Management** tab → **Lifecycle rules** → click `submissions-5-year-retention`
- **Must be visible:** transitions after 30 days (Standard-IA), 180 days (Glacier Instant Retrieval), 730 days (Glacier Deep Archive), and expiration after 1826 days
- **Capture:** Area
- **Caption:** *Lifecycle rules keep records for 5 years at the lowest cost, then delete them.*

#### C15. `aws-tutor-email.png`
- **Where:** Gmail
- **Steps:** open the email **"New submission: Demo: Architecture Report"**. If it isn't in the inbox, check **Spam**.
- **Must be visible:** subject, sender, and body text "student1 submitted 'report.pdf' (40.0 MB)…"
- **Capture:** Area. **Blur your email address.**
- **Caption:** *S3 event → SQS → notifier Lambda → SES: the tutor is emailed when a submission arrives.*

#### C16. `aws-tutor-submissions.png`
- **Where:** Browser window 2 (private)
- **Steps:**
  1. Open the site URL → **Sign in** as `tutor1`
  2. Top menu **Assignments** → *Demo: Architecture Report* row → **Submissions**
- **Must be visible:** student1, report.pdf, 40.0 MB, status **uploaded**, **Download** button
- **Capture:** Window
- **Caption:** *The tutor sees the verified submission and downloads it through a 5-minute presigned link.*

### Asynchronous marking and results release

#### C17. `aws-sqs-queues.png`
- **Where:** AWS Console → search **SQS**
- **Steps:** **Queues** → type `examhub` in the search box
- **Must be visible:** four queues: `examhub-prod-marking`, `-marking-dlq`, `-notify`, `-notify-dlq`
- **Capture:** Area
- **Caption:** *SQS queues with dead-letter queues decouple marking and email from the API.*

#### Step (no screenshot): submit the exam
- Browser window 1 → the **exam tab** from C4 → **Submit exam** → **OK**. You return to the dashboard, showing "Submitted – awaiting results".

#### C18. `aws-marking.png`
- **Where:** Browser window 2 (tutor1)
- **Steps:**
  1. Top menu **Exams** → *Demo: Cloud Fundamentals Quiz* → **Attempts & marking**
  2. student1 shows status **auto marked** with the **MCQ score filled in** (done automatically by the marker Lambda). Screenshot 1.
  3. Type `2` in the short-answer **Mark** box → **Save marks**. The status becomes **marked** and the total updates. Screenshot 2.
- **Capture:** Window
- **Caption:** *MCQs are auto-marked asynchronously (SQS → marker Lambda); the tutor then marks the short answer.*

#### C19. `aws-results-email.png`
- **Where:** Browser window 2, then Gmail
- **Steps:**
  1. Top menu **Exams** → **Release results** on the quiz row → **OK**
  2. Within about 1 minute, Gmail receives **"Results released: Demo: Cloud Fundamentals Quiz"**. Open it.
- **Must be visible:** subject and body
- **Capture:** Area. **Blur your email.**
- **Caption:** *Releasing results queues a job; the notifier Lambda emails every student through SES.*

#### C20. `aws-student-result.png`
- **Where:** Browser window 1 (student1)
- **Steps:** reload the dashboard (`Cmd + R`)
- **Must be visible:** the quiz row shows **Result: x / 5** in green
- **Capture:** Window
- **Caption:** *The student sees the released result.*

#### C21. `aws-notifier-logs.png`
- **Where:** AWS Console → search **CloudWatch** → left menu **Logs → Log groups**
- **Steps:**
  1. Search `notifier` → click `/aws/lambda/examhub-prod-notifier`
  2. Click the **newest** log stream (top of the list)
- **Must be visible:** JSON lines with `"msg": "upload processed"` and `"msg": "results emails processed"`
- **Capture:** Area
- **Caption:** *Structured logs from the notifier Lambda for both async jobs.*

### Admin, security and monitoring

#### C22. `aws-admin-users.png`
- **Where:** Browser window 2
- **Steps:**
  1. Top-right **Sign out** → **Sign in** as `admin1`
  2. The **Users** page lists users and their roles. Fill in *Create user*: username `student2`, your email, role `student` → **Create user**. Screenshot 1.
  3. Top menu **Exam schedules**: editable *Opens / Closes / Minutes* fields. Screenshot 2.
- **Capture:** Window
- **Caption:** *Administrators manage users (Cognito) and exam schedules.*

#### C23. `aws-cognito-groups.png`
- **Where:** AWS Console → search **Cognito** → **User pools**
- **Steps:** click `examhub-prod-users` → **Groups** tab (or left menu *User management → Groups*)
- **Must be visible:** groups `admins`, `tutors`, `students` with their precedence
- **Capture:** Area
- **Caption:** *Role-based access control through Cognito groups.*

#### C24. `aws-waf.png`
- **Where:** AWS Console → search **WAF & Shield**
- **Steps:**
  1. Left menu **Web ACLs**
  2. **Important:** change the region dropdown on that page to **Global (CloudFront)**
  3. Click `examhub-prod-edge` → **Rules** tab
- **Must be visible:** 4 rules: `AWSCommonRules`, `AWSKnownBadInputs`, `AWSIpReputation`, `RateLimitPerIp`
- **Capture:** Area
- **Caption:** *AWS WAF managed rules and per-IP rate limiting at the edge.*

#### C25. `aws-secrets-kms.png`
- **Where:** AWS Console
- **Steps:**
  1. Search **Secrets Manager** → **Secrets**: two `examhub-prod/…` secrets. Screenshot 1.
  2. Search **KMS** → **Customer managed keys** → click alias `examhub-prod` → **Key rotation** tab: *Automatic rotation: Enabled*. Screenshot 2.
- **Capture:** Area. Blur the account ID.
- **Caption:** *Credentials are held in Secrets Manager; data is encrypted with a rotating customer-managed KMS key.*

#### C26. `aws-dashboard.png`
- **Where:** AWS Console → **CloudWatch** → left menu **Dashboards** → `examhub-prod`
- **Steps:** run the load test (B6) first. Then set the time range (top right) to **1h** and click refresh.
- **Must be visible:** all six graphs with data (API requests, latency, Lambda concurrency, database CPU/connections, queues, WAF)
- **Capture:** Full screen or Area
- **Caption:** *CloudWatch dashboard during the load test.*

#### C27. `aws-alarms.png`
- **Where:** CloudWatch → left menu **Alarms → All alarms**
- **Steps:** type `examhub` in the search box
- **Must be visible:** the alarm list (api-5xx, api-latency-p95, errors, throttles, dlq-not-empty, marking-backlog-age, db-cpu-high, db-connections-high) and their states
- **Capture:** Area
- **Caption:** *Alarms on errors, latency, throttling, dead-letter queues, queue age and database capacity, notifying through SNS.*

---

## Part D – CI/CD on GitHub

#### D1. `cicd-github-variables.png`
- **Where:** https://github.com/Wangpos/DSO303_Assignment2 → **Settings** (top tab) → left menu **Secrets and variables → Actions**
- **Steps:**
  1. **Variables** tab → **New repository variable**, three times, with values copied from the end of `evidence/cli-03-deploy.txt`:
     - `AWS_DEPLOY_ROLE_ARN`
     - `AWS_PLAN_ROLE_ARN`
     - `TF_STATE_BUCKET`
  2. **Secrets** tab → **New repository secret** → name `NOTIFICATION_EMAIL`, value your email
  3. Go back to the **Variables** tab
- **Must be visible:** the three variable names
- **Capture:** Area. Blur the account ID inside the ARNs.
- **Caption:** *The pipeline uses short-lived OIDC credentials; no AWS access keys are stored in GitHub.*

#### D2. `cicd-oidc-role.png`
- **Where:** AWS Console → search **IAM** → **Roles**
- **Steps:** search `examhub-github-deploy` → click it → **Trust relationships** tab
- **Must be visible:** `token.actions.githubusercontent.com` and `repo:Wangpos/DSO303_Assignment2:ref:refs/heads/main`
- **Capture:** Area. Blur the account ID.
- **Caption:** *Only workflows on the main branch of this repository can assume the deploy role.*

#### D3. `cicd-push-to-main.png`
- **Where:** Terminal, then the GitHub repo → **Actions** tab
- **Steps:**
  1. In Terminal:
     ```bash
     git add -A
     git commit -m "ExamHub platform"
     git push origin main
     ```
  2. On GitHub open **Actions**. A run named after your commit message appears with a yellow (running) dot.
- **Must be visible:** workflow `ci-cd`, your commit message, branch `main`, event "push"
- **Capture:** Window
- **Caption:** *A push to main automatically starts the pipeline.*

#### D4. `cicd-pipeline-success.png`
- **Where:** GitHub → Actions → click the run from D3
- **Steps:**
  1. Wait until both jobs **test** and **deploy** have green ticks (about 3–10 minutes)
  2. Click **deploy** → expand **Apply** and **Smoke test**
- **Must be visible:** green ticks; `Apply complete!` (or "No changes"); `healthy` in the smoke test
- **Capture:** Window
- **Caption:** *Pipeline: unit tests → terraform apply → CloudFront invalidation → smoke test, all green.*

#### D5. `cicd-redeploy-change.png`
- **Where:** editor, Terminal, GitHub, browser
- **Steps:**
  1. In `app/frontend/app.js` change the text `"Online exams & assignment submissions"` to something new, e.g. `"Online exams & assignment submissions – CST Exams"`
  2. `git commit -am "Change landing heading" && git push`
  3. Wait for the Actions run to turn green
  4. Open the site in a private window. The new heading shows.
- **Must be visible:** the new text on the live site and, next to it, the green Actions run for that commit
- **Capture:** Full screen with both windows side by side
- **Caption:** *A code change pushed to main reaches the live site with no manual steps.*

#### D6. `cicd-pr-plan.png` (optional)
- **Where:** Terminal, then GitHub → **Pull requests**
- **Steps:**
  1. `git checkout -b test-pr`, make any small change, `git commit -am "Test PR" && git push -u origin test-pr`
  2. On GitHub click **Compare & pull request** → **Create pull request**
  3. Wait for the checks
- **Must be visible:** checks **test** and **plan** passing on the pull request
- **Capture:** Window
- **Caption:** *Pull requests get tests and a read-only terraform plan before merging.*

---

## Part E – Cloud Architecture Lab (Task 3)

Build the design using [architecture/cloud-architecture-lab.md](architecture/cloud-architecture-lab.md) (build order, connections, simulation steps).

#### E1. `lab-01-full-architecture.png`
- **Where:** Cloud Architecture Lab, your canvas
- **Steps:** after placing every component, zoom out (or use "fit to screen") so the whole design fits
- **Must be visible:** all tiers: edge (Route 53, WAF, CloudFront), Cognito, API Gateway, Lambdas, Aurora writer + reader, S3 ×2, SQS ×2, SES, security and monitoring services
- **Capture:** Window
- **Caption:** *Complete architecture built in the Cloud Architecture Lab.*

#### E2. `lab-02-vpc-two-az.png`
- **Steps:** zoom into the VPC
- **Must be visible:** AZ A and AZ B, each with a public, private app and private data subnet; NAT gateway in each public subnet; Aurora writer in AZ A, reader in AZ B
- **Caption:** *VPC across two Availability Zones with three subnet tiers.*

#### E3. `lab-03-flow-exam-autosave.png`
- **Steps:** run the lab's simulation along Users → Route 53 → WAF → CloudFront → API Gateway → λ api → Aurora (and submit → SQS marking → λ marker)
- **Must be visible:** the highlighted path or request log showing success
- **Caption:** *Simulation of Walkthrough 1: opening an exam and autosaving answers.*

#### E4. `lab-04-flow-upload-notify.png`
- **Steps:** simulate Users → API (presigned URL) → Users → S3 uploads → SQS notify → λ notifier → SES → Tutor
- **Caption:** *Simulation of Walkthrough 2: 40 MB direct-to-S3 upload and tutor notification.*

#### E5. `lab-05-az-failure.png`
- **Steps:** disable / fail **AZ A** in the lab, then re-run the E3 flow
- **Must be visible:** AZ A marked failed, Aurora reader in AZ B promoted to writer, the request still succeeding
- **Caption:** *Loss of AZ A: Aurora fails over to AZ B and traffic continues through AZ B.*

#### E6. `lab-06-az-recovered.png`
- **Steps:** restore AZ A
- **Must be visible:** both AZs healthy again
- **Caption:** *Recovery after the Availability Zone returns.*

---

## Part F – Suggested order in the report

1. **Architecture design:** `architecture/diagram.png` + walkthroughs + peak/AZ text
2. **Service documentation:** table from `docs/services.md`
3. **Cloud Architecture Lab:** E1–E6
4. **AWS deployment:**
   - frontend: C1–C2
   - walkthrough 1: C3–C8
   - two-AZ database: C9–C11, B5
   - walkthrough 2: C12–C16
   - async processing: C17–C21
   - security and monitoring: C22–C27, B6
5. **IaC and CI/CD:** B1–B4, D1–D6
6. **Tear-down:** B7

## Checklist

- [ ] B1 · B2 · B3 (done) · B4 · B5 · B6 · B7
- [ ] C1 · C2 · C3 · C4 · C5 · C6 · C7 · C8
- [ ] C9 · C10 · C11
- [ ] C12 · C13 · C14 · C15 · C16
- [ ] C17 · C18 · C19 · C20 · C21
- [ ] C22 · C23 · C24 · C25 · C26 · C27
- [ ] D1 · D2 · D3 · D4 · D5 · (D6)
- [ ] E1 · E2 · E3 · E4 · E5 · E6
- [ ] All images renamed, in `evidence/`, and private details blurred
