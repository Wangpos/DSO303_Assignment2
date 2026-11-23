"""Idempotent schema migration + demo seed. Invoked by Terraform on every deploy."""
import json

from lib import db

SCHEMA = [
    """CREATE OR REPLACE FUNCTION iso(t timestamptz) RETURNS text
       LANGUAGE sql IMMUTABLE AS
       $$ SELECT to_char(t AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24":"MI":"SS"Z"') $$""",
    # (colons are quoted so the driver doesn't read ':MI' as a named parameter)
    """CREATE TABLE IF NOT EXISTS users (
         sub         text PRIMARY KEY,
         username    text NOT NULL,
         email       text,
         role        text NOT NULL,
         created_at  timestamptz NOT NULL DEFAULT now()
       )""",
    """CREATE TABLE IF NOT EXISTS exams (
         id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         title            text NOT NULL,
         description      text,
         duration_minutes int  NOT NULL CHECK (duration_minutes BETWEEN 1 AND 600),
         opens_at         timestamptz,
         closes_at        timestamptz,
         status           text NOT NULL DEFAULT 'scheduled'
                          CHECK (status IN ('draft','scheduled','results_released')),
         created_by       text NOT NULL,
         created_by_email text,
         created_at       timestamptz NOT NULL DEFAULT now(),
         released_at      timestamptz
       )""",
    """CREATE TABLE IF NOT EXISTS questions (
         id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         exam_id        uuid NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
         position       int  NOT NULL,
         kind           text NOT NULL CHECK (kind IN ('mcq','short')),
         prompt         text NOT NULL,
         options        jsonb,
         correct_option int,
         marks          double precision NOT NULL DEFAULT 1
       )""",
    "CREATE INDEX IF NOT EXISTS questions_exam_idx ON questions(exam_id, position)",
    """CREATE TABLE IF NOT EXISTS attempts (
         id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         exam_id       uuid NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
         student_sub   text NOT NULL,
         student_name  text,
         student_email text,
         started_at    timestamptz NOT NULL DEFAULT now(),
         deadline_at   timestamptz NOT NULL,
         submitted_at  timestamptz,
         status        text NOT NULL DEFAULT 'in_progress'
                       CHECK (status IN ('in_progress','submitted','auto_marked','marked')),
         mcq_score     double precision,
         short_score   double precision,
         total_score   double precision,
         max_score     double precision,
         results_emailed_at timestamptz,
         UNIQUE (exam_id, student_sub)
       )""",
    """CREATE TABLE IF NOT EXISTS answers (
         attempt_id  uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
         question_id uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
         response    text,
         saved_at    timestamptz NOT NULL DEFAULT now(),
         short_mark  double precision,
         PRIMARY KEY (attempt_id, question_id)
       )""",
    """CREATE TABLE IF NOT EXISTS assignments (
         id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         title            text NOT NULL,
         description      text,
         due_at           timestamptz,
         created_by       text NOT NULL,
         created_by_email text,
         created_at       timestamptz NOT NULL DEFAULT now()
       )""",
    """CREATE TABLE IF NOT EXISTS submissions (
         id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
         assignment_id uuid NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
         student_sub   text NOT NULL,
         student_name  text,
         student_email text,
         s3_key        text NOT NULL UNIQUE,
         filename      text NOT NULL,
         size_bytes    bigint,
         status        text NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','uploaded','rejected')),
         created_at    timestamptz NOT NULL DEFAULT now(),
         uploaded_at   timestamptz
       )""",
    "CREATE INDEX IF NOT EXISTS submissions_assignment_idx ON submissions(assignment_id)",
    "CREATE INDEX IF NOT EXISTS submissions_student_idx ON submissions(student_sub)",
]

DEMO_EXAM_QUESTIONS = [
    ("mcq", "Which AWS service distributes static content from edge locations?",
     ["Amazon RDS", "Amazon CloudFront", "AWS Lambda", "Amazon SQS"], 1, 1),
    ("mcq", "How many Availability Zones does this platform's VPC span?",
     ["One", "Two", "Four", "It is region-less"], 1, 1),
    ("mcq", "Which service decouples marking from the API?",
     ["Amazon SQS", "Amazon Route 53", "AWS WAF", "Amazon Cognito"], 0, 1),
    ("short", "In one or two sentences, explain what RPO means.", None, None, 2),
]


def _seed(seed):
    if db.one("SELECT id FROM exams WHERE title = 'Demo: Cloud Fundamentals Quiz'"):
        return "seed already present"
    db.execute(
        "INSERT INTO users (sub, username, email, role) VALUES (:sub, :u, :e, 'tutor') "
        "ON CONFLICT (sub) DO NOTHING",
        sub=seed["tutor_sub"], u=seed["tutor_name"], e=seed["tutor_email"],
    )
    exam = db.one(
        "INSERT INTO exams (title, description, duration_minutes, opens_at, closes_at, created_by, created_by_email) "
        "VALUES ('Demo: Cloud Fundamentals Quiz', 'Seeded demo exam - 4 questions', 20, now() - interval '1 hour', "
        "now() + interval '30 days', :sub, :email) RETURNING id",
        sub=seed["tutor_sub"], email=seed["tutor_email"],
    )
    db.batch(
        "INSERT INTO questions (exam_id, position, kind, prompt, options, correct_option, marks) "
        "VALUES (CAST(:exam AS uuid), :pos, :kind, :prompt, CAST(:options AS jsonb), :correct, :marks)",
        [
            {"exam": exam["id"], "pos": i, "kind": k, "prompt": p,
             "options": json.dumps(o) if o else None, "correct": c, "marks": float(m)}
            for i, (k, p, o, c, m) in enumerate(DEMO_EXAM_QUESTIONS, start=1)
        ],
    )
    db.execute(
        "INSERT INTO assignments (title, description, due_at, created_by, created_by_email) "
        "VALUES ('Demo: Architecture Report', 'Upload your report as PDF or ZIP (max 50 MB).', "
        "now() + interval '14 days', :sub, :email)",
        sub=seed["tutor_sub"], email=seed["tutor_email"],
    )
    return "seeded demo exam and assignment"


def handler(event, _context):
    # The database may still be finishing its first start - allow up to 4 minutes.
    db.query("SELECT 1 AS ok", max_wait=240)
    for statement in SCHEMA:
        db.execute(statement)
    result = {"status": "ok", "statements": len(SCHEMA)}
    if event.get("seed"):
        result["seed"] = _seed(event["seed"])
    print(json.dumps(result))
    return result
