"""SQS consumer for the notify queue. Handles two message types:

1. S3 ObjectCreated events for assignment uploads -> verify the file, mark the
   submission uploaded (or rejected) and email the tutor + a student receipt.
2. {"type": "results_released", "exam_id": ...} -> email every student who sat
   the exam that results are available.
"""
import json
import os
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

from lib import db, logic

UPLOAD_BUCKET = os.environ.get("UPLOAD_BUCKET", "")
SENDER = os.environ.get("SENDER_EMAIL", "")
SITE_URL = os.environ.get("SITE_URL", "")
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024

s3 = boto3.client("s3")
ses = boto3.client("sesv2")


def log(level, msg, **kw):
    print(json.dumps({"level": level, "msg": msg, **kw}, default=str))


def send_email(to, subject, text):
    if not to:
        return False
    try:
        ses.send_email(
            FromEmailAddress=SENDER,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": text}}}},
        )
        return True
    except ClientError as err:
        code = err.response["Error"]["Code"]
        if code in ("MessageRejected", "MailFromDomainNotVerifiedException", "AccountSuspendedException"):
            # Permanent (e.g. unverified recipient in the SES sandbox) - log, don't retry.
            log("warn", "email rejected", to=to, code=code)
            return False
        raise  # throttling etc. -> SQS retries the message


# ---------------------------------------------------------------- uploads
def handle_upload(bucket, key):
    sub = db.one(
        "SELECT s.id, s.status, s.filename, s.student_name, s.student_email, a.title, a.created_by_email, "
        "(a.due_at IS NOT NULL AND now() > a.due_at) AS late "
        "FROM submissions s JOIN assignments a ON a.id = s.assignment_id WHERE s.s3_key = :key",
        key=key,
    )
    if not sub:
        log("warn", "no submission row for object", key=key)
        return
    if sub["status"] != "pending":
        log("info", "already processed", submission_id=sub["id"])
        return

    head = s3.head_object(Bucket=bucket, Key=key)
    size = head["ContentLength"]
    first_bytes = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-7")["Body"].read()
    valid = 0 < size <= MAX_BYTES and logic.sniff_file_type(first_bytes, sub["filename"])

    status = "uploaded" if valid else "rejected"
    db.execute(
        "UPDATE submissions SET status = :status, size_bytes = :size, uploaded_at = now() "
        "WHERE id = CAST(:id AS uuid) AND status = 'pending'",
        status=status, size=size, id=sub["id"],
    )
    s3.put_object_tagging(
        Bucket=bucket, Key=key, Tagging={"TagSet": [{"Key": "validation", "Value": status}]}
    )
    log("info", "upload processed", submission_id=sub["id"], status=status, size=size)

    size_mb = f"{size / 1024 / 1024:.1f} MB"
    if valid:
        late = " (LATE)" if sub["late"] else ""
        send_email(
            sub["created_by_email"],
            f"New submission{late}: {sub['title']}",
            f"{sub['student_name']} submitted '{sub['filename']}' ({size_mb}) for '{sub['title']}'{late}.\n\n"
            f"Review submissions at {SITE_URL}/#/assignments",
        )
        send_email(
            sub["student_email"],
            f"Receipt: {sub['title']}",
            f"We received '{sub['filename']}' ({size_mb}) for '{sub['title']}'.\nSubmission ID: {sub['id']}",
        )
    else:
        send_email(
            sub["student_email"],
            f"Upload rejected: {sub['title']}",
            f"'{sub['filename']}' was rejected: only genuine PDF or ZIP files up to 50 MB are accepted. "
            f"Please upload again at {SITE_URL}",
        )


# ---------------------------------------------------------------- results
def handle_results_released(exam_id):
    exam = db.one("SELECT id, title FROM exams WHERE id = CAST(:id AS uuid)", id=exam_id)
    if not exam:
        return
    students = db.query(
        "SELECT id, student_name, student_email FROM attempts "
        "WHERE exam_id = CAST(:id AS uuid) AND results_emailed_at IS NULL",
        id=exam_id,
    )
    for s in students:
        send_email(
            s["student_email"],
            f"Results released: {exam['title']}",
            f"Hello {s['student_name']},\n\nYour result for '{exam['title']}' is now available.\n"
            f"Sign in to view it: {SITE_URL}",
        )
        # Mark per student so a retry after a partial failure doesn't email twice.
        db.execute("UPDATE attempts SET results_emailed_at = now() WHERE id = CAST(:id AS uuid)", id=s["id"])
    log("info", "results emails processed", exam_id=exam_id, count=len(students))


def process(body):
    if body.get("Event") == "s3:TestEvent":
        return
    if "Records" in body:  # S3 event notification
        for r in body["Records"]:
            if r.get("eventSource") == "aws:s3":
                handle_upload(r["s3"]["bucket"]["name"], unquote_plus(r["s3"]["object"]["key"]))
        return
    if body.get("type") == "results_released":
        handle_results_released(body["exam_id"])
        return
    log("warn", "unknown message", body=body)


def handler(event, _context):
    failures = []
    for record in event.get("Records", []):
        try:
            process(json.loads(record["body"]))
        except Exception as err:  # noqa: BLE001
            log("error", "failed", messageId=record.get("messageId"), error=str(err))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
