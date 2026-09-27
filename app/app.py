"""NAGP insurance document-upload — Flask web tier.

Runs on EC2 behind a public ALB. Accepts a document upload and stores it in a
private S3 bucket under the ``uploads/`` prefix. Contains **no** database code,
**no** Secrets Manager code, and never makes an S3 object public.

Design notes:
- Application factory (``create_app``) so tests can inject a mocked S3 client and
  configuration without any live AWS call at import time.
- All configuration comes from environment variables; nothing (bucket, account,
  credentials) is hardcoded.
- Compatible with normal Amazon Linux 2023 Python 3.x (no 3.14-only syntax).
"""

import logging
import os
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

logger = logging.getLogger("nagp.app")

DEFAULT_REGION = "us-east-1"
DEFAULT_UPLOAD_PREFIX = "uploads/"
DEFAULT_MAX_UPLOAD_MB = 10
FALLBACK_CONTENT_TYPE = "application/octet-stream"


def _normalize_prefix(prefix):
    """Return a non-leading-slash, trailing-slash prefix (e.g. ``uploads/``)."""
    prefix = (prefix or DEFAULT_UPLOAD_PREFIX).strip().lstrip("/")
    if not prefix:
        prefix = DEFAULT_UPLOAD_PREFIX
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


def create_app(config=None, s3_client=None):
    """Build and return a configured Flask app.

    :param config: optional dict of config overrides (used by tests).
    :param s3_client: optional pre-built/mocked boto3 S3 client (used by tests).
    """
    app = Flask(__name__)

    try:
        max_mb = int(os.environ.get("MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB))
    except (TypeError, ValueError):
        max_mb = DEFAULT_MAX_UPLOAD_MB
    if max_mb < 1:
        max_mb = DEFAULT_MAX_UPLOAD_MB

    app.config.update(
        S3_BUCKET=os.environ.get("S3_BUCKET"),
        AWS_REGION=os.environ.get("AWS_REGION", DEFAULT_REGION),
        UPLOAD_PREFIX=_normalize_prefix(os.environ.get("UPLOAD_PREFIX", DEFAULT_UPLOAD_PREFIX)),
        MAX_UPLOAD_MB=max_mb,
        MAX_CONTENT_LENGTH=max_mb * 1024 * 1024,
    )

    if config:
        app.config.update(config)
        # Keep MAX_CONTENT_LENGTH consistent if MAX_UPLOAD_MB was overridden and
        # an explicit byte limit was not also provided.
        if "MAX_UPLOAD_MB" in config and "MAX_CONTENT_LENGTH" not in config:
            app.config["MAX_CONTENT_LENGTH"] = int(config["MAX_UPLOAD_MB"]) * 1024 * 1024
        if "UPLOAD_PREFIX" in config:
            app.config["UPLOAD_PREFIX"] = _normalize_prefix(config["UPLOAD_PREFIX"])

    if s3_client is not None:
        app.config["S3_CLIENT"] = s3_client

    _register_routes(app)
    _register_error_handlers(app)
    return app


def _get_s3_client(app):
    """Return the app's S3 client, lazily creating one only when first needed."""
    client = app.config.get("S3_CLIENT")
    if client is None:
        client = boto3.client("s3", region_name=app.config["AWS_REGION"])
        app.config["S3_CLIENT"] = client
    return client


def _register_routes(app):
    @app.get("/")
    def index():
        return render_template("index.html", max_mb=app.config["MAX_UPLOAD_MB"])

    @app.get("/health")
    def health():
        # Must not depend on S3 or any external service.
        return jsonify(status="ok"), 200

    @app.post("/upload")
    def upload():
        if "file" not in request.files:
            return jsonify(error="No file part in the request."), 400

        file = request.files["file"]
        if file is None or not file.filename or file.filename.strip() == "":
            return jsonify(error="No file selected."), 400

        bucket = app.config.get("S3_BUCKET")
        if not bucket:
            logger.error("S3_BUCKET is not configured; refusing upload.")
            return jsonify(error="Server is not configured for uploads."), 500

        safe_name = secure_filename(file.filename) or "upload.bin"
        key = "{prefix}{token}/{name}".format(
            prefix=app.config["UPLOAD_PREFIX"], token=uuid.uuid4().hex, name=safe_name
        )
        content_type = file.mimetype or FALLBACK_CONTENT_TYPE

        try:
            s3 = _get_s3_client(app)
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=file.stream,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError):
            # Log internally with detail; return a generic message to the user.
            logger.exception("S3 upload failed for key %s", key)
            return jsonify(error="Upload failed. Please try again later."), 502
        except Exception:  # noqa: BLE001 - defensive: never leak internals
            logger.exception("Unexpected error during upload for key %s", key)
            return jsonify(error="Upload failed. Please try again later."), 500

        logger.info("Stored upload at key=%s content_type=%s", key, content_type)
        return jsonify(status="ok", key=key, content_type=content_type), 201


def _register_error_handlers(app):
    @app.errorhandler(413)
    def too_large(_e):
        return jsonify(error="File too large."), 413

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify(error="Not found."), 404

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify(error="Internal server error."), 500


# Module-level app for Gunicorn (e.g. ``gunicorn --chdir app app:app``).
# Import is safe: no AWS call happens until an actual upload.
app = create_app()


if __name__ == "__main__":
    # Local dev only; production serving is via Gunicorn + systemd. Never debug=True.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False)
