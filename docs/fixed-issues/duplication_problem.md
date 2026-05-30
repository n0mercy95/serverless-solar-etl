# Walkthrough: Resolución Definitiva del Problema de Duplicación en BigQuery

Este documento resume la implementación y verificación del fix definitivo para el problema de duplicación en la tabla `pvod_metrics` de BigQuery.

---

## 🐛 Problema Original

Al ejecutar la ruta `POST /api/v1/etl/run` múltiples veces con el mismo CSV de entrada, la tabla `pvod_metrics` acumulaba filas duplicadas:

- 1ª ejecución: 271,967 filas
- 2ª ejecución: 543,934 filas
- 3ª ejecución: 815,901 filas
- 4ª ejecución: **1,087,868 filas** (4× el tamaño correcto)

**Causa raíz**: Se usaba `WRITE_APPEND` como disposición de escritura, lo que añadía registros sin eliminar los existentes.

## ❌ Primer Intento de Fix (Fallido)

El primer intento combinó tres mecanismos que se **anulaban mutuamente**:

1. Cambió `WRITE_APPEND` → `WRITE_TRUNCATE`
2. Mantuvo un **Job ID determinista** (basado en MD5 del blob)
3. Capturaba la excepción `Conflict` (HTTP 409) para omitir la carga si el Job ID ya existía

**Por qué falló**: BigQuery no permite reutilizar un Job ID ya completado. Como el Job ID era determinista y ya había sido ejecutado exitosamente con `WRITE_APPEND`, BigQuery siempre rechazaba el nuevo job con `Conflict`. El `except Conflict` capturaba el error y retornaba sin ejecutar la carga. **El `WRITE_TRUNCATE` nunca se ejecutó.**

---

## ✅ Fix Definitivo (Actual)

### 1. Job ID Único con UUID (`bigquery_adapter.py`)
Cada ejecución genera un Job ID nuevo con UUID, garantizando que BigQuery siempre ejecute el Load Job.

[bigquery_adapter.py (generación de Job ID)](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/bigquery_adapter.py#L109-L111):
```python
# UUID garantiza que cada ejecución siempre crea un Job nuevo
# — WRITE_TRUNCATE provee la idempotencia, no el Job ID.
job_id = f"pvod_load_{uuid.uuid4().hex}"
```

### 2. WRITE_TRUNCATE como Mecanismo de Idempotencia (`bigquery_adapter.py`)
`WRITE_TRUNCATE` es **inherentemente idempotente**: no importa cuántas veces se ejecute, la tabla siempre queda con exactamente los registros del Parquet actual. No se necesita ningún mecanismo adicional de deduplicación.

[bigquery_adapter.py (configuración de escritura)](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/bigquery_adapter.py#L224-L228):
```python
# WRITE_TRUNCATE: Cada ejecución REEMPLAZA la tabla completa.
# Esto es inherentemente idempotente: N ejecuciones = mismo resultado.
# NO se acumulan duplicados bajo ninguna circunstancia.
job_config.write_disposition = bq_module.WriteDisposition.WRITE_TRUNCATE
```

### 3. Eliminación del `except Conflict` (`bigquery_adapter.py`)
Se eliminó el `except Conflict` y la importación de `Conflict` de `google.api_core.exceptions`. Ya no es necesario: con Job IDs únicos y `WRITE_TRUNCATE`, cada ejecución siempre se completa exitosamente.

### 4. Validación Post-Carga (`bigquery_adapter.py`)
Se agregó una validación que compara las filas reportadas por el Load Job con el conteo real de la tabla. Si no coinciden, emite un `WARNING` de integridad.

[bigquery_adapter.py (validación)](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/bigquery_adapter.py#L169-L210):
```python
def _validate_row_count(self, bq_client, expected_rows):
    table = bq_client.get_table(self._table_ref)
    actual_rows = table.num_rows
    if actual_rows != expected_rows and expected_rows > 0:
        logger.warning("⚠️ ALERTA DE INTEGRIDAD: ...")
```

### 5. Idempotencia en GCS (mantenido, `gcs_parquet_exporter.py`)
La verificación de existencia previa del Parquet en GCS se mantiene sin cambios: si el archivo ya existe (mismo `content_hash`), se omite la serialización y subida, reutilizando la URI existente. Esto ahorra tiempo y red sin afectar la carga en BigQuery.

---

## 🔑 Lección Arquitectónica

| Estrategia | Mecanismo de Idempotencia | Cuándo Usar |
|---|---|---|
| `WRITE_TRUNCATE` + UUID Job ID | La idempotencia la provee el TRUNCATE (N ejecuciones = mismo resultado) | Cuando la tabla completa se recarga desde una fuente única |
| `WRITE_APPEND` + Job ID Determinista + Conflict | La idempotencia la provee el Job ID (evita re-ejecución) | Cuando se añaden incrementos parciales a una tabla existente |

**Nunca combinar ambas estrategias**: `WRITE_TRUNCATE` requiere que el job se ejecute siempre, mientras que el Job ID determinista + `Conflict` previene la ejecución. Son mutuamente excluyentes.

---

## 🧪 Resultado Esperado Post-Fix

Al ejecutar `POST /api/v1/etl/run`:
- **1ª ejecución**: La tabla se reemplaza completamente → **271,967 filas**
- **N-ésima ejecución (mismo CSV)**: La tabla se reemplaza completamente → **271,967 filas**
- **Ejecución con CSV diferente**: La tabla se reemplaza con los nuevos datos → filas del nuevo CSV
