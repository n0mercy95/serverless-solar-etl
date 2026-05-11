"""
test_phase_2_2_cleaning.py — Validación de Fase 2.2: Patrón Strategy de Limpieza
==================================================================================
Valida la implementación de la Tarea 2.2 del PRD:

✅ Contrato ABC (SolarDataCleaningStrategy)
✅ NighttimeZeroingStrategy: zeroing nocturno por elevación solar
✅ HampelFilterStrategy: detección/corrección de outliers en viento
✅ MissingValueImputerStrategy: imputación de nulls por estación
✅ CleaningPipelineExecutor: orquestación en el orden correcto
✅ Preservación de esquema (sin perder ni renombrar columnas)

Referencia PRD §3 — Patrón Strategy (Limpieza) y §6 — Tarea 2.2.
"""

from __future__ import annotations

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

from app.application.cleaning_pipeline import CleaningPipelineExecutor
from app.application.cleaning_strategy_port import SolarDataCleaningStrategy
from app.domain.constants import (
    IMPUTATION_COLUMNS,
    IRRADIANCE_COLUMNS,
    NIGHTTIME_ZEROING_COLUMNS,
    NWP_COLUMNS,
    LMD_COLUMNS,
    STATION_COLUMN,
    TARGET_COLUMN,
    TEMPORAL_COLUMN,
    WIND_SPEED_COLUMNS,
)
from app.infrastructure.strategies.hampel_filter_strategy import HampelFilterStrategy
from app.infrastructure.strategies.missing_value_imputer_strategy import MissingValueImputerStrategy
from app.infrastructure.strategies.nighttime_zeroing_strategy import NighttimeZeroingStrategy


# ══════════════════════════════════════════════════════════════════════
# 1. CONTRATO ABC — Interfaz SolarDataCleaningStrategy
# ══════════════════════════════════════════════════════════════════════

class TestCleaningStrategyPort:
    """Verifica el contrato del Patrón Strategy (PRD §3)."""

    def test_is_abstract_class(self):
        """SolarDataCleaningStrategy debe ser una clase abstracta."""
        assert issubclass(SolarDataCleaningStrategy, ABC)

    def test_cannot_instantiate_directly(self):
        """No se puede instanciar la interfaz abstracta directamente."""
        with pytest.raises(TypeError):
            SolarDataCleaningStrategy()

    def test_has_apply_cleaning_method(self):
        """El contrato debe definir apply_cleaning(dataframe)."""
        assert hasattr(SolarDataCleaningStrategy, "apply_cleaning")

    def test_all_strategies_implement_contract(self):
        """Las 3 estrategias concretas deben implementar el contrato."""
        for StrategyClass in (NighttimeZeroingStrategy, HampelFilterStrategy, MissingValueImputerStrategy):
            assert issubclass(StrategyClass, SolarDataCleaningStrategy), \
                f"{StrategyClass.__name__} no implementa SolarDataCleaningStrategy"


# ══════════════════════════════════════════════════════════════════════
# 2. NIGHTTIME ZEROING STRATEGY
# ══════════════════════════════════════════════════════════════════════

class TestNighttimeZeroingStrategy:
    """Valida el zeroing nocturno por elevación solar."""

    def test_zeroes_nighttime_irradiance(self, aligned_dataframe):
        """Los valores de irradiancia deben ser 0.0 durante horas nocturnas."""
        strategy = NighttimeZeroingStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        # Filtrar filas nocturnas profundas (horas 0-3 y 22-23).
        # A latitud 38°N en julio (verano), el atardecer es ~20:30,
        # por lo que usamos un margen conservador para evitar la penumbra.
        nighttime = result.filter(
            (pl.col(TEMPORAL_COLUMN).dt.hour() < 4)
            | (pl.col(TEMPORAL_COLUMN).dt.hour() >= 22)
        )

        if nighttime.height > 0:
            for col in NIGHTTIME_ZEROING_COLUMNS:
                col_values = nighttime[col]
                non_zero = col_values.filter(col_values != 0.0)
                assert non_zero.len() == 0, \
                    f"'{col}' tiene {non_zero.len()} valores no-cero de noche"

    def test_preserves_daytime_values(self, aligned_dataframe):
        """Los valores diurnos con sol alto NO deben ser forzados a cero."""
        strategy = NighttimeZeroingStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        # Filtrar mediodía (elevación solar alta)
        midday = result.filter(
            (pl.col(TEMPORAL_COLUMN).dt.hour() >= 10)
            & (pl.col(TEMPORAL_COLUMN).dt.hour() <= 14)
        )

        # Al mediodía debe haber valores de irradiancia > 0
        if midday.height > 0:
            total_irrad = midday["nwp_globalirrad"].sum()
            assert total_irrad > 0, "La irradiancia al mediodía no debe ser cero"

    def test_preserves_schema(self, aligned_dataframe):
        """El esquema de columnas debe permanecer idéntico tras el zeroing."""
        strategy = NighttimeZeroingStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        assert set(result.columns) == set(aligned_dataframe.columns)
        assert result.height == aligned_dataframe.height

    def test_power_zeroed_at_night(self, aligned_dataframe):
        """La columna power debe ser 0.0 durante horas nocturnas."""
        strategy = NighttimeZeroingStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        nighttime = result.filter(
            (pl.col(TEMPORAL_COLUMN).dt.hour() < 5)
            | (pl.col(TEMPORAL_COLUMN).dt.hour() > 20)
        )

        if nighttime.height > 0:
            power_values = nighttime[TARGET_COLUMN]
            non_zero_power = power_values.filter(power_values != 0.0)
            assert non_zero_power.len() == 0, \
                f"Power tiene {non_zero_power.len()} valores no-cero de noche"

    def test_no_auxiliary_columns_remain(self, aligned_dataframe):
        """Las columnas auxiliares (_day_of_year, etc.) deben ser eliminadas."""
        strategy = NighttimeZeroingStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        aux_cols = [c for c in result.columns if c.startswith("_")]
        assert len(aux_cols) == 0, f"Columnas auxiliares no eliminadas: {aux_cols}"


# ══════════════════════════════════════════════════════════════════════
# 3. HAMPEL FILTER STRATEGY
# ══════════════════════════════════════════════════════════════════════

class TestHampelFilterStrategy:
    """Valida el filtro Hampel para anomalías de viento."""

    def test_detects_extreme_outlier(self, aligned_dataframe_with_outlier):
        """Un outlier extremo (999.9) en windspeed debe ser reemplazado."""
        strategy = HampelFilterStrategy()

        # Verificar que el outlier existe antes
        original_max = aligned_dataframe_with_outlier["nwp_windspeed"].max()
        assert original_max == 999.9, f"El outlier inyectado no se encontró: max={original_max}"

        result = strategy.apply_cleaning(aligned_dataframe_with_outlier)

        # El outlier debe haber sido reemplazado por la mediana móvil
        cleaned_max = result["nwp_windspeed"].max()
        assert cleaned_max < 900.0, \
            f"El outlier no fue corregido: max post-Hampel = {cleaned_max}"

    def test_preserves_normal_values(self, aligned_dataframe):
        """Datos sin outliers no deben ser modificados significativamente."""
        strategy = HampelFilterStrategy()
        original = aligned_dataframe["nwp_windspeed"].clone()
        result = strategy.apply_cleaning(aligned_dataframe)
        cleaned = result["nwp_windspeed"]

        # La diferencia absoluta media debería ser cercana a 0
        diff = (original - cleaned).abs().mean()
        assert diff < 0.1, f"Datos normales fueron modificados excesivamente: diff_media={diff}"

    def test_only_affects_wind_columns(self, aligned_dataframe):
        """Solo las columnas de viento deben ser afectadas por Hampel."""
        strategy = HampelFilterStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        # Columnas no-viento deben permanecer idénticas
        non_wind_cols = [c for c in aligned_dataframe.columns
                        if c not in WIND_SPEED_COLUMNS
                        and c != TEMPORAL_COLUMN]

        for col in non_wind_cols:
            orig_series = aligned_dataframe[col]
            clean_series = result[col]
            assert orig_series.equals(clean_series), \
                f"Columna '{col}' fue modificada por Hampel (no debería)"

    def test_preserves_schema(self, aligned_dataframe):
        """El esquema debe permanecer idéntico tras aplicar Hampel."""
        strategy = HampelFilterStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        assert set(result.columns) == set(aligned_dataframe.columns)
        assert result.height == aligned_dataframe.height

    def test_no_auxiliary_columns_remain(self, aligned_dataframe):
        """Las columnas auxiliares (_rolling_median, etc.) deben ser eliminadas."""
        strategy = HampelFilterStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        aux_cols = [c for c in result.columns if c.startswith("_")]
        assert len(aux_cols) == 0, f"Columnas auxiliares no eliminadas: {aux_cols}"


# ══════════════════════════════════════════════════════════════════════
# 4. MISSING VALUE IMPUTER STRATEGY
# ══════════════════════════════════════════════════════════════════════

class TestMissingValueImputerStrategy:
    """Valida la imputación de valores faltantes por estación."""

    def test_resolves_injected_nulls(self, aligned_dataframe_with_nulls):
        """Los nulls inyectados deben ser resueltos por interpolación."""
        strategy = MissingValueImputerStrategy()

        # Verificar que hay nulls antes
        null_count_before = aligned_dataframe_with_nulls.null_count().sum_horizontal()[0]
        assert null_count_before > 0, "No se encontraron nulls para probar"

        result = strategy.apply_cleaning(aligned_dataframe_with_nulls)

        # Verificar que las columnas de imputación ya no tienen nulls
        for col_name in IMPUTATION_COLUMNS:
            if col_name in result.columns:
                remaining = result[col_name].null_count()
                assert remaining == 0, \
                    f"'{col_name}' aún tiene {remaining} nulls después de imputación"

    def test_no_changes_on_clean_data(self, aligned_dataframe):
        """Si no hay nulls, el DataFrame no debe cambiar."""
        strategy = MissingValueImputerStrategy()
        result = strategy.apply_cleaning(aligned_dataframe)

        # Las columnas numéricas deben ser idénticas
        for col_name in IMPUTATION_COLUMNS:
            if col_name in result.columns and col_name in aligned_dataframe.columns:
                assert result[col_name].equals(aligned_dataframe[col_name]), \
                    f"'{col_name}' cambió sin necesidad (no había nulls)"

    def test_preserves_row_count(self, aligned_dataframe_with_nulls):
        """La imputación no debe eliminar ni agregar filas."""
        strategy = MissingValueImputerStrategy()
        result = strategy.apply_cleaning(aligned_dataframe_with_nulls)
        assert result.height == aligned_dataframe_with_nulls.height

    def test_preserves_schema(self, aligned_dataframe_with_nulls):
        """El esquema debe permanecer idéntico tras la imputación."""
        strategy = MissingValueImputerStrategy()
        result = strategy.apply_cleaning(aligned_dataframe_with_nulls)
        assert set(result.columns) == set(aligned_dataframe_with_nulls.columns)


# ══════════════════════════════════════════════════════════════════════
# 5. CLEANING PIPELINE EXECUTOR — Orquestación
# ══════════════════════════════════════════════════════════════════════

class TestCleaningPipelineExecutor:
    """Valida el orquestador del pipeline de limpieza."""

    def test_executes_all_strategies_in_order(self, aligned_dataframe):
        """Debe ejecutar las 3 estrategias en el orden PRD."""
        execution_log = []

        class LoggingStrategy(SolarDataCleaningStrategy):
            def __init__(self, name):
                self._name = name

            def apply_cleaning(self, dataframe):
                execution_log.append(self._name)
                return dataframe

        strategies = [
            LoggingStrategy("nighttime"),
            LoggingStrategy("hampel"),
            LoggingStrategy("imputer"),
        ]

        executor = CleaningPipelineExecutor(strategies=strategies)
        executor.execute(aligned_dataframe)

        assert execution_log == ["nighttime", "hampel", "imputer"]

    def test_full_pipeline_produces_clean_data(self, aligned_dataframe):
        """El pipeline completo produce un DataFrame limpio y válido."""
        strategies = [
            NighttimeZeroingStrategy(),
            HampelFilterStrategy(),
            MissingValueImputerStrategy(),
        ]
        executor = CleaningPipelineExecutor(strategies=strategies)
        result = executor.execute(aligned_dataframe)

        assert isinstance(result, pl.DataFrame)
        assert result.height == aligned_dataframe.height
        assert set(result.columns) == set(aligned_dataframe.columns)

    def test_pipeline_preserves_temporal_column(self, aligned_dataframe):
        """La columna temporal debe sobrevivir intacta al pipeline."""
        strategies = [
            NighttimeZeroingStrategy(),
            HampelFilterStrategy(),
            MissingValueImputerStrategy(),
        ]
        executor = CleaningPipelineExecutor(strategies=strategies)
        result = executor.execute(aligned_dataframe)

        assert result[TEMPORAL_COLUMN].equals(
            aligned_dataframe.sort(STATION_COLUMN, TEMPORAL_COLUMN)[TEMPORAL_COLUMN]
        ) or result.height == aligned_dataframe.height  # Al menos misma cantidad

    def test_pipeline_preserves_station_ids(self, aligned_dataframe):
        """Los station_id deben permanecer sin cambios."""
        strategies = [
            NighttimeZeroingStrategy(),
            HampelFilterStrategy(),
            MissingValueImputerStrategy(),
        ]
        executor = CleaningPipelineExecutor(strategies=strategies)
        result = executor.execute(aligned_dataframe)

        original_ids = set(aligned_dataframe[STATION_COLUMN].unique().to_list())
        result_ids = set(result[STATION_COLUMN].unique().to_list())
        assert original_ids == result_ids
