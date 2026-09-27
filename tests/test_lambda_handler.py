"""Unit tests for the Lambda processor. No live AWS/Secrets Manager/RDS calls.

boto3 clients and PyMySQL are mocked. Connection contract under test:
  - DB endpoint (host/port/name) comes from environment variables.
  - The secret supplies ONLY username/password.
"""

import json
from datetime import datetime
from unittest import mock

import pytest

import handler


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeCursor:
    def __init__(self, fetch_rows=None, fail_on=None):
        self.executed = []          # list of (sql, params)
        self._fetch_rows = fetch_rows or []
        self._fail_on = fail_on

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError("simulated db failure")

    def fetchall(self):
        return list(self._fetch_rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def inserts(self):
        return [(s, p) for (s, p) in self.executed if s.startswith("INSERT")]

    def selects(self):
        return [(s, p) for (s, p) in self.executed if s.startswith("SELECT")]


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = 0
        self.rolled_back = 0
        self.closed = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed += 1


def install(monkeypatch, conn, secret=None, secret_string=None,
            content_type="application/pdf", set_host=True, set_port=None, set_db=True):
    """Patch handler.boto3.client and handler.pymysql.connect; set env.

    Returns (sm_mock, s3_mock, connect_calls) where connect_calls captures the
    kwargs pymysql.connect was called with.
    """
    monkeypatch.setenv("DB_SECRET_ARN", "test-secret-arn")
    if set_db:
        monkeypatch.setenv("DB_NAME", "nagp")
    else:
        monkeypatch.delenv("DB_NAME", raising=False)
    if set_host:
        monkeypatch.setenv("DB_HOST", "db.example.internal")
    else:
        monkeypatch.delenv("DB_HOST", raising=False)
    if set_port is not None:
        monkeypatch.setenv("DB_PORT", set_port)
    else:
        monkeypatch.delenv("DB_PORT", raising=False)
    monkeypatch.delenv("UPLOAD_PREFIX", raising=False)

    # RDS-managed-style secret: credentials only, no host/port.
    if secret_string is None:
        secret_string = json.dumps(
            secret if secret is not None else {"username": "u", "password": "p"}
        )

    sm = mock.Mock()
    sm.get_secret_value.return_value = {"SecretString": secret_string}
    s3 = mock.Mock()
    s3.head_object.return_value = {"ContentType": content_type}

    def _client(service, *a, **k):
        if service == "secretsmanager":
            return sm
        if service == "s3":
            return s3
        raise AssertionError("unexpected service: " + service)

    connect_calls = []

    def _connect(**kw):
        connect_calls.append(kw)
        return conn

    monkeypatch.setattr(handler.boto3, "client", _client)
    monkeypatch.setattr(handler.pymysql, "connect", _connect)
    return sm, s3, connect_calls


def s3_event(key, bucket="test-bucket", event_time="2026-09-26T12:34:56.000Z"):
    return {"Records": [{"eventTime": event_time,
                         "s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


# --------------------------------------------------------------------------- #
# Mode A — processing
# --------------------------------------------------------------------------- #
def test_s3_event_normal_insert(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, s3, _calls = install(monkeypatch, conn, content_type="application/pdf")

    result = handler.lambda_handler(s3_event("uploads/abc123/my%20file.pdf"))

    s3.head_object.assert_called_once_with(Bucket="test-bucket", Key="uploads/abc123/my file.pdf")
    assert result == {"processed": 1, "skipped": 0}
    assert conn.committed == 1 and conn.rolled_back == 0 and conn.closed == 1

    inserts = cur.inserts()
    assert len(inserts) == 1
    _sql, params = inserts[0]
    file_name, content_type, upload_ts, bucket, key = params
    assert file_name == "my file.pdf"
    assert content_type == "application/pdf"
    assert isinstance(upload_ts, datetime)
    assert upload_ts == datetime(2026, 9, 26, 12, 34, 56)
    assert bucket == "test-bucket"
    assert key == "uploads/abc123/my file.pdf"


def test_multiple_records_processed(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, s3, _calls = install(monkeypatch, conn)
    event = {"Records": [
        {"eventTime": "2026-09-26T12:00:00.000Z",
         "s3": {"bucket": {"name": "b"}, "object": {"key": "uploads/a/one.pdf"}}},
        {"eventTime": "2026-09-26T12:00:01.000Z",
         "s3": {"bucket": {"name": "b"}, "object": {"key": "uploads/b/two.png"}}},
    ]}
    result = handler.lambda_handler(event)
    assert result == {"processed": 2, "skipped": 0}
    assert len(cur.inserts()) == 2
    assert s3.head_object.call_count == 2


def test_content_type_fallback(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, s3, _calls = install(monkeypatch, conn)
    s3.head_object.return_value = {}  # no ContentType
    handler.lambda_handler(s3_event("uploads/x/file.bin"))
    _sql, params = cur.inserts()[0]
    assert params[1] == "application/octet-stream"


def test_idempotency_uses_on_duplicate_key():
    # SQL design must make identical retries idempotent (no duplicate rows), while a
    # later event with a different eventTime is a new observation.
    assert "ON DUPLICATE KEY UPDATE" in handler.INSERT_SQL
    assert "UNIQUE KEY" in handler.CREATE_TABLE_SQL
    assert "upload_timestamp" in handler.CREATE_TABLE_SQL


def test_non_uploads_key_skipped(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, s3, _calls = install(monkeypatch, conn)
    result = handler.lambda_handler(s3_event("artifacts/app/app.zip"))
    assert result == {"processed": 0, "skipped": 1}
    s3.head_object.assert_not_called()
    assert cur.inserts() == []


def test_db_failure_rolls_back_and_propagates(monkeypatch):
    cur = FakeCursor(fail_on="INSERT")
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    with pytest.raises(RuntimeError):
        handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert conn.rolled_back == 1
    assert conn.committed == 0
    assert conn.closed == 1


# --------------------------------------------------------------------------- #
# Connection contract (env endpoint + credentials-only secret)
# --------------------------------------------------------------------------- #
def test_connection_uses_env_endpoint_and_secret_credentials(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, _s3, calls = install(
        monkeypatch, conn,
        secret={"username": "svcuser", "password": "svcpass"},
        set_port="5306",
    )
    handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert len(calls) == 1
    kw = calls[0]
    assert kw["host"] == "db.example.internal"   # from DB_HOST
    assert kw["port"] == 5306                     # from DB_PORT
    assert kw["database"] == "nagp"               # from DB_NAME
    assert kw["user"] == "svcuser"                # from secret
    assert kw["password"] == "svcpass"            # from secret


def test_rds_managed_secret_without_host_port_succeeds(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    # Secret has ONLY username/password (RDS-managed style).
    _sm, _s3, calls = install(monkeypatch, conn, secret={"username": "u", "password": "p"})
    result = handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert result["processed"] == 1
    assert calls[0]["host"] == "db.example.internal"


def test_secret_host_port_do_not_override_env(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    # Even if the secret contains host/port, the env endpoint must win.
    _sm, _s3, calls = install(
        monkeypatch, conn,
        secret={"username": "u", "password": "p",
                "host": "evil.attacker.example", "port": 6666},
        set_port="3306",
    )
    handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert calls[0]["host"] == "db.example.internal"
    assert calls[0]["port"] == 3306
    assert calls[0]["host"] != "evil.attacker.example"
    assert calls[0]["port"] != 6666


def test_secret_missing_username_fails(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, _s3, calls = install(monkeypatch, conn, secret={"password": "p"})
    with pytest.raises(RuntimeError):
        handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert calls == []  # no connection attempted


def test_secret_missing_password_fails(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, _s3, calls = install(monkeypatch, conn, secret={"username": "u"})
    with pytest.raises(RuntimeError):
        handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert calls == []


def test_missing_db_host_fails_before_connect(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, s3, calls = install(monkeypatch, conn, set_host=False)
    with pytest.raises(RuntimeError):
        handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert calls == []                 # never attempted a connection
    s3.head_object.assert_not_called()  # never touched S3 object either


def test_invalid_db_port_fails_safely(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    _sm, _s3, calls = install(monkeypatch, conn, set_port="not-a-port")
    with pytest.raises(RuntimeError):
        handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert calls == []


def test_secret_value_never_logged(monkeypatch, caplog):
    cur = FakeCursor()
    conn = FakeConn(cur)
    install(monkeypatch, conn,
            secret={"username": "admin", "password": "SUPERSECRETVALUE"})
    with caplog.at_level("INFO"):
        result = handler.lambda_handler(s3_event("uploads/x/file.pdf"))
    assert "SUPERSECRETVALUE" not in caplog.text
    assert "SUPERSECRETVALUE" not in json.dumps(result)


# --------------------------------------------------------------------------- #
# Phase 4 — UTC timestamp contract
# --------------------------------------------------------------------------- #
def test_event_time_handled_as_utc(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    handler.lambda_handler(s3_event("uploads/x/file.pdf",
                                    event_time="2026-09-26T08:15:30.123Z"))
    _sql, params = cur.inserts()[0]
    upload_ts = params[2]
    # Deterministic UTC wall-clock, independent of local machine timezone.
    assert upload_ts == datetime(2026, 9, 26, 8, 15, 30, 123000)


def test_event_time_with_offset_normalized_to_utc(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    # 10:15:30 +02:00 == 08:15:30 UTC
    handler.lambda_handler(s3_event("uploads/x/file.pdf",
                                    event_time="2026-09-26T10:15:30+02:00"))
    _sql, params = cur.inserts()[0]
    assert params[2] == datetime(2026, 9, 26, 8, 15, 30)


def test_read_recent_serializes_timestamp_as_utc(monkeypatch):
    rows = [{"file_name": "a.pdf", "content_type": "application/pdf",
             "upload_timestamp": datetime(2026, 9, 26, 8, 15, 30, 123000),
             "s3_key": "uploads/x/a.pdf"}]
    cur = FakeCursor(fetch_rows=rows)
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    result = handler.lambda_handler({"action": "read_recent"})
    ts = result["items"][0]["upload_timestamp"]
    assert ts.endswith("+00:00")                       # explicit UTC indicator
    assert ts == "2026-09-26T08:15:30.123000+00:00"
    assert json.dumps(result)                           # fully serializable


# --------------------------------------------------------------------------- #
# Mode B — read_recent limits
# --------------------------------------------------------------------------- #
def test_read_recent_default_limit(monkeypatch):
    cur = FakeCursor(fetch_rows=[])
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    result = handler.lambda_handler({"action": "read_recent"})
    assert cur.selects()[0][1] == (handler.DEFAULT_READ_LIMIT,)  # (5,)
    assert result["count"] == 0


def test_read_recent_explicit_limit(monkeypatch):
    cur = FakeCursor(fetch_rows=[])
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    handler.lambda_handler({"action": "read_recent", "limit": 10})
    assert cur.selects()[0][1] == (10,)


def test_read_recent_hard_max_enforced(monkeypatch):
    cur = FakeCursor(fetch_rows=[])
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    handler.lambda_handler({"action": "read_recent", "limit": 100})
    assert cur.selects()[0][1] == (handler.MAX_READ_LIMIT,)  # clamped to 20


def test_read_recent_invalid_limit(monkeypatch):
    cur = FakeCursor()
    conn = FakeConn(cur)
    install(monkeypatch, conn)
    with pytest.raises(ValueError):
        handler.lambda_handler({"action": "read_recent", "limit": "abc"})


def test_read_recent_returns_no_credentials(monkeypatch):
    rows = [{"file_name": "a.pdf", "content_type": "application/pdf",
             "upload_timestamp": datetime(2026, 9, 26, 10, 0, 0), "s3_key": "uploads/x/a.pdf"}]
    cur = FakeCursor(fetch_rows=rows)
    conn = FakeConn(cur)
    install(monkeypatch, conn, secret={"username": "admin", "password": "SECRETPW"})
    result = handler.lambda_handler({"action": "read_recent"})
    blob = json.dumps(result)
    assert "SECRETPW" not in blob
    assert "password" not in blob
    assert "admin" not in blob


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def test_unsupported_event_rejected(monkeypatch):
    with pytest.raises(ValueError):
        handler.lambda_handler({"foo": "bar"})
