"""
test_phase_2_3_export.py — Validación de Fase 2.3: Data Types y Export Parquet a GCS
======================================================================================
Valida la implementación de la Tarea 2.3 del PRD:

✅ Contrato ABC (GoldLayerExportPort)
✅ Enforcement de esquema final estricto (PVOD_FINAL_SCHEMA)
✅ Serialización a Apache Parquet con compresión Zstandard
✅ Generación correcta de blob names con timestamp UTC
✅ GCSParquetExporter implementa el contrato
✅ Validación de columnas faltantes lanza DataTransformationError
✅ Selección y ordenamiento de columnas según esquema final

Referencia PRD §4 — Exportación Parquet y §6 — Tarea 2.3.
"""

from __future__ import annotations

import sys
import tempfile
from abc import ABC
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

# ── Resolver imports ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.application.gold_layer_port import GoldLayerExportPort
from app.domain.constants import (
    GCS_GOLD_PREFIX,
    LMD_COLUMNS,
    NWP_COLUMNS,
    NWP_LMD_DELTA_PAIRS,
    PARQUET_BLOB_PREFIX,
    PARQUET_COMPRESSION,
    PVOD_FINAL_SCHEMA,
    STATION_COLUMN,
    TARGET_COLUMN,
    TEMPORAL_COLUMN,
)
from app.domain.exceptions import DataTransformationError, SolarETLError
from app.infrastructure.gcs_parquet_exporter import GCSParquetExporter


# ══════════════════════════════════════════════════════════════════════
# 1. CONTRATO ABC — Puerto de Exportación (Gold Layer)
# ══════════════════════════════════════════════════════════════════════

class TestGoldLayerExportPort:
    """Verifica el contrato GoldLayerExportPort (Clean Architecture)."""

    def test_is_abstract_class(self):
        """GoldLayerExportPort debe ser una clase abstracta."""
        assert issubclass(GoldLayerExportPort, ABC)

    def test_cannot_instantiate_directly(self):
        """No se puede instanciar el puerto abstracto directamente."""
        with pytest.raises(TypeError):
            GoldLayerExportPort()

    def test_has_export_method(self):
        """El contrato debe definir export_to_gold_layer."""
        assert hasattr(GoldLayerExportPort, "export_to_gold_layer")

    def test_gcs_exporter_implements_contract(self):
        """GCSParquetExporter implementa GoldLayerExportPort."""
        assert issubclass(GCSParquetExporter, GoldLayerExportPort)


# ══════════════════════════════════════════════════════════════════════
# 2. ESQUEMA FINAL ESTRICTO — PVOD_FINAL_SCHEMA
# ══════════════════════════════════════════════════════════════════════

class TestFinalSchema:
    """Valida la definición del esquema final en constants.py."""

    def test_schema_contains_temporal_column(self):
        """El esquema debe incluir date_time como Datetime."""
        assert TEMPORAL_COLUMN in PVOD_FINAL_SCHEMA
        assert PVOD_FINAL_SCHEMA[TEMPORAL_COLUMN] == "Datetime"

    def test_schema_contains_station_id(self):
        """El esquema debe incluir station_id como UInt8."""
        assert STATION_COLUMN in PVOD_FINAL_SCHEMA
        assert PVOD_FINAL_SCHEMA[STATION_COLUMN] == "UInt8"

    def test_schema_contains_all_nwp_columns(self):
        """El esquema debe incluir todas las columnas NWP como Float64."""
        for col in NWP_COLUMNS:
            assert col in PVOD_FINAL_SCHEMA, f"Falta columna NWP en esquema: {col}"
            assert PVOD_FINAL_SCHEMA[col] == "Float64"

    def test_schema_contains_all_lmd_columns(self):
        """El esquema debe incluir todas las columnas LMD como Float64."""
        for col in LMD_COLUMNS:
            assert col in PVOD_FINAL_SCHEMA, f"Falta columna LMD en esquema: {col}"
            assert PVOD_FINAL_SCHEMA[col] == "Float64"

    def test_schema_contains_power_target(self):
        """El esquema debe incluir power como Float64."""
        assert TARGET_COLUMN in PVOD_FINAL_SCHEMA
        assert PVOD_FINAL_SCHEMA[TARGET_COLUMN] == "Float64"

    def test_schema_contains_delta_columns(self):
        """El esquema debe incluir las 4 columnas delta como Float64."""
        for _, _, delta_name in NWP_LMD_DELTA_PAIRS:
            assert delta_name in PVOD_FINAL_SCHEMA, \
                f"Falta columna delta en esquema: {delta_name}"
            assert PVOD_FINAL_SCHEMA[delta_name] == "Float64"

    def test_schema_has_expected_column_count(self):
        """El esquema debe tener exactamente 19 columnas."""
        # 1 temporal + 1 station + 7 NWP + 6 LMD + 1 power + 4 deltas = 20
        expected = 1 + 1 + len(NWP_COLUMNS) + len(LMD_COLUMNS) + 1 + len(NWP_LMD_DELTA_PAIRS)
        assert len(PVOD_FINAL_SCHEMA) == expected, \
            f"Esquema tiene {len(PVOD_FINAL_SCHEMA)} columnas, esperadas {expected}"


# ══════════════════════════════════════════════════════════════════════
# 3. ENFORCEMENT DE TIPOS — _enforce_final_schema
# ══════════════════════════════════════════════════════════════════════

class TestSchemaEnforcement:
    """Valida el enforcement de tipos estrictos antes del export."""

    def test_enforce_casts_all_types(self, cleaned_dataframe):
        """enforce_final_schema debe castear todas las columnas al tipo correcto."""
        result = GCSParquetExporter._enforce_final_schema(cleaned_dataframe)

        for col_name, type_name in PVOD_FINAL_SCHEMA.items():
            actual_type = result.schema[col_name]
            if type_name == "Float64":
                assert actual_type == pl.Float64, \
                    f"'{col_name}': esperado Float64, obtenido {actual_type}"
            elif type_name == "UInt8":
                assert actual_type == pl.UInt8, \
                    f"'{col_name}': esperado UInt8, obtenido {actual_type}"
            elif type_name == "Datetime":
                assert actual_type == pl.Datetime or str(actual_type).startswith("Datetime"), \
                    f"'{col_name}': esperado Datetime, obtenido {actual_type}"

    def test_enforce_selects_only_schema_columns(self, cleaned_dataframe):
        """Solo las columnas del esquema final deben permanecer."""
        result = GCSParquetExporter._enforce_final_schema(cleaned_dataframe)
        assert set(result.columns) == set(PVOD_FINAL_SCHEMA.keys())

    def test_enforce_raises_on_missing_columns(self):
        """Debe lanzar DataTransformationError si faltan columnas."""
        # DataFrame incompleto
        df = pl.DataFrame({
            "date_time": [datetime(2018, 7, 1)],
            "station_id": [0],
        })

        with pytest.raises(DataTransformationError, match="Faltan columnas"):
            GCSParquetExporter._enforce_final_schema(df)

    def test_enforce_preserves_row_count(self, cleaned_dataframe):
        """El enforcement no debe eliminar filas."""
        result = GCSParquetExporter._enforce_final_schema(cleaned_dataframe)
        assert result.height == cleaned_dataframe.height


# ══════════════════════════════════════════════════════════════════════
# 4. SERIALIZACIÓN PARQUET — Compresión y Formato
# ══════════════════════════════════════════════════════════════════════

class TestParquetSerialization:
    """Valida la serialización a Apache Parquet con compresión."""

    def test_compression_is_zstd(self):
        """La compresión configurada debe ser Zstandard (zstd)."""
        assert PARQUET_COMPRESSION == "zstd"

    def test_write_parquet_creates_valid_file(self, cleaned_dataframe):
        """_write_parquet debe crear un archivo Parquet válido en disco."""
        enforced_df = GCSParquetExporter._enforce_final_schema(cleaned_dataframe)
        parquet_path = GCSParquetExporter._write_parquet(enforced_df)

        try:
            assert parquet_path.exists()
            assert parquet_path.suffix == ".parquet"
            assert parquet_path.stat().st_size > 0

            # Verificar que Polars puede leer el Parquet correctamente
            read_back = pl.read_parquet(parquet_path)
            assert read_back.height == enforced_df.height
            assert set(read_back.columns) == set(enforced_df.columns)
        finally:
            # Limpiar archivo temporal
            parquet_path.unlink(missing_ok=True)

    def test_parquet_roundtrip_preserves_data(self, cleaned_dataframe):
        """Los datos deben sobrevivir un roundtrip Parquet sin pérdida."""
        enforced_df = GCSParquetExporter._enforce_final_schema(cleaned_dataframe)
        parquet_path = GCSParquetExporter._write_parquet(enforced_df)

        try:
            read_back = pl.read_parquet(parquet_path)

            # Comparar valores numéricos (Float64)
            for col in NWP_COLUMNS:
                original = enforced_df[col].round(6)
                roundtrip = read_back[col].round(6)
                assert original.equals(roundtrip), \
                    f"Columna '{col}' cambió en el roundtrip Parquet"
        finally:
            parquet_path.unlink(missing_ok=True)

    def test_parquet_file_is_compressed(self, cleaned_dataframe):
        """El Parquet comprimido debe ser más pequeño que el CSV equivalente."""
        enforced_df = GCSParquetExporter._enforce_final_schema(cleaned_dataframe)
        parquet_path = GCSParquetExporter._write_parquet(enforced_df)

        try:
            parquet_size = parquet_path.stat().st_size

            # Escribir CSV para comparar
            csv_path = parquet_path.with_suffix(".csv")
            enforced_df.write_csv(csv_path)
            csv_size = csv_path.stat().st_size

            assert parquet_size < csv_size, \
                f"Parquet ({parquet_size}B) no es más pequeño que CSV ({csv_size}B)"

            csv_path.unlink(missing_ok=True)
        finally:
            parquet_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════
# 5. BLOB NAMING — Convención GCS
# ══════════════════════════════════════════════════════════════════════

class TestBlobNaming:
    """Valida la generación de nombres de blob para GCS."""

    def test_blob_name_has_gold_prefix(self):
        """El blob name debe empezar con 'gold/' (Capa Oro)."""
        blob_name = GCSParquetExporter._generate_blob_name()
        assert blob_name.startswith(GCS_GOLD_PREFIX)

    def test_blob_name_has_pvod_prefix(self):
        """El blob name debe incluir el prefijo 'pvod_'."""
        blob_name = GCSParquetExporter._generate_blob_name()
        assert PARQUET_BLOB_PREFIX in blob_name

    def test_blob_name_has_parquet_extension(self):
        """El blob name debe terminar en '.parquet'."""
        blob_name = GCSParquetExporter._generate_blob_name()
        assert blob_name.endswith(".parquet")

    def test_blob_name_contains_timestamp(self):
        """El blob name debe contener un timestamp UTC válido."""
        blob_name = GCSParquetExporter._generate_blob_name()
        # Extraer parte del timestamp: pvod_YYYYMMDD_HHMMSS
        ts_part = blob_name.replace(GCS_GOLD_PREFIX, "").replace(
            PARQUET_BLOB_PREFIX, ""
        ).replace(".parquet", "")
        # Verificar formato YYYYMMDD_HHMMSS
        assert len(ts_part) == 15  # YYYYMMDD_HHMMSS
        datetime.strptime(ts_part, "%Y%m%d_%H%M%S")  # No debe lanzar excepción

    def test_blob_names_are_unique(self):
        """Dos llamadas consecutivas deben generar nombres distintos (o iguales en el mismo segundo)."""
        import time
        name1 = GCSParquetExporter._generate_blob_name()
        time.sleep(1.1)  # Esperar >1 segundo para garantizar unicidad
        name2 = GCSParquetExporter._generate_blob_name()
        assert name1 != name2


# ══════════════════════════════════════════════════════════════════════
# 6. GCS UPLOAD — Mock (sin conexión real a GCS)
# ══════════════════════════════════════════════════════════════════════

class TestGCSUploadMocked:
    """Valida el flujo de upload a GCS usando mocks."""

    def test_upload_returns_gs_uri(self, cleaned_dataframe):
        """export_to_gold_layer debe retornar un URI gs://."""
        exporter = GCSParquetExporter(
            bucket_name="test-bucket",
            credentials_path=None,
        )

        with patch.object(exporter, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/gold/pvod_20180701_120000.parquet"

            uri = exporter.export_to_gold_layer(cleaned_dataframe)

            assert uri.startswith("gs://")
            assert "test-bucket" in uri
            assert "gold/" in uri
            assert uri.endswith(".parquet")

    def test_upload_called_with_correct_args(self, cleaned_dataframe):
        """El upload a GCS debe recibir la ruta local y el blob name."""
        exporter = GCSParquetExporter(
            bucket_name="test-bucket",
            credentials_path=None,
        )

        with patch.object(exporter, "_upload_to_gcs") as mock_upload:
            mock_upload.return_value = "gs://test-bucket/gold/test.parquet"

            exporter.export_to_gold_layer(cleaned_dataframe)

            mock_upload.assert_called_once()
            args = mock_upload.call_args
            local_path = args[0][0]
            blob_name = args[0][1]

            assert isinstance(local_path, Path)
            assert local_path.suffix == ".parquet"
            assert blob_name.startswith("gold/")
            assert blob_name.endswith(".parquet")
