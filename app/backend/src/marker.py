"""SQS consumer: auto-marks the MCQ part of a submitted attempt.

Idempotent - re-processing the same attempt yields the same score, so SQS
at-least-once delivery is safe."""
import json

from lib import db, logic


def mark(attempt_id):
    attempt = db.one(
        "SELECT id, exam_id, status FROM attempts WHERE id = CAST(:id AS uuid)", id=attempt_id
    )
    if not attempt:
        print(json.dumps({"level": "warn", "msg": "attempt not found", "attempt_id": attempt_id}))
        return
    if attempt["status"] == "in_progress":
        print(json.dumps({"level": "warn", "msg": "attempt not submitted yet", "attempt_id": attempt_id}))
        return

    questions = db.query(
        "SELECT id, kind, correct_option, marks FROM questions WHERE exam_id = CAST(:id AS uuid)",
        id=attempt["exam_id"],
    )
    answers = {
        a["question_id"]: a["response"]
        for a in db.query("SELECT question_id, response FROM answers WHERE attempt_id = CAST(:id AS uuid)", id=attempt_id)
    }
    score, has_short = logic.score_mcq(questions, answers)
    db.execute(
        "UPDATE attempts SET mcq_score = :score, total_score = :score + COALESCE(short_score, 0), "
        "status = CASE WHEN status = 'marked' OR NOT :has_short THEN 'marked' ELSE 'auto_marked' END "
        "WHERE id = CAST(:id AS uuid)",
        score=float(score), has_short=has_short, id=attempt_id,
    )
    print(json.dumps({"level": "info", "msg": "marked", "attempt_id": attempt_id, "mcq_score": score}))


def handler(event, _context):
    failures = []
    for record in event.get("Records", []):
        try:
            mark(json.loads(record["body"])["attempt_id"])
        except Exception as err:  # noqa: BLE001 - report per-message failure, SQS retries it
            print(json.dumps({"level": "error", "messageId": record.get("messageId"), "error": str(err)}))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
