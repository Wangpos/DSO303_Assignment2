"""Thin PostgreSQL client for Amazon RDS (Multi-AZ) using pg8000.

* One connection per Lambda execution environment, reused across invocations.
* TLS is mandatory (the parameter group sets rds.force_ssl=1); the server
  certificate is verified against the RDS CA bundle shipped in the Lambda layer.
* If the connection drops - e.g. during a Multi-AZ failover, when the endpoint's
  DNS name moves to the standby in the other AZ - the call reconnects and retries
  with exponential backoff until `max_wait` seconds have passed.

The public API (query / one / execute / batch / jsonb, `:name` parameters, rows
as dicts with JSON-friendly values) is the same one the Aurora Data API version
exposed, so the handlers did not need to change."""
import datetime
import decimal
import json
import os
import socket
import ssl
import time
import uuid

import boto3

try:
    import pg8000.native as pg
except ImportError:  # unit tests run without the Lambda layer
    pg = None

SECRET_ARN = os.environ.get("DB_SECRET_ARN", "")
CA_BUNDLE = os.environ.get("DB_CA_BUNDLE", "/opt/rds-global-bundle.pem")

# SQLSTATE classes that mean "the server went away / is switching roles" -> retry.
_TRANSIENT_SQLSTATE = ("08", "57P01", "57P02", "57P03", "25006", "53300")

_conn = None
_secret = None


class DatabaseUnavailable(Exception):
    pass


def _credentials():
    global _secret
    if _secret is None:
        sm = boto3.client("secretsmanager")
        _secret = json.loads(sm.get_secret_value(SecretId=SECRET_ARN)["SecretString"])
    return _secret


def _ssl_context():
    if os.path.exists(CA_BUNDLE):
        return ssl.create_default_context(cafile=CA_BUNDLE)
    # Fallback (local runs): still encrypted, but without CA verification.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _connect():
    s = _credentials()
    return pg.Connection(
        user=s["username"],
        password=s["password"],
        host=s["host"],
        port=int(s.get("port", 5432)),
        database=s["dbname"],
        ssl_context=_ssl_context(),
        timeout=10,
        tcp_keepalive=True,
        application_name=os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "examhub"),
    )


def _close():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _conn = None


def _is_transient(err):
    if isinstance(err, (pg.InterfaceError, OSError, socket.timeout, ConnectionError)):
        return True
    if isinstance(err, pg.DatabaseError) and err.args and isinstance(err.args[0], dict):
        code = err.args[0].get("C", "")
        return code.startswith(_TRANSIENT_SQLSTATE)
    return False


def _param(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def _cell(v):
    """Return values in the same JSON-friendly shape the Data API produced."""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, datetime.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=datetime.timezone.utc)
        return v.astimezone(datetime.timezone.utc).isoformat()
    if isinstance(v, (datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (dict, list)):  # jsonb -> string, decoded with jsonb()
        return json.dumps(v)
    return v


def _run(sql, max_wait, params):
    global _conn
    deadline = time.time() + max_wait
    delay = 0.5
    args = {k: _param(v) for k, v in params.items()}
    while True:
        try:
            if _conn is None:
                _conn = _connect()
            rows = _conn.run(sql, **args)
            cols = [c["name"] for c in (_conn.columns or [])]
            return rows, cols, _conn.row_count
        except Exception as err:
            if not _is_transient(err):
                raise
            _close()
            if time.time() + delay > deadline:
                raise DatabaseUnavailable(str(err)) from err
            time.sleep(delay)
            delay = min(delay * 2, 8)


def query(sql, max_wait=60, **params):
    rows, cols, _ = _run(sql, max_wait, params)
    return [dict(zip(cols, (_cell(v) for v in row))) for row in (rows or [])]


def one(sql, **params):
    rows = query(sql, **params)
    return rows[0] if rows else None


def execute(sql, max_wait=60, **params):
    _, _, count = _run(sql, max_wait, params)
    return max(count or 0, 0)


def batch(sql, param_sets):
    if not param_sets:
        return
    _run("BEGIN", 60, {})
    try:
        for p in param_sets:
            _run(sql, 0, p)
        _run("COMMIT", 0, {})
    except Exception:
        _close()  # drops the open transaction
        raise


def jsonb(value):
    """jsonb columns are returned as JSON strings; decode them."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value
