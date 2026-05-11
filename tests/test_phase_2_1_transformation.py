"""
test_phase_2_1_transformation.py — Validación de Fase 2.1: Carga Lazy y Alineamiento
======================================================================================
Valida la implementación de la Tarea 2.1 del PRD:

✅ Contrato ABC (PVODTransformationPipeline)
✅ Carga lazy via pl.scan_csv() — no materializa hasta .collect()
✅ Parsing temporal y truncamiento a grilla de 15 minutos exactos
✅ Tipado estricto de columnas (Float64, UInt8, Datetime)
✅ Cálculo de columnas delta NWP - LMD
✅ Validación de integridad temporal (sin duplicados ni desalineamiento)
✅ Validación de restricciones físicas de irradiancia [0, 1361] W/m²
✅ Abortar ejecución ante violaciones físicas (PRD §4)

Referencia PRD §6 — Fase 2, Tarea 2.1.
"""

from __future__ import annotations

import io
import sys
from abc import ABC
from pathlib import Path

import polars as pl
import pytest

# ── Resolver imports ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.application.transformation_ports import PVODTransformationPipeline
from app.domain.constants import (
    IRRADIANCE_COLUMNS,
    LMD_COLUMNS,
    NWP_COLUMNS,
    NWP_LMD_DELTA_PAIRS,
    SOLAR_CONSTANT_W_M2,
    STATION_COLUMN,
    TARGET_COLUMN,
    TEMPORAL_COLUMN,
)
from app.domain.exceptions import (
    DataTransformationError,
    IrradianceOutOfBoundsError,
    TemporalAlignmentError,
)
from app.infrastructure.pvod_lazy_loader import PVODLazyLoader


# ══════════════════════════════════════════════════════════════════════
# 1. CONTRATO ABC — Puerto de Transformación
# ══════════════════════════════════════════════════════════════════════

class TestTransformationPort:
    """Verifica el contrato PVODTransformationPipeline (Clean Architecture)."""

    def test_is_abstract_class(self):
        """PVODTransformationPipeline debe ser una clase abstracta."""
        assert issubclass(PVODTransformationPipeline, ABC)

    def test_cannot_instantiate_directly(self):
        """No se puede instanciar el puerto abstracto directamente."""
        with pytest.raises(TypeError):
            PVODTransformationPipeline()

    def test_has_load_and_align_method(self):
        """El contrato debe definir load_and_align."""
        assert hasattr(PVODTransformationPipeline, "load_and_align")

    def test_pvod_lazy_loader_implements_contract(self):
        """PVODLazyLoader implementa PVODTransformationPipeline."""
        assert issubclass(PVODLazyLoader, PVODTransformationPipeline)


# ══════════════════════════════════════════════════════════════════════
# 2. CARGA LAZY — scan_csv y LazyFrame
# ══════════════════════════════════════════════════════════════════════

class TestLazyLoading:
    """Valida que la carga es lazy (plan de ejecución sin materializar)."""

    def test_load_and_align_returns_lazy_frame(self, csv_buffer):
        """El resultado debe ser un pl.LazyFrame (no DataFrame eager)."""
        loader = PVODLazyLoader()
        result = loader.load_and_align(csv_buffer)
        assert isinstance(result, pl.LazyFrame)

    def test_lazy_frame_has_correct_schema(self, csv_buffer):
        """El LazyFrame debe tener el esquema correcto (incluyendo deltas)."""
        loader = PVODLazyLoader()
        lf = loader.load_and_align(csv_buffer)
        schema = lf.collect_schema()

        # Columnas base
        assert TEMPORAL_COLUMN in schema.names()
        assert STATION_COLUMN in schema.names()
        assert TARGET_COLUMN in schema.names()

        # Columnas NWP
        for col in NWP_COLUMNS:
            assert col in schema.names(), f"Falta columna NWP: {col}"

        # Columnas LMD
        for col in LMD_COLUMNS:
            assert col in schema.names(), f"Falta columna LMD: {col}"

        # Columnas Delta
        for _, _, delta_name in NWP_LMD_DELTA_PAIRS:
            assert delta_name in schema.names(), f"Falta columna delta: {delta_name}"

    def test_collect_produces_dataframe(self, csv_buffer):
        """Materializar con .collect() produce un pl.DataFrame."""
        loader = PVODLazyLoader()
        lf = loader.load_and_align(csv_buffer)
        df = lf.collect()
        assert isinstance(df, pl.DataFrame)
        assert df.height > 0


# ══════════════════════════════════════════════════════════════════════
# 3. ALINEAMIENTO TEMPORAL — Grilla de 15 Minutos
# ══════════════════════════════════════════════════════════════════════

class TestTemporalAlignment:
    """Valida el truncamiento y alineamiento a 15 min exactos."""

    def test_datetime_column_is_datetime_type(self, aligned_dataframe):
        """La columna date_time debe ser de tipo pl.Datetime."""
        dtype = aligned_dataframe.schema[TEMPORAL_COLUMN]
        assert dtype == pl.Datetime or dtype.is_(pl.Datetime)

    def test_all_minutes_are_multiples_of_15(self, aligned_dataframe):
        """Todos los minutos deben ser múltiplos exactos de 15 (0, 15, 30, 45)."""
        minutes = aligned_dataframe.select(
            pl.col(TEMPORAL_COLUMN).dt.minute().alias("minute")
        )["minute"].unique().to_list()

        valid_minutes = {0, 15, 30, 45}
        for m in minutes:
            assert m in valid_minutes, f"Minuto no alineado: {m}"

    def test_no_duplicate_timestamps_per_station(self, aligned_dataframe):
        """No deben existir timestamps duplicados dentro de una misma estación."""
        duplicates = (
            aligned_dataframe
            .group_by([STATION_COLUMN, TEMPORAL_COLUMN])
            .agg(pl.len().alias("count"))
            .filter(pl.col("count") > 1)
        )
        assert duplicates.height == 0, f"Se encontraron {duplicates.height} duplicados"


# ══════════════════════════════════════════════════════════════════════
# 4. TIPADO ESTRICTO — Float64, UInt8, Datetime
# ══════════════════════════════════════════════════════════════════════

class TestStrictTyping:
    """Valida el casting estricto de tipos del esquema PVOD."""

    def test_station_id_is_uint8(self, aligned_dataframe):
        """station_id debe ser UInt8 (PRD §4)."""
        assert aligned_dataframe.schema[STATION_COLUMN] == pl.UInt8

    def test_numeric_columns_are_float64(self, aligned_dataframe):
        """Todas las columnas numéricas (NWP + LMD + power) deben ser Float64."""
        numeric_cols = list(NWP_COLUMNS) + list(LMD_COLUMNS) + [TARGET_COLUMN]
        for col in numeric_cols:
            assert aligned_dataframe.schema[col] == pl.Float64, \
                f"Columna '{col}' tiene tipo {aligned_dataframe.schema[col]}, esperado Float64"

    def test_delta_columns_are_float64(self, aligned_dataframe):
        """Las columnas delta NWP-LMD deben ser Float64."""
        for _, _, delta_name in NWP_LMD_DELTA_PAIRS:
            assert aligned_dataframe.schema[delta_name] == pl.Float64, \
                f"Delta '{delta_name}' tiene tipo {aligned_dataframe.schema[delta_name]}"


# ══════════════════════════════════════════════════════════════════════
# 5. COLUMNAS DELTA — NWP - LMD
# ══════════════════════════════════════════════════════════════════════

class TestNWPLMDDeltas:
    """Valida el cálculo de desviación NWP vs LMD."""

    def test_delta_columns_exist(self, aligned_dataframe):
        """Las 4 columnas delta deben existir en el DataFrame."""
        for _, _, delta_name in NWP_LMD_DELTA_PAIRS:
            assert delta_name in aligned_dataframe.columns

    def test_delta_values_are_correct(self, aligned_dataframe):
        """delta = nwp_value - lmd_value para cada par."""
        df = aligned_dataframe.head(10)
        for nwp_col, lmd_col, delta_name in NWP_LMD_DELTA_PAIRS:
            expected = (df[nwp_col] - df[lmd_col]).round(6)
            actual = df[delta_name].round(6)
            assert expected.equals(actual), \
                f"Delta incorrecto para {delta_name}: esperado {expected}, obtenido {actual}"


# ══════════════════════════════════════════════════════════════════════
# 6. VALIDACIONES FÍSICAS — Irradiancia y Temporal
# ══════════════════════════════════════════════════════════════════════

class TestPhysicalValidations:
    """Valida las restricciones físicas exigidas por el PRD §4."""

    def test_irradiance_within_bounds(self, aligned_dataframe):
        """La irradiancia debe estar en [0, 1361] W/m² (constante solar)."""
        for col_name in IRRADIANCE_COLUMNS:
            col = aligned_dataframe[col_name].drop_nulls()
            min_val = col.min()
            max_val = col.max()
            assert min_val >= 0.0, \
                f"'{col_name}' tiene valor negativo: {min_val}"
            assert max_val <= SOLAR_CONSTANT_W_M2, \
                f"'{col_name}' excede la constante solar: {max_val}"

    def test_aborts_on_negative_irradiance(self, csv_buffer_negative_irradiance):
        """Debe abortar con IrradianceOutOfBoundsError si hay irradiancia negativa."""
        loader = PVODLazyLoader()
        with pytest.raises(IrradianceOutOfBoundsError):
            loader.load_and_align(csv_buffer_negative_irradiance)

    def test_station_ids_in_valid_range(self, aligned_dataframe):
        """Los station_id deben estar en el rango [0, 9]."""
        station_ids = aligned_dataframe[STATION_COLUMN].unique().sort().to_list()
        assert all(0 <= sid <= 9 for sid in station_ids)

    def test_row_count_matches_expected(self, aligned_dataframe):
        """El conteo de filas del dataset sintético debe coincidir con el esperado."""
        # Dataset sintético: 10 estaciones × 96 registros = 960
        assert aligned_dataframe.height == 960


# ══════════════════════════════════════════════════════════════════════
# 7. EXCEPCIONES DE TRANSFORMACIÓN
# ══════════════════════════════════════════════════════════════════════

class TestTransformationExceptions:
    """Valida la jerarquía de excepciones de transformación."""

    def test_temporal_alignment_error_hierarchy(self):
        """TemporalAlignmentError hereda de DataTransformationError."""
        assert issubclass(TemporalAlignmentError, DataTransformationError)

    def test_irradiance_out_of_bounds_hierarchy(self):
        """IrradianceOutOfBoundsError hereda de DataTransformationError."""
        assert issubclass(IrradianceOutOfBoundsError, DataTransformationError)

    def test_data_transformation_inherits_from_base(self):
        """DataTransformationError hereda de SolarETLError."""
        from app.domain.exceptions import SolarETLError
        assert issubclass(DataTransformationError, SolarETLError)
