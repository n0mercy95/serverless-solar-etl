"""
application/schema_profiler.py — Componente de Validación Estructural del Schema
================================================================================
Genera reportes de observabilidad para verificar el esquema físico de los datos
a nivel de entrada cruda (intake) antes de transformaciones.
"""

from __future__ import annotations

import logging
import time
from typing import Union

import polars as pl

logger = logging.getLogger(__name__)


class SchemaProfiler:
    """Componente de observabilidad estructural para el DataFrame de Polars.

    Compara las columnas y tipos de datos inferidos con el esquema esperado
    antes de aplicar transformaciones o casts.
    """

    # Mapeo de columnas físicas del CSV a nombre amigable y tipo esperado
    COLUMN_METADATA = {
        "date_time": {
            "display": "timestamp",
            "expected": "Datetime",
            "expected_polars": [pl.Datetime],
        },
        "station_id": {
            "display": "station_id",
            "expected": "Int64",
            "expected_polars": [
                pl.Int64,
                pl.UInt8,
                pl.Int8,
                pl.Int16,
                pl.Int32,
                pl.UInt16,
                pl.UInt32,
                pl.UInt64,
            ],
        },
        "nwp_globalirrad": {
            "display": "NWP_GHI",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "nwp_directirrad": {
            "display": "nwp_directirrad",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "nwp_temperature": {
            "display": "nwp_temperature",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "nwp_humidity": {
            "display": "nwp_humidity",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "nwp_windspeed": {
            "display": "nwp_windspeed",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "nwp_winddirection": {
            "display": "nwp_winddirection",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "nwp_pressure": {
            "display": "nwp_pressure",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "lmd_totalirrad": {
            "display": "LMD_GHI",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "lmd_diffuseirrad": {
            "display": "lmd_diffuseirrad",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "lmd_temperature": {
            "display": "lmd_temperature",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "lmd_pressure": {
            "display": "lmd_pressure",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "lmd_winddirection": {
            "display": "lmd_winddirection",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "lmd_windspeed": {
            "display": "Wind Speed",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
        "power": {
            "display": "Power (MW)",
            "expected": "Float64",
            "expected_polars": [pl.Float64, pl.Float32],
        },
    }

    def __init__(self, df_or_lf: Union[pl.DataFrame, pl.LazyFrame]) -> None:
        """Inicializa el SchemaProfiler con un DataFrame o LazyFrame de Polars.

        Parameters
        ----------
        df_or_lf : Union[pl.DataFrame, pl.LazyFrame]
            Datos a perfilar estructuralmente. Si es LazyFrame, se materializará.
        """
        if isinstance(df_or_lf, pl.LazyFrame):
            self._df = df_or_lf.collect()
        else:
            self._df = df_or_lf

    def generate_report(self, phase_name: str) -> str:
        """Genera el reporte estructural ASCII comparando el esquema inferido con el esperado.

        Parameters
        ----------
        phase_name : str
            Nombre de la fase (ej: "Raw Intake").

        Returns
        -------
        str
            Reporte en formato tabla ASCII de 78 caracteres de ancho.
        """
        t0 = time.perf_counter()

        total_records = self._df.height
        memory_bytes = self._df.estimated_size()
        memory_mb = memory_bytes / (1024 * 1024)

        schema = self._df.schema

        rows = []
        total_expected = len(self.COLUMN_METADATA)

        # 1. Procesar columnas esperadas en orden establecido
        for col_name, meta in self.COLUMN_METADATA.items():
            display_name = meta["display"]
            expected_type_str = meta["expected"]
            expected_polars_types = meta["expected_polars"]

            if col_name not in schema:
                actual_type_str = "Missing"
                status = "[ERROR] -> Missing"
            else:
                actual_type = schema[col_name]
                actual_type_str = self._format_type(actual_type)

                # Verificar coincidencia de tipos nativos y de clases de forma robusta
                type_matches = False
                for t in expected_polars_types:
                    if actual_type == t:
                        type_matches = True
                        break
                    if isinstance(t, type) and isinstance(actual_type, t):
                        type_matches = True
                        break
                    if isinstance(actual_type, type) and issubclass(actual_type, t):
                        type_matches = True
                        break

                if type_matches:
                    status = "[OK]"
                else:
                    status = "[WARN] -> Cast needed"

            rows.append({
                "display_name": display_name,
                "expected": expected_type_str,
                "actual": actual_type_str,
                "status": status,
            })

        # 2. Procesar cualquier columna adicional/extra
        for col_name in schema.names():
            if col_name not in self.COLUMN_METADATA:
                actual_type = schema[col_name]
                actual_type_str = self._format_type(actual_type)
                rows.append({
                    "display_name": col_name,
                    "expected": "N/A",
                    "actual": actual_type_str,
                    "status": "[OK]",
                })

        # Calcular Score de Integridad basado en columnas esperadas presentes
        present_count = sum(1 for col_name in self.COLUMN_METADATA if col_name in schema)
        score = (present_count / total_expected) * 100.0 if total_expected > 0 else 100.0

        execution_time = time.perf_counter() - t0

        return self._build_ascii_report(
            phase_name=phase_name,
            total_records=total_records,
            memory_mb=memory_mb,
            execution_time=execution_time,
            rows=rows,
            score=score,
        )

    @staticmethod
    def _format_type(polars_type) -> str:
        """Devuelve una representación amigable en texto del tipo Polars."""
        if polars_type == pl.String or polars_type == pl.Utf8:
            return "String"
        elif polars_type == pl.Int64:
            return "Int64"
        elif polars_type == pl.UInt8:
            return "UInt8"
        elif polars_type == pl.Float64:
            return "Float64"
        elif polars_type == pl.Datetime:
            return "Datetime"
        else:
            # Eliminar prefijos comunes y formatear como string limpio
            return str(polars_type).replace("DataType.", "").replace("()", "").split(".")[-1]

    @staticmethod
    def _build_ascii_report(
        phase_name: str,
        total_records: int,
        memory_mb: float,
        execution_time: float,
        rows: list[dict[str, str]],
        score: float,
    ) -> str:
        """Construye las líneas de la tabla ASCII exactamente de 78 caracteres de ancho."""
        left_side_1 = f"Phase:              {phase_name}"
        right_side_1 = f"Total Records:              {total_records:,}"
        line_1 = f"{left_side_1:<37} | {right_side_1:<38}"

        left_side_2 = f"Memory Usage:       ~{memory_mb:.1f} MB"
        right_side_2 = f"Execution Time:             {execution_time:.4f}s"
        line_2 = f"{left_side_2:<37} | {right_side_2:<38}"

        score_suffix = " (Ready for Statistical Profiling)" if score == 100.0 else " (Schema alignment required)"
        score_str = f"Schema Integrity Score: {score:.0f}%{score_suffix}"

        lines = [
            "==============================================================================",
            "                    PVOD ETL: DATA INTAKE & SCHEMA REPORT",
            "==============================================================================",
            line_1,
            line_2,
            "==============================================================================",
            "Column Name             | Expected Type | Actual Type | Status",
            "------------------------------------------------------------------------------",
        ]

        for r in rows:
            row_str = f"{r['display_name']:<23} | {r['expected']:<13} | {r['actual']:<11} | {r['status']}"
            lines.append(row_str)

        lines.extend([
            "==============================================================================",
            score_str,
            "==============================================================================",
        ])

        return "\n".join(lines)
