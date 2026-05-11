"""
test_phase_3_2_bigquery.py — Tests para la Integración de BigQuery
===================================================================
Verifica el comportamiento del adaptador BigQueryAdapter:
1. Cálculo correcto del job_id determinista.
2. Configuración adecuada del LoadJob (Particiones, Clustering).
3. Manejo de excepciones en caso de fallo del SDK de GCP.
"""

from __future__ import annotations

import hashlib
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


def test_deterministic_job_id(bq_adapter: BigQueryAdapter):
    """Verifica que el job_id coincida exactamente con la fórmula del PRD."""
    gcs_uri = "gs://test-bucket/gold/pvod_123.parquet"
    blob_md5 = "base64_md5_hash_from_gcs"
    
    # Formula PRD: source_uri + project_id + dataset_id + target_table + hash_contenido_parquet
    expected_seed = f"{gcs_uri}test-projecttest_datasetpvod_metrics{blob_md5}"
    expected_hash = hashlib.md5(expected_seed.encode("utf-8")).hexdigest()
    expected_job_id = f"pvod_load_{expected_hash}"
    
    # Usando método de la clase (exponiendo un método de clase interna o testando la generación)
    # Como el método es _generate_deterministic_job_id, lo testearemos directamente
    actual_job_id = bq_adapter._generate_deterministic_job_id(gcs_uri, blob_md5)
    
    assert actual_job_id == expected_job_id


@patch("google.cloud.storage.Client")
@patch("google.cloud.bigquery.Client")
def test_load_dataframe_idempotent_success(
    mock_bq_client_class, mock_storage_client_class, bq_adapter: BigQueryAdapter
):
    """Verifica la ejecución exitosa de la carga hacia BigQuery."""
    
    gcs_uri = "gs://test-bucket/gold/file.parquet"
    
    # Configurar mock de Storage (Blob)
    mock_storage_client = mock_storage_client_class.return_value
    mock_bucket = mock_storage_client.bucket.return_value
    mock_blob = mock_bucket.get_blob.return_value
    mock_blob.md5_hash = "mocked_md5_hash"
    
    # Configurar mock de BigQuery
    mock_bq_client = mock_bq_client_class.return_value
    mock_load_job = mock_bq_client.load_table_from_uri.return_value
    mock_load_job.job_id = "mocked_job_id_123"
    
    # Mock de bigquery.SourceFormat, TimePartitioningType, etc... al estar mockeando Client, las constantes de módulo igual se importarán del real, lo que está bien.
    
    # Ejecutar
    result_job_id = bq_adapter.load_dataframe_idempotent(gcs_uri)
    
    # Verificaciones Storage
    mock_bucket.get_blob.assert_called_once_with("gold/file.parquet")
    
    # Verificaciones BigQuery
    mock_bq_client.load_table_from_uri.assert_called_once()
    
    kwargs = mock_bq_client.load_table_from_uri.call_args.kwargs
    
    assert kwargs["source_uris"] == gcs_uri
    assert kwargs["destination"] == "test-project.test_dataset.pvod_metrics"
    assert "pvod_load_" in kwargs["job_id"]
    
    job_config = kwargs["job_config"]
    # No usamos isinstance por ser un mock, pero chequeamos atributos
    from google.cloud import bigquery
    assert job_config.source_format == bigquery.SourceFormat.PARQUET
    assert job_config.time_partitioning.field == "date_time"
    assert job_config.clustering_fields == ["station_id"]
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    
    # Verifica que llamamos a result() para esperar
    mock_load_job.result.assert_called_once()
    
    # Retorna el job_id correcto del job de BQ (según implementacion retorna el load_job.job_id)
    assert result_job_id == "mocked_job_id_123"


@patch("google.cloud.storage.Client")
def test_load_dataframe_idempotent_invalid_blob(mock_storage_client_class, bq_adapter: BigQueryAdapter):
    """Verifica que falle si el blob no existe en GCS o no tiene MD5."""
    
    mock_storage_client = mock_storage_client_class.return_value
    mock_bucket = mock_storage_client.bucket.return_value
    mock_bucket.get_blob.return_value = None  # Blob no encontrado
    
    gcs_uri = "gs://test-bucket/gold/not_found.parquet"
    
    with pytest.raises(BigQueryConnectionError, match="No se pudo recuperar metadata del blob"):
        bq_adapter.load_dataframe_idempotent(gcs_uri)


@patch("google.cloud.storage.Client")
@patch("google.cloud.bigquery.Client")
def test_load_dataframe_idempotent_bq_failure(
    mock_bq_client_class, mock_storage_client_class, bq_adapter: BigQueryAdapter
):
    """Verifica que las excepciones de BQ se envuelven en BigQueryConnectionError."""
    
    mock_storage_client = mock_storage_client_class.return_value
    mock_bucket = mock_storage_client.bucket.return_value
    mock_blob = mock_bucket.get_blob.return_value
    mock_blob.md5_hash = "mocked_md5_hash"
    
    mock_bq_client = mock_bq_client_class.return_value
    mock_load_job = mock_bq_client.load_table_from_uri.return_value
    
    # Forzar error de GCP
    mock_load_job.result.side_effect = Exception("Google API Error: Backend offline")
    
    gcs_uri = "gs://test-bucket/gold/file.parquet"
    
    with pytest.raises(BigQueryConnectionError, match="Google API Error"):
        bq_adapter.load_dataframe_idempotent(gcs_uri)
