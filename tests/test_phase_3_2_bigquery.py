"""
test_phase_3_2_bigquery.py — Tests para la Integración de BigQuery
===================================================================
Verifica el comportamiento del adaptador BigQueryAdapter:
1. Cada ejecución genera un Job ID único (UUID).
2. Configuración adecuada del LoadJob (WRITE_TRUNCATE, Particiones, Clustering).
3. Validación post-carga del conteo de filas.
4. Manejo de excepciones en caso de fallo del SDK de GCP.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.exceptions import BigQueryConnectionError
from app.infrastructure.bigquery_adapter import BigQueryAdapter


@pytest.fixture
def bq_adapter() -> BigQueryAdapter:
    return BigQueryAdapter(
        project_id="test-project",
        dataset_id="test_dataset",
        table_id="pvod_metrics",
        bucket_name="test-bucket",
    )


def test_job_id_is_unique_per_call(bq_adapter: BigQueryAdapter):
    """Verifica que cada llamada genera un Job ID UUID distinto (no determinista)."""
    with patch("google.cloud.bigquery.Client") as mock_bq_class:
        mock_bq_client = mock_bq_class.return_value
        mock_load_job = mock_bq_client.load_table_from_uri.return_value
        mock_load_job.job_id = "pvod_load_uuid1"
        mock_load_job.output_rows = 271967

        mock_table = MagicMock()
        mock_table.num_rows = 271967
        mock_bq_client.get_table.return_value = mock_table

        gcs_uri = "gs://test-bucket/gold/pvod_123.parquet"

        bq_adapter.load_dataframe_idempotent(gcs_uri)
        call1_job_id = mock_bq_client.load_table_from_uri.call_args.kwargs["job_id"]

        bq_adapter.load_dataframe_idempotent(gcs_uri)
        call2_job_id = mock_bq_client.load_table_from_uri.call_args.kwargs["job_id"]

        # Cada llamada debe generar un Job ID diferente
        assert call1_job_id != call2_job_id
        assert call1_job_id.startswith("pvod_load_")
        assert call2_job_id.startswith("pvod_load_")


@patch("google.cloud.bigquery.Client")
def test_load_dataframe_idempotent_success(
    mock_bq_client_class, bq_adapter: BigQueryAdapter
):
    """Verifica la ejecución exitosa de la carga hacia BigQuery con WRITE_TRUNCATE."""

    gcs_uri = "gs://test-bucket/gold/file.parquet"

    # Configurar mock de BigQuery
    mock_bq_client = mock_bq_client_class.return_value
    mock_load_job = mock_bq_client.load_table_from_uri.return_value
    mock_load_job.job_id = "mocked_job_id_123"
    mock_load_job.output_rows = 271967

    # Mock de get_table para validación post-carga
    mock_table = MagicMock()
    mock_table.num_rows = 271967
    mock_bq_client.get_table.return_value = mock_table

    # Ejecutar
    result_job_id = bq_adapter.load_dataframe_idempotent(gcs_uri)

    # Verificaciones BigQuery
    mock_bq_client.load_table_from_uri.assert_called_once()

    kwargs = mock_bq_client.load_table_from_uri.call_args.kwargs

    assert kwargs["source_uris"] == gcs_uri
    assert kwargs["destination"] == "test-project.test_dataset.pvod_metrics"
    assert "pvod_load_" in kwargs["job_id"]

    job_config = kwargs["job_config"]
    from google.cloud import bigquery
    assert job_config.source_format == bigquery.SourceFormat.PARQUET
    assert job_config.time_partitioning.field == "date_time"
    assert job_config.clustering_fields == ["station_id"]
    # CRÍTICO: Debe ser WRITE_TRUNCATE, NO WRITE_APPEND
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_TRUNCATE

    # Verifica que llamamos a result() para esperar
    mock_load_job.result.assert_called_once()

    # Verifica validación post-carga
    mock_bq_client.get_table.assert_called_once_with(
        "test-project.test_dataset.pvod_metrics"
    )

    # Retorna el job_id correcto
    assert result_job_id == "mocked_job_id_123"


@patch("google.cloud.bigquery.Client")
def test_load_dataframe_idempotent_bq_failure(
    mock_bq_client_class, bq_adapter: BigQueryAdapter
):
    """Verifica que las excepciones de BQ se envuelven en BigQueryConnectionError."""

    mock_bq_client = mock_bq_client_class.return_value
    mock_load_job = mock_bq_client.load_table_from_uri.return_value

    # Forzar error de GCP
    mock_load_job.result.side_effect = Exception("Google API Error: Backend offline")

    gcs_uri = "gs://test-bucket/gold/file.parquet"

    with pytest.raises(BigQueryConnectionError, match="Google API Error"):
        bq_adapter.load_dataframe_idempotent(gcs_uri)


@patch("google.cloud.bigquery.Client")
def test_validate_row_count_warns_on_mismatch(
    mock_bq_client_class, bq_adapter: BigQueryAdapter
):
    """Verifica que se emite un warning si el conteo de filas no coincide post-carga."""

    gcs_uri = "gs://test-bucket/gold/file.parquet"

    mock_bq_client = mock_bq_client_class.return_value
    mock_load_job = mock_bq_client.load_table_from_uri.return_value
    mock_load_job.job_id = "mocked_job_id_456"
    mock_load_job.output_rows = 271967

    # Simular que la tabla tiene más filas de las esperadas (duplicación)
    mock_table = MagicMock()
    mock_table.num_rows = 1087868  # 4x las filas esperadas
    mock_bq_client.get_table.return_value = mock_table

    import logging

    with patch.object(logging.getLogger("app.infrastructure.bigquery_adapter"), "warning") as mock_warn:
        bq_adapter.load_dataframe_idempotent(gcs_uri)

        # Debe haber emitido un warning de integridad
        warning_calls = [
            call
            for call in mock_warn.call_args_list
            if "ALERTA DE INTEGRIDAD" in str(call)
        ]
        assert len(warning_calls) >= 1
