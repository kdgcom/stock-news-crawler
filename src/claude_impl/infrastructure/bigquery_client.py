"""BigQuery client wrapper with graceful fallback.

Configuration keys consumed from the *config* dict::

    gcp.project_id          -- GCP project identifier
    gcp.bigquery.dataset    -- target dataset name  (default ``stock_trading``)
    gcp.bigquery.location   -- dataset location      (default ``US``)
    gcp.credentials_path    -- path to service-account JSON (optional)

If ``google-cloud-bigquery`` is not installed **or** the connection cannot
be established, every public method logs a warning and returns an empty
result so that the rest of the system keeps running.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional import of google-cloud-bigquery
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    _HAS_BIGQUERY = True
except ImportError:
    _HAS_BIGQUERY = False
    logger.warning(
        "google-cloud-bigquery is not installed. "
        "BigQueryClient will return empty results for all operations."
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


class BigQueryClient:
    """Thin wrapper around ``google.cloud.bigquery.Client``.

    All public methods are safe to call even when the underlying library
    is unavailable -- they will simply return empty results and log a
    warning.
    """

    def __init__(self, config: dict) -> None:
        self._project_id: str = _nested_get(config, "gcp.project_id", "")
        self._dataset: str = _nested_get(config, "gcp.bigquery.dataset", "stock_trading")
        self._location: str = _nested_get(config, "gcp.bigquery.location", "US")
        self._credentials_path: str | None = _nested_get(config, "gcp.credentials_path")
        self._client: Any | None = None

        if not _HAS_BIGQUERY:
            logger.warning("BigQueryClient initialised without google-cloud-bigquery.")
            return

        try:
            credentials = None
            if self._credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    self._credentials_path,
                    scopes=["https://www.googleapis.com/auth/bigquery"],
                )
            self._client = bigquery.Client(
                project=self._project_id,
                credentials=credentials,
                location=self._location,
            )
            logger.info(
                "BigQueryClient connected to project=%s dataset=%s",
                self._project_id,
                self._dataset,
            )
        except Exception:
            logger.warning(
                "Failed to initialise BigQuery client. "
                "All BigQuery operations will return empty results.",
                exc_info=True,
            )

    # -- helpers -------------------------------------------------------------

    @property
    def _available(self) -> bool:
        return self._client is not None

    def _full_table_id(self, table: str) -> str:
        """Return fully-qualified table id ``project.dataset.table``."""
        return f"{self._project_id}.{self._dataset}.{table}"

    # -- public API ----------------------------------------------------------

    def insert_rows(self, table: str, rows: list[dict]) -> list[dict]:
        """Insert *rows* as JSON into *table*.

        Returns a list of errors reported by the BigQuery streaming API.
        If the client is unavailable the call is a no-op and returns an
        empty list.
        """
        if not self._available:
            logger.warning("insert_rows skipped: BigQuery client not available.")
            return []

        if not rows:
            return []

        try:
            table_ref = self._client.get_table(self._full_table_id(table))
            errors = self._client.insert_rows_json(table_ref, rows)
            if errors:
                logger.error(
                    "BigQuery insert_rows errors for %s: %s",
                    table,
                    errors,
                )
            else:
                logger.debug(
                    "Inserted %d rows into %s",
                    len(rows),
                    table,
                )
            return errors  # type: ignore[return-value]
        except Exception:
            logger.warning(
                "BigQuery insert_rows failed for table=%s",
                table,
                exc_info=True,
            )
            return []

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        """Execute *sql* and return results as a list of dicts.

        Parameterised queries are supported via *params*.  Each key in
        *params* should correspond to a ``@key`` placeholder in the SQL
        string.  Values are sent as ``ScalarQueryParameter`` with their
        type inferred from the Python type.
        """
        if not self._available:
            logger.warning("query skipped: BigQuery client not available.")
            return []

        try:
            job_config = bigquery.QueryJobConfig()

            if params:
                query_params: list[bigquery.ScalarQueryParameter] = []
                for name, value in params.items():
                    bq_type = self._python_type_to_bq(value)
                    query_params.append(
                        bigquery.ScalarQueryParameter(name, bq_type, value)
                    )
                job_config.query_parameters = query_params

            query_job = self._client.query(sql, job_config=job_config)
            results = query_job.result()

            rows = [dict(row) for row in results]
            logger.debug("Query returned %d rows.", len(rows))
            return rows
        except Exception:
            logger.warning("BigQuery query failed.", exc_info=True)
            return []

    def load_from_gcs(self, gcs_uri: str, table: str) -> None:
        """Load data from a GCS JSONL file into *table*.

        Uses ``WRITE_APPEND`` disposition and ``NEWLINE_DELIMITED_JSON``
        source format so that new rows are appended without truncating
        existing data.
        """
        if not self._available:
            logger.warning("load_from_gcs skipped: BigQuery client not available.")
            return

        try:
            table_id = self._full_table_id(table)
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=True,
            )
            load_job = self._client.load_table_from_uri(
                gcs_uri,
                table_id,
                job_config=job_config,
            )
            load_job.result()  # wait for completion
            logger.info(
                "Loaded %s into %s (rows loaded: %s).",
                gcs_uri,
                table_id,
                load_job.output_rows,
            )
        except Exception:
            logger.warning(
                "BigQuery load_from_gcs failed for uri=%s table=%s",
                gcs_uri,
                table,
                exc_info=True,
            )

    # -- private helpers -----------------------------------------------------

    @staticmethod
    def _python_type_to_bq(value: Any) -> str:
        """Map a Python value to a BigQuery scalar type string."""
        if isinstance(value, bool):
            return "BOOL"
        if isinstance(value, int):
            return "INT64"
        if isinstance(value, float):
            return "FLOAT64"
        return "STRING"
