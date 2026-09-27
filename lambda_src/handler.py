"""NAGP insurance document-upload — Lambda processor.

Target runtime: python3.14. Handler: ``handler.lambda_handler``.

Two invocation modes:
  A. S3 ObjectCreated processing (records under the ``uploads/`` prefix) — reads
     object metadata, fetches DB credentials from Secrets Manager, and writes a
     metadata row to RDS MySQL (idempotently).
  B. Controlled ``{"action": "read_recent", "limit": N}`` demo read — returns the
     most recent rows so the demo can prove real RDS data without letting EC2 or
     the local machine touch the database.

Connection contract: the DB endpoint (``DB_HOST`` / ``DB_PORT`` / ``DB_NAME``) comes
from environment variables (RDS resource lifecycle); the RDS-managed secret supplies
only ``username`` / ``password`` (rotating credentials). Host/port are never taken
from the secret.

boto3 is supplied by the managed Lambda runtime; PyMySQL is bundled in the zip.
Secrets/passwords are never logged.
"""

import json
import logging
import os
import urllib.parse
from datetime import date, datetime, timezone

import boto3
import pymysql
import pymysql.cursors

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_UPLOAD_PREFIX = "uploads/"
TABLE_NAME = "document_metadata"
FALLBACK_CONTENT_TYPE = "application/octet-stream"

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
WRITE_TIMEOUT = 10

DEFAULT_READ_LIMIT = 5
MAX_READ_LIMIT = 20
DEFAULT_DB_PORT = 3306

# The RDS-managed secret carries only rotating credentials. The DB endpoint
# (host/port) and database name belong to the RDS resource lifecycle and are
# supplied via environment variables (from CloudFormation) — never read from the
# secret, even if the secret happens to contain host/port.
REQUIRED_SECRET_FIELDS = ("username", "password")

CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS " + TABLE_NAME + " ("
    "  id BIGINT NOT NULL AUTO_INCREMENT,"
    "  file_name VARCHAR(1024) NOT NULL,"
    "  content_type VARCHAR(255) NOT NULL,"
    "  upload_timestamp DATETIME(6) NOT NULL,"
    "  s3_bucket VARCHAR(255) NOT NULL,"
    "  s3_key VARCHAR(1024) NOT NULL,"
    "  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    "  PRIMARY KEY (id),"
    "  UNIQUE KEY uq_object (s3_bucket, s3_key(191), upload_timestamp)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
)

# Idempotency: identical retried events (same bucket/key/eventTime) update the
# existing row instead of inserting a duplicate.
INSERT_SQL = (
    "INSERT INTO " + TABLE_NAME + " "
    "(file_name, content_type, upload_timestamp, s3_bucket, s3_key) "
    "VALUES (%s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE content_type = VALUES(content_type)"
)

SELECT_RECENT_SQL = (
    "SELECT file_name, content_type, upload_timestamp, s3_key "
    "FROM " + TABLE_NAME + " ORDER BY id DESC LIMIT %s"
)


def lambda_handler(event, context=None):
    """Route the invocation to the correct mode."""
    if isinstance(event, dict) and event.get("action") == "read_recent":
        return _handle_read_recent(event)
    if isinstance(event, dict) and "Records" in event:
        return _handle_s3_event(event)
    shape = list(event.keys()) if isinstance(event, dict) else type(event).__name__
    logger.error("Unsupported event shape: %s", shape)
    raise ValueError("Unsupported event type")


# --------------------------------------------------------------------------- #
# Mode A — S3 ObjectCreated processing
# --------------------------------------------------------------------------- #
def _handle_s3_event(event):
    records = event.get("Records") or []
    host, port, db_name = _db_endpoint()   # env-based; fails fast before any connect
    secret = _get_db_secret()

    s3 = boto3.client("s3")
    conn = _connect(secret, host, port, db_name)
    processed = 0
    skipped = 0
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            for record in records:
                item = _extract_record(record)
                if item is None:
                    skipped += 1
                    continue
                head = s3.head_object(Bucket=item["bucket"], Key=item["key"])
                content_type = head.get("ContentType") or FALLBACK_CONTENT_TYPE
                cur.execute(
                    INSERT_SQL,
                    (
                        item["file_name"],
                        content_type,
                        item["upload_ts"],
                        item["bucket"],
                        item["key"],
                    ),
                )
                processed += 1
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("S3 event processing failed; transaction rolled back")
        raise
    finally:
        conn.close()

    logger.info("Processed %d record(s), skipped %d", processed, skipped)
    return {"processed": processed, "skipped": skipped}


def _extract_record(record):
    """Return normalized fields for a valid uploads/ record, else None (skip)."""
    try:
        s3info = record["s3"]
        bucket = s3info["bucket"]["name"]
        raw_key = s3info["object"]["key"]
    except (KeyError, TypeError):
        logger.warning("Malformed S3 record; skipping")
        return None

    key = urllib.parse.unquote_plus(raw_key)
    prefix = os.environ.get("UPLOAD_PREFIX", DEFAULT_UPLOAD_PREFIX)
    if not key.startswith(prefix):
        logger.warning("Object key outside upload prefix; ignoring")
        return None

    file_name = key.rsplit("/", 1)[-1]
    if not file_name:
        logger.warning("Empty file name in key; ignoring")
        return None

    return {
        "bucket": bucket,
        "key": key,
        "file_name": file_name,
        "upload_ts": _parse_event_time(record.get("eventTime")),
    }


def _parse_event_time(value):
    """Parse an ISO-8601 S3 eventTime into a naive-UTC datetime for DATETIME(6)."""
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# --------------------------------------------------------------------------- #
# Mode B — controlled demo read
# --------------------------------------------------------------------------- #
def _handle_read_recent(event):
    limit = event.get("limit", DEFAULT_READ_LIMIT)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, MAX_READ_LIMIT)

    host, port, db_name = _db_endpoint()
    secret = _get_db_secret()
    conn = _connect(secret, host, port, db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(SELECT_RECENT_SQL, (limit,))
            rows = cur.fetchall()
        conn.commit()
    finally:
        conn.close()

    items = [_json_safe_row(row) for row in rows]
    return {"count": len(items), "items": items}


def _json_safe_row(row):
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            # upload_timestamp is stored as UTC wall-clock (naive). Emit an
            # explicit UTC ISO-8601 value so the demo output is unambiguous.
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            out[key] = dt.astimezone(timezone.utc).isoformat()
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# Secrets / DB helpers
# --------------------------------------------------------------------------- #
def _get_db_secret():
    """Fetch and validate the RDS credential secret. Never logs the secret."""
    secret_arn = os.environ.get("DB_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError("DB_SECRET_ARN is not set")

    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_arn)
    raw = resp.get("SecretString")
    if not raw:
        raise RuntimeError("Secret has no SecretString")

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise RuntimeError("Secret is not valid JSON")

    missing = [f for f in REQUIRED_SECRET_FIELDS if not data.get(f)]
    if missing:
        # Names of missing fields only — never the values present.
        raise RuntimeError("Secret missing required field(s): " + ",".join(missing))
    return data


def _require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(name + " is not set")
    return value


def _db_endpoint():
    """Resolve (host, port, db_name) from the environment.

    Host/port belong to the RDS resource lifecycle and are supplied by
    CloudFormation via env vars (``DB_HOST`` / ``DB_PORT`` / ``DB_NAME``). They are
    NOT read from the credentials secret. Fails fast before any DB connection.
    """
    host = _require_env("DB_HOST")
    db_name = _require_env("DB_NAME")
    raw_port = os.environ.get("DB_PORT", str(DEFAULT_DB_PORT))
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        raise RuntimeError("DB_PORT must be an integer")
    if not (1 <= port <= 65535):
        raise RuntimeError("DB_PORT is out of range")
    return host, port, db_name


def _connect(secret, host, port, db_name):
    # Endpoint from environment; credentials from the secret.
    return pymysql.connect(
        host=host,
        user=secret["username"],
        password=secret["password"],
        port=port,
        database=db_name,
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        write_timeout=WRITE_TIMEOUT,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
