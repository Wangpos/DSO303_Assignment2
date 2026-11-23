"""Pure business logic (no AWS calls) so it can be unit-tested anywhere."""
import re

ROLE_ORDER = ("admins", "tutors", "students")
ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".zip": "application/zip"}
PDF_MAGIC = b"%PDF"
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")  # normal / empty archive


def parse_groups(raw):
    """Cognito groups arrive from the HTTP API JWT authorizer as '[a b]' or 'a'."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(g) for g in raw]
    return [g for g in re.split(r"[\s,]+", str(raw).strip("[]")) if g]


def primary_role(groups):
    for role in ROLE_ORDER:
        if role in groups:
            return role[:-1]  # admins -> admin
    return None


def safe_filename(name, max_len=100):
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "file"
    if len(base) > max_len:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: max_len - len(ext) - 1] + "." + ext) if dot else base[:max_len]
    return base


def validate_upload_request(filename, size_bytes, max_mb=50):
    """Returns (content_type, error). Only PDF/ZIP up to max_mb are accepted."""
    if not filename:
        return None, "filename is required"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return None, "only .pdf and .zip files are accepted"
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return None, "size must be an integer number of bytes"
    if size <= 0:
        return None, "file is empty"
    if size > max_mb * 1024 * 1024:
        return None, f"file is larger than {max_mb} MB"
    return ALLOWED_EXTENSIONS[ext], None


def sniff_file_type(head, filename):
    """Checks the first bytes match the extension (stops renamed executables)."""
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        return head.startswith(PDF_MAGIC)
    if lower.endswith(".zip"):
        return any(head.startswith(m) for m in ZIP_MAGICS)
    return False


def score_mcq(questions, answers):
    """questions: [{id, kind, correct_option, marks}], answers: {question_id: response}.

    Returns (mcq_score, has_short_answers)."""
    score = 0.0
    has_short = False
    for q in questions:
        if q.get("kind") == "short":
            has_short = True
            continue
        if q.get("kind") != "mcq" or q.get("correct_option") is None:
            continue
        response = answers.get(q["id"])
        try:
            if response is not None and int(response) == int(q["correct_option"]):
                score += float(q.get("marks") or 1)
        except (TypeError, ValueError):
            pass
    return round(score, 2), has_short


def validate_exam(body):
    """Validates a tutor's exam payload; returns list of error strings."""
    errors = []
    if not (body.get("title") or "").strip():
        errors.append("title is required")
    try:
        duration = int(body.get("duration_minutes", 0))
        if not 1 <= duration <= 600:
            errors.append("duration_minutes must be between 1 and 600")
    except (TypeError, ValueError):
        errors.append("duration_minutes must be a number")
    questions = body.get("questions") or []
    if not questions:
        errors.append("at least one question is required")
    for i, q in enumerate(questions, start=1):
        kind = q.get("kind")
        if kind not in ("mcq", "short"):
            errors.append(f"question {i}: kind must be 'mcq' or 'short'")
            continue
        if not (q.get("prompt") or "").strip():
            errors.append(f"question {i}: prompt is required")
        if kind == "mcq":
            options = q.get("options") or []
            if len(options) < 2:
                errors.append(f"question {i}: an MCQ needs at least two options")
            co = q.get("correct_option")
            if not isinstance(co, int) or not 0 <= co < len(options):
                errors.append(f"question {i}: correct_option must index one of the options")
    return errors


def match_route(routes, method, path):
    """routes: [(method, regex, fn)] -> (fn, params) or (None, None)."""
    for m, pattern, fn in routes:
        if m != method:
            continue
        match = re.fullmatch(pattern, path)
        if match:
            return fn, match.groupdict()
    return None, None
