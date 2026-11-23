"""HTTP API Lambda (API Gateway HTTP API, payload v2, behind CloudFront)."""
import base64
import json
import os
import re
import traceback
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

from lib import db, logic

REGION = os.environ.get("AWS_REGION", "ap-south-1")
UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "")
MARKING_QUEUE = os.environ.get("MARKING_QUEUE", "")
NOTIFY_QUEUE = os.environ.get("NOTIFY_QUEUE", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
ORIGIN_SECRET_ARN = os.environ.get("ORIGIN_SECRET_ARN", "")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
AUTOSAVE_GRACE_SECONDS = 60

s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
sqs = boto3.client("sqs")
cognito = boto3.client("cognito-idp")
secrets = boto3.client("secretsmanager")

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_origin_secret_cache = None


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ----------------------------------------------------------------- helpers
def respond(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(body, default=str),
    }


def origin_secret():
    global _origin_secret_cache
    if _origin_secret_cache is None:
        _origin_secret_cache = secrets.get_secret_value(SecretId=ORIGIN_SECRET_ARN)["SecretString"]
    return _origin_secret_cache


def require(user, *roles):
    if not user or user["role"] not in roles:
        raise HttpError(403, "you do not have permission for this action")


def require_uuid(value, name="id"):
    if not isinstance(value, str) or not UUID_RE.match(value):
        raise HttpError(400, f"{name} must be a UUID")
    return value


def parse_time(value, name):
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise HttpError(400, f"{name} must be an ISO-8601 date/time")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def ensure_user(user):
    db.execute(
        "INSERT INTO users (sub, username, email, role) VALUES (:sub, :username, :email, :role) "
        "ON CONFLICT (sub) DO UPDATE SET email = EXCLUDED.email, role = EXCLUDED.role",
        sub=user["sub"], username=user["username"], email=user["email"], role=user["role"] or "student",
    )


def exam_for_staff(user, exam_id):
    exam = db.one(
        "SELECT id, title, description, duration_minutes, iso(opens_at) AS opens_at, iso(closes_at) AS closes_at, "
        "status, created_by, created_by_email FROM exams WHERE id = CAST(:id AS uuid)",
        id=exam_id,
    )
    if not exam:
        raise HttpError(404, "exam not found")
    if user["role"] != "admin" and exam["created_by"] != user["sub"]:
        raise HttpError(403, "only the exam owner or an admin can do this")
    return exam


def queue(url, messages):
    for i in range(0, len(messages), 10):
        sqs.send_message_batch(
            QueueUrl=url,
            Entries=[{"Id": str(n), "MessageBody": json.dumps(m)} for n, m in enumerate(messages[i : i + 10])],
        )


# ----------------------------------------------------------------- general
def health(req):
    result = {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
    if req["query"].get("deep"):
        rows = db.query("SELECT iso(now()) AS db_time", max_wait=20)
        result["db"] = "ok" if rows else "error"
        result["db_time"] = rows[0]["db_time"] if rows else None
    return result


def me(req):
    return req["user"]


# ----------------------------------------------------------------- exams
def list_exams(req):
    user = req["user"]
    if user["role"] == "student":
        return db.query(
            "SELECT e.id, e.title, e.description, e.duration_minutes, iso(e.opens_at) AS opens_at, "
            "iso(e.closes_at) AS closes_at, e.status, "
            "(now() >= COALESCE(e.opens_at, '-infinity') AND now() <= COALESCE(e.closes_at, 'infinity')) AS is_open, "
            "a.id AS attempt_id, a.status AS attempt_status, iso(a.deadline_at) AS deadline_at, "
            "CASE WHEN e.status = 'results_released' THEN a.total_score END AS total_score, "
            "CASE WHEN e.status = 'results_released' THEN a.max_score END AS max_score "
            "FROM exams e LEFT JOIN attempts a ON a.exam_id = e.id AND a.student_sub = :sub "
            "WHERE e.status <> 'draft' ORDER BY e.opens_at DESC NULLS LAST",
            sub=user["sub"],
        )
    require(user, "tutor", "admin")
    return db.query(
        "SELECT e.id, e.title, e.duration_minutes, iso(e.opens_at) AS opens_at, iso(e.closes_at) AS closes_at, "
        "e.status, e.created_by_email, "
        "(SELECT count(*) FROM attempts a WHERE a.exam_id = e.id) AS attempts, "
        "(SELECT count(*) FROM attempts a WHERE a.exam_id = e.id AND a.status <> 'in_progress') AS submitted "
        "FROM exams e WHERE (:is_admin OR e.created_by = :sub) ORDER BY e.created_at DESC",
        is_admin=user["role"] == "admin", sub=user["sub"],
    )


def create_exam(req):
    user, body = req["user"], req["body"]
    require(user, "tutor", "admin")
    errors = logic.validate_exam(body)
    if errors:
        raise HttpError(400, "; ".join(errors))
    opens, closes = parse_time(body.get("opens_at"), "opens_at"), parse_time(body.get("closes_at"), "closes_at")
    if opens and closes and closes <= opens:
        raise HttpError(400, "closes_at must be after opens_at")
    ensure_user(user)
    exam = db.one(
        "INSERT INTO exams (title, description, duration_minutes, opens_at, closes_at, created_by, created_by_email) "
        "VALUES (:t, :d, :dur, CAST(:o AS timestamptz), CAST(:c AS timestamptz), :sub, :email) RETURNING id",
        t=body["title"].strip(), d=body.get("description"), dur=int(body["duration_minutes"]),
        o=opens, c=closes, sub=user["sub"], email=user["email"],
    )
    db.batch(
        "INSERT INTO questions (exam_id, position, kind, prompt, options, correct_option, marks) "
        "VALUES (CAST(:exam AS uuid), :pos, :kind, :prompt, CAST(:options AS jsonb), :correct, :marks)",
        [
            {
                "exam": exam["id"], "pos": i, "kind": q["kind"], "prompt": q["prompt"].strip(),
                "options": json.dumps(q["options"]) if q["kind"] == "mcq" else None,
                "correct": q.get("correct_option") if q["kind"] == "mcq" else None,
                "marks": float(q.get("marks") or 1),
            }
            for i, q in enumerate(body["questions"], start=1)
        ],
    )
    return {"id": exam["id"]}


def get_exam(req):
    exam = exam_for_staff(req["user"], require_uuid(req["params"]["exam_id"]))
    questions = db.query(
        "SELECT id, position, kind, prompt, options, correct_option, marks FROM questions "
        "WHERE exam_id = CAST(:id AS uuid) ORDER BY position",
        id=exam["id"],
    )
    for q in questions:
        q["options"] = db.jsonb(q["options"])
    exam["questions"] = questions
    return exam


def update_schedule(req):
    user, body = req["user"], req["body"]
    require(user, "tutor", "admin")
    exam = exam_for_staff(user, require_uuid(req["params"]["exam_id"]))
    opens, closes = parse_time(body.get("opens_at"), "opens_at"), parse_time(body.get("closes_at"), "closes_at")
    if opens and closes and closes <= opens:
        raise HttpError(400, "closes_at must be after opens_at")
    duration = body.get("duration_minutes")
    db.execute(
        "UPDATE exams SET opens_at = CAST(:o AS timestamptz), closes_at = CAST(:c AS timestamptz), "
        "duration_minutes = COALESCE(:d, duration_minutes) WHERE id = CAST(:id AS uuid)",
        o=opens, c=closes, d=int(duration) if duration else None, id=exam["id"],
    )
    return {"id": exam["id"], "opens_at": opens, "closes_at": closes}


# ----------------------------------------------------------------- attempts (students)
def _attempt_payload(attempt):
    questions = db.query(
        "SELECT id, position, kind, prompt, options, marks FROM questions "
        "WHERE exam_id = CAST(:id AS uuid) ORDER BY position",
        id=attempt["exam_id"],
    )
    for q in questions:
        q["options"] = db.jsonb(q["options"])
    answers = db.query(
        "SELECT question_id, response FROM answers WHERE attempt_id = CAST(:id AS uuid)", id=attempt["id"]
    )
    return {
        "attempt": attempt,
        "questions": questions,
        "answers": {a["question_id"]: a["response"] for a in answers},
    }


def start_attempt(req):
    user = req["user"]
    require(user, "student")
    exam_id = require_uuid(req["params"]["exam_id"])
    exam = db.one(
        "SELECT id, title, status, "
        "(now() >= COALESCE(opens_at, '-infinity') AND now() <= COALESCE(closes_at, 'infinity')) AS is_open "
        "FROM exams WHERE id = CAST(:id AS uuid) AND status <> 'draft'",
        id=exam_id,
    )
    if not exam:
        raise HttpError(404, "exam not found")

    select_attempt = (
        "SELECT a.id, a.exam_id, a.status, iso(a.started_at) AS started_at, iso(a.deadline_at) AS deadline_at, "
        "iso(now()) AS server_time, e.title, e.duration_minutes "
        "FROM attempts a JOIN exams e ON e.id = a.exam_id "
        "WHERE a.exam_id = CAST(:exam AS uuid) AND a.student_sub = :sub"
    )
    attempt = db.one(select_attempt, exam=exam_id, sub=user["sub"])
    if not attempt:
        if not exam["is_open"]:
            raise HttpError(403, "this exam is not open")
        ensure_user(user)
        db.execute(
            "INSERT INTO attempts (exam_id, student_sub, student_name, student_email, deadline_at, max_score) "
            "SELECT e.id, :sub, :name, :email, "
            "LEAST(now() + make_interval(mins => e.duration_minutes), COALESCE(e.closes_at, 'infinity')), "
            "(SELECT COALESCE(sum(marks), 0) FROM questions q WHERE q.exam_id = e.id) "
            "FROM exams e WHERE e.id = CAST(:exam AS uuid) "
            "ON CONFLICT (exam_id, student_sub) DO NOTHING",
            sub=user["sub"], name=user["username"], email=user["email"], exam=exam_id,
        )
        attempt = db.one(select_attempt, exam=exam_id, sub=user["sub"])
    if attempt["status"] != "in_progress":
        raise HttpError(409, "you have already submitted this exam")
    return _attempt_payload(attempt)


def _own_attempt(user, attempt_id):
    attempt = db.one(
        "SELECT id, exam_id, status, (now() <= deadline_at + make_interval(secs => :grace)) AS within_time "
        "FROM attempts WHERE id = CAST(:id AS uuid) AND student_sub = :sub",
        id=attempt_id, sub=user["sub"], grace=AUTOSAVE_GRACE_SECONDS,
    )
    if not attempt:
        raise HttpError(404, "attempt not found")
    return attempt


def _save(attempt_id, answers):
    if not isinstance(answers, list) or len(answers) > 500:
        raise HttpError(400, "answers must be a list (max 500)")
    rows = []
    for a in answers:
        qid = require_uuid(a.get("question_id"), "question_id")
        response = a.get("response")
        rows.append({"a": attempt_id, "q": qid, "r": None if response is None else str(response)[:10000]})
    db.batch(
        "INSERT INTO answers (attempt_id, question_id, response, saved_at) "
        "SELECT t.id, q.id, :r, now() FROM attempts t JOIN questions q ON q.exam_id = t.exam_id "
        "WHERE t.id = CAST(:a AS uuid) AND q.id = CAST(:q AS uuid) "
        "ON CONFLICT (attempt_id, question_id) DO UPDATE SET response = EXCLUDED.response, saved_at = now()",
        rows,
    )
    return len(rows)


def save_answers(req):
    user = req["user"]
    require(user, "student")
    attempt = _own_attempt(user, require_uuid(req["params"]["attempt_id"]))
    if attempt["status"] != "in_progress":
        raise HttpError(409, "this attempt has already been submitted")
    if not attempt["within_time"]:
        raise HttpError(409, "time is up for this exam")
    saved = _save(attempt["id"], req["body"].get("answers", []))
    return {"saved": saved, "saved_at": datetime.now(timezone.utc).isoformat()}


def submit_attempt(req):
    user = req["user"]
    require(user, "student")
    attempt = _own_attempt(user, require_uuid(req["params"]["attempt_id"]))
    if attempt["status"] != "in_progress":
        return {"status": attempt["status"]}
    if attempt["within_time"] and req["body"].get("answers"):
        _save(attempt["id"], req["body"]["answers"])
    updated = db.execute(
        "UPDATE attempts SET status = 'submitted', submitted_at = now() "
        "WHERE id = CAST(:id AS uuid) AND status = 'in_progress'",
        id=attempt["id"],
    )
    if updated:
        queue(MARKING_QUEUE, [{"attempt_id": attempt["id"]}])
    return {"status": "submitted"}


# ----------------------------------------------------------------- marking (tutors)
def list_attempts(req):
    user = req["user"]
    require(user, "tutor", "admin")
    exam = exam_for_staff(user, require_uuid(req["params"]["exam_id"]))
    attempts = db.query(
        "SELECT id, student_name, student_email, status, iso(submitted_at) AS submitted_at, "
        "mcq_score, short_score, total_score, max_score FROM attempts "
        "WHERE exam_id = CAST(:id AS uuid) ORDER BY student_name",
        id=exam["id"],
    )
    short_questions = db.query(
        "SELECT id, position, prompt, marks FROM questions "
        "WHERE exam_id = CAST(:id AS uuid) AND kind = 'short' ORDER BY position",
        id=exam["id"],
    )
    responses = db.query(
        "SELECT an.attempt_id, an.question_id, an.response, an.short_mark FROM answers an "
        "JOIN questions q ON q.id = an.question_id WHERE q.exam_id = CAST(:id AS uuid) AND q.kind = 'short'",
        id=exam["id"],
    )
    by_attempt = {}
    for r in responses:
        by_attempt.setdefault(r["attempt_id"], {})[r["question_id"]] = {
            "response": r["response"], "mark": r["short_mark"],
        }
    for a in attempts:
        a["short_answers"] = by_attempt.get(a["id"], {})
    return {"exam": exam, "short_questions": short_questions, "attempts": attempts}


def mark_attempt(req):
    user = req["user"]
    require(user, "tutor", "admin")
    attempt_id = require_uuid(req["params"]["attempt_id"])
    attempt = db.one("SELECT id, exam_id, status FROM attempts WHERE id = CAST(:id AS uuid)", id=attempt_id)
    if not attempt:
        raise HttpError(404, "attempt not found")
    exam_for_staff(user, attempt["exam_id"])
    if attempt["status"] == "in_progress":
        raise HttpError(409, "the student has not submitted yet")
    max_marks = {
        q["id"]: q["marks"]
        for q in db.query(
            "SELECT id, marks FROM questions WHERE exam_id = CAST(:id AS uuid) AND kind = 'short'",
            id=attempt["exam_id"],
        )
    }
    rows = []
    for m in req["body"].get("marks", []):
        qid = require_uuid(m.get("question_id"), "question_id")
        if qid not in max_marks:
            raise HttpError(400, "question is not a short-answer question in this exam")
        mark = float(m.get("mark", 0))
        if not 0 <= mark <= max_marks[qid]:
            raise HttpError(400, f"mark must be between 0 and {max_marks[qid]}")
        rows.append({"a": attempt_id, "q": qid, "m": mark})
    db.batch(
        "INSERT INTO answers (attempt_id, question_id, response, short_mark) "
        "VALUES (CAST(:a AS uuid), CAST(:q AS uuid), NULL, :m) "
        "ON CONFLICT (attempt_id, question_id) DO UPDATE SET short_mark = EXCLUDED.short_mark",
        rows,
    )
    db.execute(
        "UPDATE attempts t SET short_score = s.total, total_score = COALESCE(t.mcq_score, 0) + s.total, "
        "status = 'marked' FROM ("
        "  SELECT COALESCE(sum(an.short_mark), 0) AS total FROM answers an "
        "  JOIN questions q ON q.id = an.question_id "
        "  WHERE an.attempt_id = CAST(:id AS uuid) AND q.kind = 'short') s "
        "WHERE t.id = CAST(:id AS uuid)",
        id=attempt_id,
    )
    return {"id": attempt_id, "status": "marked"}


def release_results(req):
    user = req["user"]
    require(user, "tutor", "admin")
    exam = exam_for_staff(user, require_uuid(req["params"]["exam_id"]))
    sitting = db.one(
        "SELECT count(*) AS n FROM attempts WHERE exam_id = CAST(:id AS uuid) "
        "AND status = 'in_progress' AND deadline_at >= now()",
        id=exam["id"],
    )["n"]
    if sitting:
        raise HttpError(409, f"{sitting} student(s) are still sitting this exam")
    # Students who ran out of time without pressing submit are submitted at their deadline.
    expired = db.query(
        "UPDATE attempts SET status = 'submitted', submitted_at = deadline_at "
        "WHERE exam_id = CAST(:id AS uuid) AND status = 'in_progress' RETURNING id",
        id=exam["id"],
    )
    if expired:
        queue(MARKING_QUEUE, [{"attempt_id": a["id"]} for a in expired])
    db.execute(
        "UPDATE exams SET status = 'results_released', released_at = now() WHERE id = CAST(:id AS uuid)",
        id=exam["id"],
    )
    queue(NOTIFY_QUEUE, [{"type": "results_released", "exam_id": exam["id"]}])
    return {"status": "results_released", "auto_submitted": len(expired)}


# ----------------------------------------------------------------- assignments
def list_assignments(req):
    user = req["user"]
    if user["role"] == "student":
        return db.query(
            "SELECT a.id, a.title, a.description, iso(a.due_at) AS due_at, "
            "s.id AS submission_id, s.filename, s.status AS submission_status, iso(s.created_at) AS submitted_at "
            "FROM assignments a LEFT JOIN LATERAL ("
            "  SELECT id, filename, status, created_at FROM submissions "
            "  WHERE assignment_id = a.id AND student_sub = :sub ORDER BY created_at DESC LIMIT 1) s ON true "
            "ORDER BY a.due_at NULLS LAST",
            sub=user["sub"],
        )
    require(user, "tutor", "admin")
    return db.query(
        "SELECT a.id, a.title, a.description, iso(a.due_at) AS due_at, a.created_by_email, "
        "(SELECT count(*) FROM submissions s WHERE s.assignment_id = a.id AND s.status = 'uploaded') AS submissions "
        "FROM assignments a WHERE (:is_admin OR a.created_by = :sub) ORDER BY a.created_at DESC",
        is_admin=user["role"] == "admin", sub=user["sub"],
    )


def create_assignment(req):
    user, body = req["user"], req["body"]
    require(user, "tutor", "admin")
    title = (body.get("title") or "").strip()
    if not title:
        raise HttpError(400, "title is required")
    ensure_user(user)
    row = db.one(
        "INSERT INTO assignments (title, description, due_at, created_by, created_by_email) "
        "VALUES (:t, :d, CAST(:due AS timestamptz), :sub, :email) RETURNING id",
        t=title, d=body.get("description"), due=parse_time(body.get("due_at"), "due_at"),
        sub=user["sub"], email=user["email"],
    )
    return {"id": row["id"]}


def request_upload(req):
    """Returns a presigned POST so the browser uploads straight to S3 (the 50 MB
    file never passes through API Gateway/Lambda, which cap payloads at 6-10 MB)."""
    user, body = req["user"], req["body"]
    require(user, "student")
    assignment_id = require_uuid(req["params"]["assignment_id"])
    if not db.one("SELECT id FROM assignments WHERE id = CAST(:id AS uuid)", id=assignment_id):
        raise HttpError(404, "assignment not found")
    filename = logic.safe_filename(body.get("filename"))
    content_type, error = logic.validate_upload_request(filename, body.get("size"), MAX_UPLOAD_MB)
    if error:
        raise HttpError(400, error)
    ensure_user(user)
    submission_id = str(uuid.uuid4())
    key = f"submissions/{assignment_id}/{submission_id}/{filename}"
    db.execute(
        "INSERT INTO submissions (id, assignment_id, student_sub, student_name, student_email, s3_key, filename, size_bytes) "
        "VALUES (CAST(:id AS uuid), CAST(:a AS uuid), :sub, :name, :email, :key, :fn, :size)",
        id=submission_id, a=assignment_id, sub=user["sub"], name=user["username"], email=user["email"],
        key=key, fn=filename, size=int(body["size"]),
    )
    post = s3.generate_presigned_post(
        Bucket=UPLOAD_BUCKET,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, MAX_UPLOAD_MB * 1024 * 1024]],
        ExpiresIn=900,
    )
    return {"submission_id": submission_id, "upload": post}


def list_submissions(req):
    user = req["user"]
    require(user, "tutor", "admin")
    assignment_id = require_uuid(req["params"]["assignment_id"])
    assignment = db.one(
        "SELECT id, title, created_by FROM assignments WHERE id = CAST(:id AS uuid)", id=assignment_id
    )
    if not assignment:
        raise HttpError(404, "assignment not found")
    if user["role"] != "admin" and assignment["created_by"] != user["sub"]:
        raise HttpError(403, "only the assignment owner or an admin can view submissions")
    rows = db.query(
        "SELECT id, student_name, student_email, filename, size_bytes, status, s3_key, "
        "iso(created_at) AS created_at, iso(uploaded_at) AS uploaded_at FROM submissions "
        "WHERE assignment_id = CAST(:id AS uuid) AND status <> 'pending' ORDER BY created_at DESC",
        id=assignment_id,
    )
    for r in rows:
        key = r.pop("s3_key")
        if r["status"] == "uploaded":
            r["download_url"] = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": UPLOAD_BUCKET, "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{r["filename"]}"',
                },
                ExpiresIn=300,
            )
    return {"assignment": assignment, "submissions": rows}


def my_submissions(req):
    user = req["user"]
    require(user, "student")
    return db.query(
        "SELECT s.id, a.title AS assignment, s.filename, s.size_bytes, s.status, iso(s.created_at) AS created_at "
        "FROM submissions s JOIN assignments a ON a.id = s.assignment_id "
        "WHERE s.student_sub = :sub ORDER BY s.created_at DESC",
        sub=user["sub"],
    )


# ----------------------------------------------------------------- admin
def list_users(req):
    require(req["user"], "admin")
    roles = {}
    for group in ("students", "tutors", "admins"):
        token = None
        while True:
            kwargs = {"UserPoolId": USER_POOL_ID, "GroupName": group, "Limit": 60}
            if token:
                kwargs["NextToken"] = token
            res = cognito.list_users_in_group(**kwargs)
            for u in res["Users"]:
                roles.setdefault(u["Username"], []).append(group)
            token = res.get("NextToken")
            if not token:
                break
    users, token = [], None
    while len(users) < 1000:
        kwargs = {"UserPoolId": USER_POOL_ID, "Limit": 60}
        if token:
            kwargs["PaginationToken"] = token
        res = cognito.list_users(**kwargs)
        for u in res["Users"]:
            attrs = {a["Name"]: a["Value"] for a in u.get("Attributes", [])}
            users.append({
                "username": u["Username"],
                "email": attrs.get("email"),
                "status": u["UserStatus"],
                "enabled": u["Enabled"],
                "role": logic.primary_role(roles.get(u["Username"], [])),
                "created": u["UserCreateDate"].isoformat(),
            })
        token = res.get("PaginationToken")
        if not token:
            break
    return sorted(users, key=lambda u: u["username"])


def create_user(req):
    body = req["body"]
    require(req["user"], "admin")
    username = (body.get("username") or "").strip().lower()
    email = (body.get("email") or "").strip()
    role = body.get("role")
    if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
        raise HttpError(400, "username must be 3-64 characters: letters, digits, . _ -")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HttpError(400, "a valid email is required")
    if role not in ("student", "tutor", "admin"):
        raise HttpError(400, "role must be student, tutor or admin")
    try:
        cognito.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=username,
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
            DesiredDeliveryMediums=["EMAIL"],
        )
    except cognito.exceptions.UsernameExistsException:
        raise HttpError(409, "that username already exists")
    cognito.admin_add_user_to_group(UserPoolId=USER_POOL_ID, Username=username, GroupName=role + "s")
    return {"username": username, "role": role, "invited": email}


# ----------------------------------------------------------------- routing
U = r"[0-9a-fA-F-]{36}"
ROUTES = [
    ("GET", r"/api/health", health),
    ("GET", r"/api/me", me),
    ("GET", r"/api/exams", list_exams),
    ("POST", r"/api/exams", create_exam),
    ("GET", rf"/api/exams/(?P<exam_id>{U})", get_exam),
    ("PATCH", rf"/api/exams/(?P<exam_id>{U})/schedule", update_schedule),
    ("POST", rf"/api/exams/(?P<exam_id>{U})/attempts", start_attempt),
    ("GET", rf"/api/exams/(?P<exam_id>{U})/attempts", list_attempts),
    ("POST", rf"/api/exams/(?P<exam_id>{U})/release", release_results),
    ("PUT", rf"/api/attempts/(?P<attempt_id>{U})/answers", save_answers),
    ("POST", rf"/api/attempts/(?P<attempt_id>{U})/submit", submit_attempt),
    ("PUT", rf"/api/attempts/(?P<attempt_id>{U})/marks", mark_attempt),
    ("GET", r"/api/assignments", list_assignments),
    ("POST", r"/api/assignments", create_assignment),
    ("POST", rf"/api/assignments/(?P<assignment_id>{U})/uploads", request_upload),
    ("GET", rf"/api/assignments/(?P<assignment_id>{U})/submissions", list_submissions),
    ("GET", r"/api/submissions", my_submissions),
    ("GET", r"/api/admin/users", list_users),
    ("POST", r"/api/admin/users", create_user),
]
PUBLIC = {health}


def _user_from(event):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if not claims.get("sub"):
        return None
    groups = logic.parse_groups(claims.get("cognito:groups"))
    return {
        "sub": claims["sub"],
        "username": claims.get("cognito:username") or claims.get("username"),
        "email": claims.get("email"),
        "groups": groups,
        "role": logic.primary_role(groups),
    }


def handler(event, _context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if ORIGIN_SECRET_ARN and headers.get("x-origin-verify") != origin_secret():
        return respond(403, {"error": "requests must come through CloudFront"})

    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "").rstrip("/") or "/"
    fn, params = logic.match_route(ROUTES, method, path)
    if not fn:
        return respond(404, {"error": f"no route for {method} {path}"})

    user = _user_from(event)
    if fn not in PUBLIC and not user:
        return respond(401, {"error": "sign in required"})

    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and raw:
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return respond(400, {"error": "body must be a JSON object"})

    req = {"user": user, "params": params, "body": body, "query": event.get("queryStringParameters") or {}}
    try:
        return respond(200, fn(req))
    except HttpError as err:
        return respond(err.status, {"error": err.message})
    except db.DatabaseUnavailable:
        return respond(503, {"error": "database is temporarily unavailable - your answers are kept in the browser; retrying"})
    except Exception:  # noqa: BLE001
        print(json.dumps({"level": "error", "path": path, "trace": traceback.format_exc()}))
        return respond(500, {"error": "internal error"})
