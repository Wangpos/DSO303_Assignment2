#!/usr/bin/env python3
"""Generates architecture/diagram.svg (python3 architecture/generate_diagram.py).

Layout idea: each regional service sits directly above the Lambda that uses it
(API Gateway -> api, SQS marking -> marker, SQS notify -> notifier) so the
arrows run in straight vertical lanes."""
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1500, 1275
C = {
    "edge": "#8C4FFF", "compute": "#ED7100", "storage": "#3F8624", "db": "#2E73B8",
    "integ": "#E7157B", "sec": "#DD344C", "ops": "#7D3C98", "user": "#232F3E", "cicd": "#555555",
}
TINT = {
    "edge": "#F3EDFF", "compute": "#FFF3E6", "storage": "#EEF6E6", "db": "#E8F1FB",
    "integ": "#FDE8F2", "sec": "#FDEBED", "ops": "#F4ECF8", "user": "#EEF0F3", "cicd": "#F2F2F2",
}
out = []
labels = []  # zone/arrow labels drawn last, with a white halo, so lines never hide them


def box(x, y, w, h, title, sub="", kind="compute", bold=True):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{TINT[kind]}" stroke="{C[kind]}" stroke-width="1.8"/>')
    out.append(f'<rect x="{x}" y="{y}" width="6" height="{h}" rx="3" fill="{C[kind]}"/>')
    ty = y + (22 if sub else h / 2 + 5)
    out.append(f'<text x="{x + 14}" y="{ty}" class="{"t" if bold else "s"}">{escape(title)}</text>')
    for i, line in enumerate(sub.split("\n") if sub else []):
        out.append(f'<text x="{x + 14}" y="{y + 40 + i * 15}" class="s">{escape(line)}</text>')


def zone(x, y, w, h, label, color, dash="", fill="none", right=False, bottom=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{color}" stroke-width="1.6"{d}/>')
    tx = x + w - 12 if right else x + 12
    ty = y + h - 10 if bottom else y + 19
    anchor = ' text-anchor="end"' if right else ""
    labels.append(f'<text x="{tx}" y="{ty}" class="z halo" fill="{color}"{anchor}>{escape(label)}</text>')


def arrow(points, color="#444", dash="", both=False):
    path = "M " + " L ".join(f"{px},{py}" for px, py in points)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    start = ' marker-start="url(#ahs)"' if both else ""
    out.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.7"{d} marker-end="url(#ah)"{start}/>')


def label(x, y, text, color="#333", anchor="start"):
    labels.append(f'<text x="{x}" y="{y}" class="a halo" fill="{color}" text-anchor="{anchor}">{escape(text)}</text>')


# ------------------------------------------------------------------ title, users, edge, identity
out.append('<text x="30" y="27" class="h">ExamHub – online exams &amp; assignment platform · AWS production architecture</text>')
box(30, 70, 200, 92, "Users", "8,000 students · 400 staff\nstudents · tutors · admins\nbrowser, HTTPS only", "user")

zone(270, 58, 760, 122, "EDGE (global)", C["edge"], "6 4")
box(290, 85, 190, 80, "Amazon Route 53", "DNS alias record\nexams.<university>", "edge")
box(500, 85, 230, 80, "AWS WAF (web ACL)", "attached to the CloudFront distribution\nmanaged rules · per-IP rate limit", "sec")
box(750, 85, 260, 80, "Amazon CloudFront", "/       → S3 frontend (OAC)\n/api/* → API Gateway (no cache)", "edge")

zone(1060, 58, 410, 122, "IDENTITY", C["sec"], "6 4")
box(1080, 85, 370, 80, "Amazon Cognito user pool + hosted UI", "groups: students · tutors · admins\nOAuth code + PKCE · MFA optional · JWT", "sec")

arrow([(230, 120), (290, 120)], C["edge"])
label(236, 113, "HTTPS")
arrow([(480, 125), (500, 125)], C["edge"])
arrow([(730, 125), (750, 125)], C["edge"])
# browser is redirected to the Cognito hosted UI (lane y=54, under the email lane)
arrow([(200, 70), (200, 52), (1265, 52), (1265, 85)], C["sec"])
label(1060, 48, "sign-in: browser → Cognito hosted UI (OAuth code + PKCE) → JWT", C["sec"], "middle")

# ------------------------------------------------------------------ region
zone(20, 205, 1460, 880, "AWS REGION  ap-south-1 (Mumbai)", "#232F3E", "", "#FBFBFC", bottom=True)

# services row: aligned with the Lambda columns in AZ A (api 80-225, marker 235-380, notifier 390-535)
box(40, 240, 190, 92, "API Gateway (HTTP)", "JWT authorizer (Cognito)\n1,500 rps · burst 3,000\naccess logs", "integ")
box(240, 240, 150, 92, "SQS marking", "+ DLQ (5 tries)\nSSE · long poll\nconsumers ≤ 5", "integ")
box(400, 240, 150, 92, "SQS notify", "+ DLQ (5 tries)\nS3 events + results\nconsumers ≤ 2", "integ")
box(575, 240, 300, 92, "S3 – assignment uploads", "SSE-KMS · versioned · TLS-only\nObjectCreated → SQS notify\nIA 30 d → Glacier IR 180 d → Deep 2 y → del 5 y", "storage")
box(890, 240, 200, 92, "S3 – frontend", "static SPA (HTML/JS/CSS)\nprivate, CloudFront OAC\nSSE-S3", "storage")
box(1110, 240, 350, 92, "Amazon SES", "results-released emails to students\nnew-submission alert to tutor\nverified sender (DKIM/SPF in prod)", "integ")

# CloudFront -> S3 frontend (straight down) and -> API Gateway (lane y=192)
arrow([(970, 165), (970, 240)], C["edge"])
label(976, 222, "OAC")
arrow([(790, 165), (790, 192), (120, 192), (120, 240)], C["edge"])
label(130, 188, "/api/*  + origin-secret header (blocks WAF bypass)")
# Users -> S3 uploads direct (presigned POST), lane y=222
arrow([(60, 162), (60, 222), (700, 222), (700, 240)], C["storage"], "7 4")
label(130, 218, "presigned POST, ≤ 50 MB, browser → S3 directly (never through API/Lambda)", C["storage"])
# S3 uploads -> SQS notify
arrow([(575, 286), (550, 286)], C["integ"], "3 3")

# ------------------------------------------------------------------ VPC
VY = 395
zone(40, VY, 1060, 600, "VPC 10.20.0.0/16 · 2 AZs × 3 subnet tiers", C["edge"], "", "#FFFFFF", right=True)
for i, (ax, az) in enumerate([(55, "Availability Zone A (ap-south-1a)"), (580, "Availability Zone B (ap-south-1b)")]):
    zone(ax, VY + 30, 505, 470, az, "#1A73E8", "4 3", right=True)
    zone(ax + 12, VY + 58, 481, 72, f"Public subnet 10.20.{i}.0/24", "#3F8624", "", "#F4FAEF", right=True)
    box(ax + 265, VY + 84, 140, 36, "NAT gateway", "", "edge", bold=False)
    zone(ax + 12, VY + 145, 481, 175, f"Private app subnet 10.20.{10 + i}.0/24", "#1A73E8", "", "#F3F8FF", right=True)
    box(ax + 25, VY + 175, 145, 60, "λ api", "Python 3.13 · arm64", "compute")
    box(ax + 180, VY + 175, 145, 60, "λ marker", "auto-marks MCQs", "compute")
    box(ax + 335, VY + 175, 145, 60, "λ notifier", "validate + email", "compute")
    notes = [
        "SG: egress 443 + 5432 → DB SG only · X-Ray",
        "AWS APIs: S3 via gateway endpoint, SQS/SES/Secrets via NAT",
        "least-privilege IAM role per function",
        "provisioned concurrency in exam week" if i == 0 else "same functions – Lambda spreads across AZs",
    ]
    for n, text in enumerate(notes):
        out.append(f'<text x="{ax + 75}" y="{VY + 252 + n * 16}" class="s">{escape(text)}</text>')
    zone(ax + 12, VY + 335, 481, 150, f"Private data subnet 10.20.{20 + i}.0/24 · no internet route", C["db"], "", "#F1F6FC", right=True)
    if i == 0:
        box(ax + 40, VY + 368, 330, 80, "Aurora PostgreSQL – WRITER", "Serverless v2 · 2–16 ACU in exam week\nData API · KMS · rds.force_ssl", "db")
    else:
        box(ax + 115, VY + 368, 330, 80, "Aurora PostgreSQL – READER", "standby + read replica (promotion tier 1)\nauto-promoted in < 60 s if AZ A fails", "db")

# Aurora replication
arrow([(425, VY + 408), (695, VY + 408)], C["db"], both=True)
label(560, VY + 400, "shared cluster volume", C["db"], "middle")
box(70, VY + 515, 790, 56, "Aurora cluster volume: 6 copies across 3 AZs · PITR 35 days · AWS Backup daily 35 d + monthly 5 y", "", "db", bold=False)
box(875, VY + 515, 210, 56, "S3 gateway endpoint", "", "storage", bold=False)

# vertical lanes from the services row into AZ A
LAMBDA_TOP = VY + 175
arrow([(150, 332), (150, LAMBDA_TOP)], C["integ"])                       # API GW -> api
label(156, 372, "invoke")
arrow([(310, 332), (310, LAMBDA_TOP)], C["integ"])                       # SQS marking -> marker
label(316, 380, "poll")
arrow([(470, 332), (470, LAMBDA_TOP)], C["integ"])                       # SQS notify -> notifier
label(476, 380, "poll")
arrow([(200, LAMBDA_TOP), (200, 352), (265, 352), (265, 332)], C["integ"])  # api -> SQS marking
label(205, 364, "send")
arrow([(218, LAMBDA_TOP), (218, 344), (430, 344), (430, 332)], C["integ"])   # api -> SQS notify (results released)
label(330, 341, "results released", C["integ"], "middle")
arrow([(510, LAMBDA_TOP), (510, 372), (1285, 372), (1285, 332)], C["integ"])  # notifier -> SES
label(900, 367, "SendEmail", C["integ"], "middle")
arrow([(110, LAMBDA_TOP + 60), (110, VY + 368)], C["db"])                # api -> Aurora (Data API)
label(116, VY + 331, "Data API (HTTPS) · used by api, marker and notifier", C["db"])
# SES -> users (email), lane y=46 over the top
arrow([(1460, 270), (1478, 270), (1478, 36), (130, 36), (130, 70)], C["integ"], "2 3")
label(1100, 32, "email: results released · new submission → tutor · upload receipt", C["integ"])

# ------------------------------------------------------------------ security & ops column
zone(1115, VY, 350, 600, "SECURITY & OPERATIONS", C["ops"], "6 4", "#FFFFFF")
items = [
    ("AWS Secrets Manager", "DB credentials · CloudFront origin secret\nKMS-encrypted", "sec", 66),
    ("AWS KMS (customer-managed key)", "Aurora · S3 uploads · Secrets · Backup\nautomatic key rotation", "sec", 66),
    ("AWS IAM", "least-privilege role per Lambda\nGitHub OIDC roles (no static keys)", "sec", 66),
    ("Amazon CloudWatch + X-Ray", "dashboard · logs 90 d · VPC flow logs\nalarms: 5xx · p95 · throttles · DLQ ·\nqueue age · Aurora ACU", "ops", 82),
    ("Amazon SNS alarm topic", "email to on-call admin", "ops", 56),
    ("AWS Backup vault", "KMS · daily kept 35 d\nmonthly kept 5 years (1,826 d)", "ops", 66),
    ("ACM certificate (us-east-1)", "TLS 1.2+ on custom domain", "sec", 56),
]
y = VY + 32
for title, sub, kind, h in items:
    box(1130, y, 320, h, title, sub, kind)
    y += h + 12

# notes + legend inside region
out.append('<text x="40" y="1014" class="s">Production / exam week: NAT per AZ, Aurora 2–16 ACU, PITR 35 d, API provisioned concurrency 50, deletion protection.</text>')
out.append('<text x="40" y="1030" class="s" font-weight="700" fill="#2E73B8">Deployed build (AWS Free plan blocks private multi-instance Aurora): RDS PostgreSQL Multi-AZ db.t4g.micro – primary AZ A, synchronous standby AZ B,</text>')
out.append('<text x="40" y="1044" class="s" font-weight="700" fill="#2E73B8">same private data subnets, KMS + force_ssl, Lambdas connect with pg8000 over TLS · one NAT gateway · 1-day backups.</text>')
out.append('<text x="40" y="1062" class="s">In transit: TLS everywhere (CloudFront, API, S3 denies non-TLS, DB force_ssl). At rest: KMS (DB, uploads, Secrets, Backup), SSE-S3 frontend, SSE-SQS queues.</text>')
for i, (k, name) in enumerate([("edge", "network / edge"), ("compute", "compute"), ("db", "database"), ("storage", "storage"), ("integ", "integration"), ("sec", "security")]):
    x = 960 + i * 85
    out.append(f'<rect x="{x}" y="1066" width="11" height="11" fill="{C[k]}"/><text x="{x + 15}" y="1076" class="l">{name}</text>')

# ------------------------------------------------------------------ CI/CD
zone(20, 1100, 1460, 155, "CI/CD – a push to main redeploys everything", C["cicd"], "6 4")
steps = [
    (40, 210, "GitHub repository", "app/ · infra/ (Terraform)\ndocs/ · architecture/", "cicd"),
    (290, 270, "GitHub Actions", "PR: unit tests · fmt · plan\nmain: tests → terraform apply\n→ CloudFront invalidation → smoke test", "cicd"),
    (600, 250, "OIDC → IAM role (STS)", "deploy role: main branch only\nplan role: read-only for PRs\nshort-lived credentials", "sec"),
    (890, 260, "Terraform", "state in S3 (versioned, encrypted,\nnative lockfile)\nwhole stack reproducible", "cicd"),
    (1190, 270, "AWS account", "VPC · Lambda · API · Aurora · S3\nCloudFront · WAF · Cognito · SQS\nSES · alarms · backup", "cicd"),
]
for x, w, t, s, k in steps:
    box(x, 1135, w, 100, t, s, k)
for x1, x2 in [(250, 290), (560, 600), (850, 890), (1150, 1190)]:
    arrow([(x1, 1185), (x2, 1185)], C["cicd"])

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Helvetica, Arial, sans-serif">
<defs>
  <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#444"/></marker>
  <marker id="ahs" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="#444"/></marker>
  <style>
    .h {{ font-size: 21px; font-weight: 700; fill: #232F3E; }}
    .t {{ font-size: 13.5px; font-weight: 700; fill: #1c2433; }}
    .s {{ font-size: 11.5px; fill: #3a4558; }}
    .l {{ font-size: 10.5px; fill: #3a4558; }}
    .z {{ font-size: 12px; font-weight: 700; letter-spacing: .04em; }}
    .a {{ font-size: 11px; font-style: italic; }}
    .halo {{ paint-order: stroke; stroke: #ffffff; stroke-width: 4px; stroke-linejoin: round; }}
  </style>
</defs>
<rect width="{W}" height="{H}" fill="#ffffff"/>
{chr(10).join(out)}
{chr(10).join(labels)}
</svg>
'''
Path(__file__).with_name("diagram.svg").write_text(svg)
print("wrote diagram.svg")
