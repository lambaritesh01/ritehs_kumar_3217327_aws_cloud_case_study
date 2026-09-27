"""Unit tests for the Flask web tier. No live AWS calls (S3 client is mocked)."""

import io

import pytest
from botocore.exceptions import ClientError

import app as app_module


class FakeS3:
    """Minimal stand-in for a boto3 S3 client that records put_object calls."""

    def __init__(self, raise_exc=None):
        self.calls = []
        self.raise_exc = raise_exc

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        return {"ETag": "fake-etag"}


def make_client(s3=None, config=None):
    cfg = {"S3_BUCKET": "test-bucket"}
    if config:
        cfg.update(config)
    application = app_module.create_app(config=cfg, s3_client=s3)
    application.testing = True
    return application, application.test_client()


def test_index_returns_200():
    _app, client = make_client()
    resp = client.get("/")
    assert resp.status_code == 200


def test_health_returns_200_and_does_not_use_s3():
    s3 = FakeS3()
    _app, client = make_client(s3=s3)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    assert s3.calls == []  # health must not touch S3


def test_upload_without_file_returns_400():
    _app, client = make_client(s3=FakeS3())
    resp = client.post("/upload", data={})
    assert resp.status_code == 400


def test_upload_empty_filename_rejected():
    _app, client = make_client(s3=FakeS3())
    data = {"file": (io.BytesIO(b"content"), "")}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_successful_upload_calls_s3_with_expected_args():
    s3 = FakeS3()
    _app, client = make_client(s3=s3)
    data = {"file": (io.BytesIO(b"%PDF-1.7 fake"), "policy.pdf", "application/pdf")}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")

    assert resp.status_code == 201
    assert len(s3.calls) == 1
    call = s3.calls[0]
    assert call["Bucket"] == "test-bucket"          # bucket from config
    assert call["Key"].startswith("uploads/")        # correct prefix
    assert call["Key"].endswith("/policy.pdf")       # sanitized source filename retained
    assert call["ContentType"] == "application/pdf"  # content type supplied

    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["key"].startswith("uploads/")


def test_content_type_fallback_to_octet_stream():
    s3 = FakeS3()
    _app, client = make_client(s3=s3)
    # No explicit content type + extensionless name => fallback.
    data = {"file": (io.BytesIO(b"rawbytes"), "mystery")}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")

    assert resp.status_code == 201
    assert s3.calls[0]["ContentType"] == "application/octet-stream"


def test_s3_failure_returns_generic_error_without_leaking_internals():
    err = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "secret-bucket-policy-detail"}},
        "PutObject",
    )
    s3 = FakeS3(raise_exc=err)
    _app, client = make_client(s3=s3)
    data = {"file": (io.BytesIO(b"data"), "policy.pdf", "application/pdf")}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")

    assert resp.status_code == 502
    text = resp.get_data(as_text=True)
    assert "AccessDenied" not in text
    assert "secret-bucket-policy-detail" not in text
    assert "Traceback" not in text


def test_missing_bucket_config_returns_500():
    application = app_module.create_app(config={"S3_BUCKET": None}, s3_client=FakeS3())
    client = application.test_client()
    data = {"file": (io.BytesIO(b"data"), "policy.pdf", "application/pdf")}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 500


def test_max_upload_size_returns_413():
    s3 = FakeS3()
    _app, client = make_client(s3=s3, config={"MAX_CONTENT_LENGTH": 16})
    data = {"file": (io.BytesIO(b"x" * 1024), "big.bin", "application/octet-stream")}
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 413
    assert s3.calls == []  # rejected before any S3 call


def test_key_uuid_makes_duplicate_filenames_unique():
    s3 = FakeS3()
    _app, client = make_client(s3=s3)
    for _ in range(2):
        data = {"file": (io.BytesIO(b"data"), "policy.pdf", "application/pdf")}
        client.post("/upload", data=data, content_type="multipart/form-data")
    keys = [c["Key"] for c in s3.calls]
    assert len(keys) == 2
    assert keys[0] != keys[1]                 # unique despite same filename
    assert all(k.endswith("/policy.pdf") for k in keys)
