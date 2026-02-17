"""Google Cloud Storage client wrapper with graceful fallback.

Configuration keys consumed from the *config* dict::

    gcp.cloud_storage.bucket  -- GCS bucket name
    gcp.credentials_path      -- path to service-account JSON (optional)

If ``google-cloud-storage`` is not installed **or** the connection
cannot be established, every public method logs a warning and returns a
safe default (empty bytes, empty list, etc.).
"""

from __future__ import annotations

import gzip
import io
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional import
# ---------------------------------------------------------------------------
try:
    from google.cloud import storage as gcs_storage
    from google.oauth2 import service_account

    _HAS_GCS = True
except ImportError:
    _HAS_GCS = False
    logger.warning(
        "google-cloud-storage is not installed. "
        "GCSClient will return empty results for all operations."
    )


def _nested_get(d: dict, dotted_key: str, default: Any = None) -> Any:
    """Retrieve a value from a nested dict using a dotted key path."""
    keys = dotted_key.split(".")
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k)
        if current is None:
            return default
    return current


class GCSClient:
    """Thin wrapper around ``google.cloud.storage.Client``.

    All public methods are safe to call even when the library is missing
    or the bucket is unreachable -- they log a warning and return safe
    defaults.
    """

    def __init__(self, config: dict) -> None:
        self._bucket_name: str = _nested_get(config, "gcp.cloud_storage.bucket", "")
        self._credentials_path: str | None = _nested_get(config, "gcp.credentials_path")
        self._client: Any | None = None
        self._bucket: Any | None = None

        if not _HAS_GCS:
            logger.warning("GCSClient initialised without google-cloud-storage.")
            return

        if not self._bucket_name:
            logger.warning(
                "GCSClient: gcp.cloud_storage.bucket is empty. "
                "No bucket operations will be performed."
            )
            return

        try:
            credentials = None
            if self._credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    self._credentials_path,
                    scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
                )
            self._client = gcs_storage.Client(credentials=credentials)
            self._bucket = self._client.bucket(self._bucket_name)
            logger.info("GCSClient connected to bucket=%s", self._bucket_name)
        except Exception:
            logger.warning(
                "Failed to initialise GCS client for bucket=%s. "
                "All GCS operations will be skipped.",
                self._bucket_name,
                exc_info=True,
            )

    # -- helpers -------------------------------------------------------------

    @property
    def _available(self) -> bool:
        return self._bucket is not None

    @staticmethod
    def _to_jsonl_bytes(data: list[dict]) -> bytes:
        """Serialise a list of dicts into newline-delimited JSON bytes."""
        lines: list[str] = []
        for record in data:
            lines.append(json.dumps(record, ensure_ascii=False, default=str))
        return ("\n".join(lines) + "\n").encode("utf-8")

    # -- public API ----------------------------------------------------------

    def upload_jsonl(self, data: list[dict], path: str) -> bool:
        """Upload *data* as a newline-delimited JSON (JSONL) file.

        Parameters
        ----------
        data:
            List of dicts to serialise.
        path:
            Object path inside the bucket (e.g.
            ``"price_buffer/2026/02/17/kr_5m.jsonl"``).

        Returns ``True`` on success.
        """
        if not self._available:
            logger.warning("upload_jsonl skipped: GCS client not available.")
            return False

        if not data:
            logger.debug("upload_jsonl: empty data list, nothing to upload.")
            return True

        try:
            payload = self._to_jsonl_bytes(data)
            blob = self._bucket.blob(path)
            blob.upload_from_string(payload, content_type="application/x-ndjson")
            logger.info(
                "Uploaded %d records (%d bytes) to gs://%s/%s",
                len(data),
                len(payload),
                self._bucket_name,
                path,
            )
            return True
        except Exception:
            logger.warning(
                "GCS upload_jsonl failed for path=%s",
                path,
                exc_info=True,
            )
            return False

    def upload_compressed(self, data: list[dict], path: str) -> bool:
        """Upload *data* as a gzip-compressed JSONL file.

        The object path should conventionally end with ``.jsonl.gz``.

        Returns ``True`` on success.
        """
        if not self._available:
            logger.warning("upload_compressed skipped: GCS client not available.")
            return False

        if not data:
            logger.debug("upload_compressed: empty data list, nothing to upload.")
            return True

        try:
            jsonl_bytes = self._to_jsonl_bytes(data)

            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode="wb") as gz:
                gz.write(jsonl_bytes)
            compressed = buffer.getvalue()

            blob = self._bucket.blob(path)
            blob.content_encoding = "gzip"
            blob.upload_from_string(compressed, content_type="application/x-ndjson")
            logger.info(
                "Uploaded %d records (%d -> %d bytes gzipped) to gs://%s/%s",
                len(data),
                len(jsonl_bytes),
                len(compressed),
                self._bucket_name,
                path,
            )
            return True
        except Exception:
            logger.warning(
                "GCS upload_compressed failed for path=%s",
                path,
                exc_info=True,
            )
            return False

    def download(self, path: str) -> bytes:
        """Download the object at *path* and return its raw bytes.

        Returns empty ``bytes`` on failure.
        """
        if not self._available:
            logger.warning("download skipped: GCS client not available.")
            return b""

        try:
            blob = self._bucket.blob(path)
            data = blob.download_as_bytes()
            logger.debug(
                "Downloaded %d bytes from gs://%s/%s",
                len(data),
                self._bucket_name,
                path,
            )
            return data
        except Exception:
            logger.warning(
                "GCS download failed for path=%s",
                path,
                exc_info=True,
            )
            return b""

    def list_objects(self, prefix: str) -> list[str]:
        """List all object names under *prefix*.

        Returns an empty list when the client is unavailable.
        """
        if not self._available:
            logger.warning("list_objects skipped: GCS client not available.")
            return []

        try:
            blobs = self._client.list_blobs(self._bucket_name, prefix=prefix)
            names = [blob.name for blob in blobs]
            logger.debug(
                "list_objects prefix=%s found %d objects.",
                prefix,
                len(names),
            )
            return names
        except Exception:
            logger.warning(
                "GCS list_objects failed for prefix=%s",
                prefix,
                exc_info=True,
            )
            return []
