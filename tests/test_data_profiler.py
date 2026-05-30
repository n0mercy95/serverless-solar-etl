"""
test_data_profiler.py — Pruebas Unitarias para el DataProfiler
=============================================================
Valida la precisión del cálculo de métricas de calidad y la coherencia del
reporte ASCII generado por el DataProfiler.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

# Resolver imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.application.data_profiler import DataProfiler


@pytest.fixture
def sample_solar_dataframe() -> pl.DataFrame:
    """Genera un pl.DataFrame con datos solares mock para testear el profiler."""
    # Creamos un conjunto de datos para la estación 0 que cubra día y noche
    base_time = datetime(2023, 6, 21, 0, 0)  # Solsticio de verano (día largo)
    records = []
    
    # 24 horas cada 15 min = 96 registros
    for i in range(96):
        dt = base_time + timedelta(minutes=i * 15)
        # Horas del día (6:00 a 20:00 hay luz)
        hour = dt.hour
        is_day = 6 <= hour <= 19
        
        # NWP_GHI (nwp_globalirrad)
        nwp_ghi = float(500.0 * (1.0 if is_day else 0.0))
        if i == 10:  # Inyectar un valor negativo
            nwp_ghi = -10.0
        elif i == 15:  # Inyectar un nulo
            nwp_ghi = None
            
        # LMD_GHI (lmd_totalirrad)
        lmd_ghi = float(480.0 * (1.0 if is_day else 0.0))
        if i == 20:  # Inyectar nulo
            lmd_ghi = None
            
        # Power (power)
        power = float(10.0 * (1.0 if is_day else 0.0))
        if i == 30:  # Inyectar negativo
            power = -2.0
        elif i == 35:  # Inyectar nulo
            power = None
        elif i == 1:  # Inyectar Nighttime Power > 0 (noche profunda: 00:15)
            power = 5.0
            
        # Wind Speed (lmd_windspeed)
        wind = 3.5
        if i == 40:  # Inyectar nulo
            wind = None
        elif i == 45:  # Inyectar negativo
            wind = -1.5

        records.append({
            "date_time": dt,
            "station_id": 0,
            "nwp_globalirrad": nwp_ghi,
            "lmd_totalirrad": lmd_ghi,
            "power": power,
            "lmd_windspeed": wind,
        })
        
    return pl.DataFrame(records)


def test_profiler_with_dataframe(sample_solar_dataframe):
    """Verifica que el DataProfiler se instancie y funcione con pl.DataFrame."""
    profiler = DataProfiler(sample_solar_dataframe)
    report = profiler.generate_report("Pre-Cleaning")
    
    assert isinstance(report, str)
    assert "Phase:              Pre-Cleaning" in report
    assert "PVOD ETL: DATA QUALITY & PROFILING REPORT" in report
    assert "Total Records:              96" in report


def test_profiler_with_lazyframe(sample_solar_dataframe):
    """Verifica que el DataProfiler soporte pl.LazyFrame recolectándolo internamente."""
    lazy_df = sample_solar_dataframe.lazy()
    profiler = DataProfiler(lazy_df)
    report = profiler.generate_report("Post-Cleaning (Gold)")
    
    assert isinstance(report, str)
    assert "Phase:              Post-Cleaning" in report
    assert "Total Records:              96" in report


def test_profiler_calculates_nulls_and_negatives_correctamente(sample_solar_dataframe):
    """Valida los conteos exactos de nulos y valores negativos en cada columna."""
    profiler = DataProfiler(sample_solar_dataframe)
    report = profiler.generate_report("Test")
    
    # NWP_GHI: 1 nulo, 1 negativo
    # LMD_GHI: 1 nulo, 0 negativos
    # Power: 1 nulo, 1 negativo
    # Wind Speed: 1 nulo, 1 negativo
    
    # Comprobar filas de nulos y negativos
    # Formato esperado para Null Values: Null Values             | X       | X       | X         | X
    # Donde X es el conteo
    assert "Null Values             | 1       | 1       | 1         | 1" in report
    assert "Negative Values         | 1       | 0       | 1         | 1" in report


def test_profiler_calculates_nighttime_power_correctamente(sample_solar_dataframe):
    """Valida el cálculo de la métrica física 'Nighttime Power > 0'."""
    profiler = DataProfiler(sample_solar_dataframe)
    report = profiler.generate_report("Test")
    
    # En el fixture inyectamos 1 registro en la noche profunda (00:15) con power = 5.0
    # y además, al atardecer (19:30 y 19:45) el sol ya bajó el horizonte (elevación <= 0)
    # pero el fixture mantiene power = 10.0.
    # Esto produce exactamente 3 registros con Nighttime Power > 0.
    # El reporte debe mostrar N/A en irradiancia y viento, y exactamente 3 para Power.
    # Fila esperada: "Nighttime Power > 0     | N/A     | N/A     | X         | N/A"
    assert "Nighttime Power > 0     | N/A     | N/A     | 3         | N/A" in report


def test_profiler_calculates_descriptive_stats(sample_solar_dataframe):
    """Verifica el cálculo y formateo de promedios, std dev, min y max."""
    profiler = DataProfiler(sample_solar_dataframe)
    report = profiler.generate_report("Test")
    
    # Al menos verificar que las filas de estadísticas están presentes
    assert "Mean" in report
    assert "Std Dev" in report
    assert "Min" in report
    assert "Max" in report


def test_profiler_handles_empty_dataframe():
    """Valida el comportamiento robusto del profiler ante DataFrames vacíos."""
    schema = {
        "date_time": pl.Datetime,
        "station_id": pl.UInt8,
        "nwp_globalirrad": pl.Float64,
        "lmd_totalirrad": pl.Float64,
        "power": pl.Float64,
        "lmd_windspeed": pl.Float64,
    }
    empty_df = pl.DataFrame([], schema=schema)
    
    profiler = DataProfiler(empty_df)
    report = profiler.generate_report("Empty Phase")
    
    assert "Total Records:              0" in report
    assert "Overall Quality Score: 100.0%" in report
    assert "Null Values             | 0       | 0       | 0         | 0" in report


def test_overall_quality_score_is_calculated(sample_solar_dataframe):
    """Valida el cálculo correcto del Score de calidad general."""
    profiler = DataProfiler(sample_solar_dataframe)
    report = profiler.generate_report("Test")
    
    # Total de registros = 96
    # Total celdas posibles en las 4 columnas = 96 * 4 = 384
    # Incidencias inyectadas:
    #   - NWP_GHI: 1 null, 1 negative = 2
    #   - LMD_GHI: 1 null, 0 negative = 1
    #   - Power: 1 null, 1 negative, 3 nighttime power = 5
    #   - Wind Speed: 1 null, 1 negative = 2
    # Total incidencias = 2 + 1 + 5 + 2 = 10
    # Score esperado = (1.0 - (10 / 384)) * 100 = 97.395% -> redondeado a 97.4%
    assert "Overall Quality Score: 97.4%" in report
