"""
conftest.py — Fixtures Compartidos para la Suite de Tests del ETL Solar
========================================================================
Provee fixtures reutilizables: buffer CSV sintético, DataFrames de prueba
con datos PVOD realistas, y configuración de Settings mockeada.

Estos fixtures generan datos sintéticos que replican la estructura exacta
del dataset PVOD (10 estaciones, intervalo de 15 min, columnas NWP/LMD)
sin requerir descarga HTTP ni acceso a GCS/BigQuery.
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

# ── Agregar src/ al PYTHONPATH para resolver imports de app.* ─────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.domain.constants import (
    EXPECTED_RECORDS,
    IRRADIANCE_COLUMNS,
    LMD_COLUMNS,
    NWP_COLUMNS,
    NWP_LMD_DELTA_PAIRS,
    NUM_STATIONS,
    PVOD_FINAL_SCHEMA,
    STATION_COLUMN,
    TARGET_COLUMN,
    TEMPORAL_COLUMN,
)


# ── Parámetros de generación ──────────────────────────────────────────
_STATIONS = NUM_STATIONS       # 10 estaciones
_ROWS_PER_STATION = 96         # 1 día completo (96 intervalos de 15 min)
_TOTAL_ROWS = _STATIONS * _ROWS_PER_STATION
_START_DT = datetime(2018, 7, 1, 0, 0)


def _generate_csv_content(
    *,
    num_stations: int = _STATIONS,
    rows_per_station: int = _ROWS_PER_STATION,
    include_nulls: bool = False,
    include_outlier: bool = False,
    include_negative_irradiance: bool = False,
) -> str:
    """Genera contenido CSV sintético con la estructura exacta del PVOD.

    Parameters
    ----------
    num_stations : int
        Cantidad de estaciones a generar.
    rows_per_station : int
        Registros por estación (cada uno = 15 min).
    include_nulls : bool
        Si True, inyecta valores nulos en algunas celdas.
    include_outlier : bool
        Si True, inyecta un outlier extremo en windspeed.
    include_negative_irradiance : bool
        Si True, inyecta un valor negativo de irradiancia (violación física).

    Returns
    -------
    str
        Contenido CSV listo para escribir o parsear.
    """
    # Header
    columns = [
        TEMPORAL_COLUMN,
        STATION_COLUMN,
        *NWP_COLUMNS,
        *LMD_COLUMNS,
        TARGET_COLUMN,
    ]
    lines = [",".join(columns)]

    for station_id in range(num_stations):
        for i in range(rows_per_station):
            dt = _START_DT + timedelta(minutes=15 * i)
            dt_str = dt.strftime("%Y-%m-%d %H:%M")

            # Valores base (varían ligeramente por estación)
            hour = dt.hour + dt.minute / 60.0
            # Simular irradiancia diurna (forma de campana)
            is_daytime = 6 <= dt.hour <= 18
            irrad_base = max(0.0, 800.0 * max(0, 1 - ((hour - 12) / 6) ** 2)) if is_daytime else 0.0

            nwp_globalirrad = round(irrad_base + station_id * 5, 2)
            nwp_directirrad = round(irrad_base * 0.7 + station_id * 3, 2)
            nwp_temperature = round(20.0 + 5 * max(0, 1 - ((hour - 14) / 8) ** 2) + station_id * 0.5, 2)
            nwp_humidity = round(60.0 - station_id * 2, 2)
            nwp_windspeed = round(3.0 + station_id * 0.3, 2)
            nwp_winddirection = round(180.0 + station_id * 10, 2)
            nwp_pressure = round(1013.0 - station_id * 0.5, 2)

            lmd_totalirrad = round(irrad_base * 0.95 + station_id * 4, 2)
            lmd_diffuseirrad = round(irrad_base * 0.3 + station_id * 2, 2)
            lmd_temperature = round(nwp_temperature + 0.5, 2)
            lmd_pressure = round(nwp_pressure + 0.3, 2)
            lmd_winddirection = round(nwp_winddirection + 5, 2)
            lmd_windspeed = round(nwp_windspeed + 0.2, 2)

            power = round(irrad_base * 0.002 + station_id * 0.01, 4) if is_daytime else 0.0

            values = [
                dt_str,
                str(station_id),
                str(nwp_globalirrad),
                str(nwp_directirrad),
                str(nwp_temperature),
                str(nwp_humidity),
                str(nwp_windspeed),
                str(nwp_winddirection),
                str(nwp_pressure),
                str(lmd_totalirrad),
                str(lmd_diffuseirrad),
                str(lmd_temperature),
                str(lmd_pressure),
                str(lmd_winddirection),
                str(lmd_windspeed),
                str(power),
            ]

            # Inyecciones de anomalías para tests específicos
            if include_nulls and station_id == 0 and i in (10, 11, 12):
                # Inyectar nulls en nwp_temperature (index 4 en values)
                values[4] = ""

            if include_outlier and station_id == 1 and i == 48:
                # Inyectar outlier extremo en nwp_windspeed (index 6)
                values[6] = "999.9"

            if include_negative_irradiance and station_id == 2 and i == 50:
                # Inyectar irradiancia negativa (index 2)
                values[2] = "-50.0"

            lines.append(",".join(values))

    return "\n".join(lines) + "\n"


@pytest.fixture
def csv_buffer() -> io.BytesIO:
    """Buffer CSV sintético limpio (sin anomalías).

    Simula 10 estaciones × 96 registros = 960 filas.
    """
    content = _generate_csv_content()
    buffer = io.BytesIO(content.encode("utf-8"))
    buffer.seek(0)
    return buffer


@pytest.fixture
def csv_buffer_with_nulls() -> io.BytesIO:
    """Buffer CSV con valores nulos inyectados."""
    content = _generate_csv_content(include_nulls=True)
    buffer = io.BytesIO(content.encode("utf-8"))
    buffer.seek(0)
    return buffer


@pytest.fixture
def csv_buffer_with_outlier() -> io.BytesIO:
    """Buffer CSV con un outlier extremo en windspeed."""
    content = _generate_csv_content(include_outlier=True)
    buffer = io.BytesIO(content.encode("utf-8"))
    buffer.seek(0)
    return buffer


@pytest.fixture
def csv_buffer_negative_irradiance() -> io.BytesIO:
    """Buffer CSV con valor de irradiancia negativo (violación PRD §4)."""
    content = _generate_csv_content(include_negative_irradiance=True)
    buffer = io.BytesIO(content.encode("utf-8"))
    buffer.seek(0)
    return buffer


@pytest.fixture
def aligned_dataframe(csv_buffer: io.BytesIO) -> pl.DataFrame:
    """DataFrame materializado post Tarea 2.1 (alineado y tipado).

    Equivale al output de PVODLazyLoader.load_and_align().collect().
    """
    from app.infrastructure.pvod_lazy_loader import PVODLazyLoader

    loader = PVODLazyLoader()
    lazy_frame = loader.load_and_align(csv_buffer)
    return lazy_frame.collect()


@pytest.fixture
def aligned_dataframe_with_nulls(csv_buffer_with_nulls: io.BytesIO) -> pl.DataFrame:
    """DataFrame materializado con nulls inyectados (para test de imputación)."""
    from app.infrastructure.pvod_lazy_loader import PVODLazyLoader

    loader = PVODLazyLoader()
    lazy_frame = loader.load_and_align(csv_buffer_with_nulls)
    return lazy_frame.collect()


@pytest.fixture
def aligned_dataframe_with_outlier(csv_buffer_with_outlier: io.BytesIO) -> pl.DataFrame:
    """DataFrame materializado con outlier extremo (para test de Hampel)."""
    from app.infrastructure.pvod_lazy_loader import PVODLazyLoader

    loader = PVODLazyLoader()
    lazy_frame = loader.load_and_align(csv_buffer_with_outlier)
    return lazy_frame.collect()


@pytest.fixture
def cleaned_dataframe(aligned_dataframe: pl.DataFrame) -> pl.DataFrame:
    """DataFrame post pipeline de limpieza completo (Tarea 2.2).

    Aplica las 3 estrategias en orden PRD.
    """
    from app.application.cleaning_pipeline import CleaningPipelineExecutor
    from app.infrastructure.strategies.hampel_filter_strategy import HampelFilterStrategy
    from app.infrastructure.strategies.missing_value_imputer_strategy import MissingValueImputerStrategy
    from app.infrastructure.strategies.nighttime_zeroing_strategy import NighttimeZeroingStrategy

    strategies = [
        NighttimeZeroingStrategy(),
        HampelFilterStrategy(),
        MissingValueImputerStrategy(),
    ]
    executor = CleaningPipelineExecutor(strategies=strategies)
    return executor.execute(aligned_dataframe)


@pytest.fixture
def mock_settings() -> MagicMock:
    """Settings mockeados para evitar lectura del .env real."""
    settings = MagicMock()
    settings.github_raw_url = "https://raw.githubusercontent.com/test/repo/data/pvod.csv"
    settings.scidb_fallback_url = "https://scidb.cn/api/v1/dataset/pvod.csv"
    settings.gcs_bucket_name = "test-bucket"
    settings.gcp_project_id = "test-project"
    settings.bq_dataset_id = "test_dataset"
    settings.bq_table_id = "test_table"
    return settings
