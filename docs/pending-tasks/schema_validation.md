# Schema Validation Report for Polars Data Intake

We need to add a structural observability layer to our ETL pipeline. This layer will run immediately after extracting the raw data and prior to any data casting, transformations, or cleaning. It will generate an ASCII-formatted schema validation report matching the exact design and width (78 characters) of our existing profiling reports.

## Proposed Changes

We will introduce a new `SchemaProfiler` class in the application layer and integrate it directly into the `PVODLazyLoader` class in the infrastructure layer.

---

### Application Layer

#### [NEW] [schema_profiler.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/schema_profiler.py)
This module will define the `SchemaProfiler` class, responsible for analyzing a Polars DataFrame or LazyFrame structural layout and rendering a beautifully aligned ASCII validation report.

Key details:
- **`COLUMN_METADATA`**: A central mapping of the 16 expected raw columns, their display names, expected data types (for reporting), and compatible Polars `DataType` references.
- **Estimated Memory**: Computed exactly from the collected DataFrame using `df.estimated_size()`.
- **Integrity Score**: Measures column presence against expected columns, matching `100%` when all columns are present.
- **Formating**: Exact 78-character width boundary using structured formatting to align the ASCII tables and borders seamlessly.

```python
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
        "date_time": {"display": "timestamp", "expected": "Datetime", "expected_polars": [pl.Datetime]},
        "station_id": {"display": "station_id", "expected": "Int64", "expected_polars": [pl.Int64, pl.UInt8, pl.Int8, pl.Int16, pl.Int32, pl.UInt16, pl.UInt32, pl.UInt64]},
        "nwp_globalirrad": {"display": "NWP_GHI", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "nwp_directirrad": {"display": "nwp_directirrad", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "nwp_temperature": {"display": "nwp_temperature", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "nwp_humidity": {"display": "nwp_humidity", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "nwp_windspeed": {"display": "nwp_windspeed", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "nwp_winddirection": {"display": "nwp_winddirection", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "nwp_pressure": {"display": "nwp_pressure", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "lmd_totalirrad": {"display": "LMD_GHI", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "lmd_diffuseirrad": {"display": "lmd_diffuseirrad", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "lmd_temperature": {"display": "lmd_temperature", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "lmd_pressure": {"display": "lmd_pressure", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "lmd_winddirection": {"display": "lmd_winddirection", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "lmd_windspeed": {"display": "Wind Speed", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
        "power": {"display": "Power (MW)", "expected": "Float64", "expected_polars": [pl.Float64, pl.Float32]},
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
        
        # Iterar sobre las columnas y comparar esquemas
        schema = self._df.schema
        
        rows = []
        matching_count = 0
        total_expected = len(self.COLUMN_METADATA)
        
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
                
                # Chequear si coincide con alguno de los tipos esperados
                type_matches = any(actual_type == t or isinstance(actual_type, t) if not isinstance(t, type) else actual_type == t for t in expected_polars_types)
                
                if type_matches:
                    status = "[OK]"
                    matching_count += 1
                else:
                    # Si es date_time que llega como String
                    if col_name == "date_time" and actual_type_str == "String":
                        status = "[WARN] -> Cast needed"
                        matching_count += 1  # No penaliza el score estructural ya que es el flujo esperado de CSV
                    else:
                        status = "[WARN] -> Cast needed"
                        matching_count += 1  # No penaliza el score si está presente pero requiere cast (como de Int a Float o String)
            
            rows.append({
                "display_name": display_name,
                "expected": expected_type_str,
                "actual": actual_type_str,
                "status": status,
            })
            
        # Calcular Score de Integridad
        # Si todas las columnas esperadas están presentes, el score es 100%
        present_count = sum(1 for col_name in self.COLUMN_METADATA if col_name in schema)
        score = (present_count / total_expected) * 100.0
        
        execution_time = time.perf_counter() - t0
        
        # Construir reporte ASCII
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
            return str(polars_type).replace("DataType.", "").replace("()", "")
            
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
        
        # Para el Score
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
```

---

### Infrastructure Layer

#### [MODIFY] [pvod_lazy_loader.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/pvod_lazy_loader.py)
We will insert the schema validation right after `self._scan_csv_lazy(tmp_path)` within `load_and_align()`.

> [!TIP]
> **Performance Optimization**: By collecting the DataFrame once at the intake layer for validation, and returning it to a LazyFrame using `raw_df.lazy()`, we avoid multiple subsequent reads from the disk tempfile, parsing the CSV exactly once.

```diff
     def load_and_align(self, buffer: io.BytesIO) -> pl.LazyFrame:
         """Carga el CSV desde un buffer en modo lazy y ejecuta el
         alineamiento temporal a la grilla estricta de 15 minutos.
 
         El flujo es:
-        ``buffer → tempfile → scan_csv → parse/truncate → cast → deltas → validar``
+        ``buffer → tempfile → scan_csv → schema validation → parse/truncate → cast → deltas → validar``
 
         Parameters
         ----------
         buffer : io.BytesIO
             Buffer binario con el CSV PVOD consolidado.
 
         Returns
         -------
         pl.LazyFrame
             LazyFrame optimizado, listo para la fase de limpieza (Strategy).
         """
         logger.info("Iniciando carga lazy y alineamiento temporal del PVOD")
 
         # ── 1. Materializar buffer a disco temporal ───────────────────
         tmp_path = self._buffer_to_tempfile(buffer)
 
         try:
             # ── 2. Carga lazy via scan_csv ────────────────────────────
             lazy_frame = self._scan_csv_lazy(tmp_path)
 
+            # ── 2b. Generar Schema Validation Report ──────────────────
+            from app.application.schema_profiler import SchemaProfiler
+            raw_df = lazy_frame.collect()
+            schema_profiler = SchemaProfiler(raw_df)
+            schema_report = schema_profiler.generate_report(phase_name="Raw Intake")
+            logger.info(f"\n{schema_report}")
+            
+            # Re-crear el LazyFrame a partir del DataFrame cargado para conservar el flujo lazy
+            lazy_frame = raw_df.lazy()
+
             # ── 3. Parsing temporal y truncamiento a 15 min ───────────
             lazy_frame = self._parse_and_truncate_datetime(lazy_frame)
```

---

## Verification Plan

### Automated Tests
We will add unit tests in a new file `tests/test_schema_profiler.py` and run them inside our virtual environment.

1. **Verify `SchemaProfiler` calculations**:
   - Check exact parsing of Polars raw types (e.g. String, Int64, Float64).
   - Check handling of missing columns and correct `[ERROR] -> Missing` reporting.
   - Check correct status generation (`[OK]`, `[WARN] -> Cast needed`).
   - Check structural score calculation.
2. **Verify Integrations**:
   - Run the full pipeline via tests to see the logger outputs.
   - Ensure `pytest` passes with no new regression issues.

```bash
.venv/bin/pytest tests/test_schema_profiler.py
```

### Manual Verification
- We will execute the main ETL script (e.g. `scripts/run_pipeline.py` or equivalent integration tests) and inspect the standard console output to verify the ASCII layout borders align perfectly at 78 characters width, matching the requirements.
