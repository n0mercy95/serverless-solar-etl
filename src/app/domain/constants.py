"""
domain/constants.py — Constantes Físicas y Esquema del Dataset PVOD
====================================================================
Centraliza las constantes del dominio solar utilizadas en validaciones
físicas, definición de esquema y alineamiento temporal.  Estas constantes
son inmutables y derivan directamente del PRD §4 y de la literatura
fotovoltaica estándar (Kopp & Lean 2011, TSI = 1361 W/m²).

Mantener estas constantes en la capa de Dominio garantiza que ninguna
capa externa (Infrastructure, Application) redefina valores críticos.
"""

from __future__ import annotations

# ── Constantes Físicas ────────────────────────────────────────────────
SOLAR_CONSTANT_W_M2: float = 1361.0
"""Constante solar extraterrestre (Total Solar Irradiance).
Referencia: Kopp & Lean (2011).  La irradiancia global medida
nunca debe exceder este valor en la superficie terrestre."""

# ── Parámetros Temporales del Dataset ─────────────────────────────────
SAMPLING_INTERVAL_MINUTES: int = 15
"""Intervalo de muestreo estricto del PVOD (cada 15 minutos exactos)."""

SAMPLING_INTERVAL_POLARS: str = "15m"
"""Representación del intervalo como cadena Polars para ``truncate``."""

# ── Dimensiones del Dataset ───────────────────────────────────────────
NUM_STATIONS: int = 10
"""Cantidad de estaciones fotovoltaicas en el PVOD (station 0–9)."""

EXPECTED_RECORDS: int = 271_968
"""Registros totales esperados en el CSV consolidado (PRD §4)."""

# ── Esquema de Columnas PVOD ──────────────────────────────────────────
TEMPORAL_COLUMN: str = "date_time"
"""Columna de timestamp (clave de alineamiento temporal)."""

STATION_COLUMN: str = "station_id"
"""Columna de identificador de estación (clave de clustering BQ)."""

TARGET_COLUMN: str = "power"
"""Variable objetivo: salida de potencia fotovoltaica (kW)."""

NWP_COLUMNS: tuple[str, ...] = (
    "nwp_globalirrad",
    "nwp_directirrad",
    "nwp_temperature",
    "nwp_humidity",
    "nwp_windspeed",
    "nwp_winddirection",
    "nwp_pressure",
)
"""Columnas de Predicción Numérica del Tiempo (Numerical Weather Prediction).
Representan predicciones macroescalares del modelo meteorológico."""

LMD_COLUMNS: tuple[str, ...] = (
    "lmd_totalirrad",
    "lmd_diffuseirrad",
    "lmd_temperature",
    "lmd_pressure",
    "lmd_winddirection",
    "lmd_windspeed",
)
"""Columnas de Mediciones Locales (Local Measurements Data).
Representan mediciones microclimáticas reales de la estación."""

# ── Mapeo de Deltas NWP ↔ LMD ────────────────────────────────────────
# Pares (columna_nwp, columna_lmd, nombre_delta) para variables que
# existen en ambas matrices y permiten calcular la desviación del modelo.
NWP_LMD_DELTA_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("nwp_globalirrad", "lmd_totalirrad", "delta_globalirrad"),
    ("nwp_temperature", "lmd_temperature", "delta_temperature"),
    ("nwp_pressure", "lmd_pressure", "delta_pressure"),
    ("nwp_windspeed", "lmd_windspeed", "delta_windspeed"),
)
"""Pares de columnas NWP/LMD para el cálculo de desviación (error del modelo).
Cada tupla es (columna_nwp, columna_lmd, nombre_columna_delta)."""

# ── Columnas de Irradiancia (sujetas a validación física) ─────────────
IRRADIANCE_COLUMNS: tuple[str, ...] = (
    "nwp_globalirrad",
    "nwp_directirrad",
    "lmd_totalirrad",
    "lmd_diffuseirrad",
)
"""Columnas de irradiancia que deben cumplir 0 ≤ valor ≤ SOLAR_CONSTANT_W_M2."""

# ══════════════════════════════════════════════════════════════════════
# PARÁMETROS DE LIMPIEZA — Patrón Strategy (PRD §3, Tarea 2.2)
# ══════════════════════════════════════════════════════════════════════

# ── Hampel Filter (Anomalías de Viento) ───────────────────────────────
HAMPEL_WINDOW_SIZE: int = 5
"""Tamaño de la ventana móvil para el filtro Hampel (en registros).
Con intervalo de 15 min, 5 registros = 1h15min de contexto."""

HAMPEL_THRESHOLD: float = 3.0
"""Umbral en MADs (Median Absolute Deviations) para clasificar outliers.
Valores con |x - mediana| > threshold × 1.4826 × MAD son anomalías."""

HAMPEL_CONSISTENCY_FACTOR: float = 1.4826
"""Factor de consistencia para convertir MAD a escala de desviación estándar.
Derivado de 1/Φ⁻¹(3/4) para distribución normal (Rousseeuw & Croux 1993)."""

WIND_SPEED_COLUMNS: tuple[str, ...] = ("nwp_windspeed", "lmd_windspeed")
"""Columnas de velocidad de viento sujetas al filtro Hampel."""

# ── Nighttime Zeroing (Elevación Solar) ───────────────────────────────
DEFAULT_STATION_LATITUDE: float = 38.0
"""Latitud representativa de las estaciones PVOD (~centro Hebei, China).
Rango real del dataset: 36.64°N – 39.52°N (Yao et al., Solar Energy 2021)."""

DEFAULT_STATION_LONGITUDE: float = 115.5
"""Longitud representativa de las estaciones PVOD (~centro Hebei, China).
Rango real del dataset: 113.64°E – 117.46°E."""

SOLAR_DECLINATION_AMPLITUDE: float = 23.45
"""Amplitud de la declinación solar en grados (oblicuidad de la eclíptica)."""

NIGHTTIME_ZEROING_COLUMNS: tuple[str, ...] = (
    "nwp_globalirrad",
    "nwp_directirrad",
    "lmd_totalirrad",
    "lmd_diffuseirrad",
    "power",
)
"""Columnas forzadas a cero exacto cuando la elevación solar ≤ 0°.
Incluye irradiancias NWP/LMD y salida de potencia."""

# ── Missing Value Imputation ──────────────────────────────────────────
IMPUTATION_COLUMNS: tuple[str, ...] = (
    "nwp_globalirrad",
    "nwp_directirrad",
    "nwp_temperature",
    "nwp_humidity",
    "nwp_windspeed",
    "nwp_winddirection",
    "nwp_pressure",
    "lmd_totalirrad",
    "lmd_diffuseirrad",
    "lmd_temperature",
    "lmd_pressure",
    "lmd_winddirection",
    "lmd_windspeed",
    "power",
)
"""Columnas numéricas sujetas a imputación de valores faltantes.
La interpolación se ejecuta por estación para evitar cruzar series."""

# ══════════════════════════════════════════════════════════════════════
# EXPORTACIÓN PARQUET — Capa Oro / Gold Layer (PRD §4, Tarea 2.3)
# ══════════════════════════════════════════════════════════════════════

PARQUET_COMPRESSION: str = "zstd"
"""Algoritmo de compresión para Apache Parquet.
Zstandard ofrece mejor ratio compresión/velocidad que Snappy para datos
columnar densos.  PyArrow aplica RLE + dictionary encoding automáticamente
por columna cuando usa este backend."""

GCS_GOLD_PREFIX: str = "gold/"
"""Prefijo (directorio virtual) en el bucket GCS para la Capa Oro.
Los archivos Parquet se almacenan como: gold/pvod_{timestamp}.parquet"""

PARQUET_BLOB_PREFIX: str = "pvod_"
"""Prefijo del nombre del blob Parquet en GCS."""

# ── Esquema Final Estricto (para enforcement antes del export) ────────
# Mapeo columna → tipo Polars que DEBE tener el DataFrame antes de
# serializarse a Parquet.  Garantiza compatibilidad con BigQuery.
PVOD_FINAL_SCHEMA: dict[str, str] = {
    # Temporal
    "date_time": "Datetime",
    # Metadata
    "station_id": "UInt8",
    # NWP
    "nwp_globalirrad": "Float64",
    "nwp_directirrad": "Float64",
    "nwp_temperature": "Float64",
    "nwp_humidity": "Float64",
    "nwp_windspeed": "Float64",
    "nwp_winddirection": "Float64",
    "nwp_pressure": "Float64",
    # LMD
    "lmd_totalirrad": "Float64",
    "lmd_diffuseirrad": "Float64",
    "lmd_temperature": "Float64",
    "lmd_pressure": "Float64",
    "lmd_winddirection": "Float64",
    "lmd_windspeed": "Float64",
    # Target
    "power": "Float64",
    # Deltas NWP - LMD
    "delta_globalirrad": "Float64",
    "delta_temperature": "Float64",
    "delta_pressure": "Float64",
    "delta_windspeed": "Float64",
}
"""Esquema final estricto del DataFrame PVOD para exportación a Parquet.
Cada columna debe tener exactamente este tipo antes de la serialización."""

