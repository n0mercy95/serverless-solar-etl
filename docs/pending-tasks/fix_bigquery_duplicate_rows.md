# Fix Pendiente: Cuadruplicación de Filas en `pvod_metrics` (BigQuery)

Este documento describe el problema de duplicación masiva en la tabla `pvod_metrics` de BigQuery, por qué un caché Redis **no** es la solución correcta, y el plan de implementación para limpiar y prevenir la duplicación.

---

## El Problema

La tabla `pvod_metrics` en BigQuery contiene **1,087,868 filas** cuando debería tener **271,967** (el valor esperado según `EXPECTED_RECORDS` en [`constants.py`](../../src/app/domain/constants.py)). Cada fila existe exactamente **4 veces** — una cuadruplicación perfecta del dataset completo.

| Métrica | Valor actual | Valor esperado |
|---|---|---|
| Filas totales | 1,087,868 | 271,967 |
| Combinaciones únicas `(date_time, station_id)` | 271,967 | 271,967 |
| Factor de duplicación | **4x** | 1x |
| Almacenamiento lógico | 124.5 MB | ~31 MB |
| Particiones | 349 | 349 |

---

## Causa Raíz: Idempotencia Rota

El pipeline tiene un mecanismo de "idempotencia" que **nunca funcionó**. La cadena causal es:

### 1. Cada ejecución genera un Parquet con nombre único

En [`gcs_parquet_exporter.py`](../../src/app/infrastructure/gcs_parquet_exporter.py) (líneas 231-232):

```python
ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
return f"{GCS_GOLD_PREFIX}{PARQUET_BLOB_PREFIX}{ts}.parquet"
# Resultado: gold/pvod_20260527_155711.parquet
```

Cada vez que se ejecuta el pipeline, el Parquet se sube a GCS con un nombre diferente (basado en el timestamp actual). Esto es correcto para mantener un historial, pero genera una URI distinta cada vez.

### 2. El Job ID depende de la URI (que siempre cambia)

En [`bigquery_adapter.py`](../../src/app/infrastructure/bigquery_adapter.py) (líneas 209-214):

```python
raw_seed = (
    f"{gcs_uri}{self._project_id}{self._dataset_id}"
    f"{self._table_id}{blob_md5}"
)
hashed_seed = hashlib.md5(raw_seed.encode("utf-8")).hexdigest()
return f"pvod_load_{hashed_seed}"
```

El `job_id` se calcula usando `gcs_uri` como parte del hash. Como la URI cambia en cada ejecución → el hash cambia → el Job ID cambia → BigQuery lo trata como un job **nuevo** y lo ejecuta.

### 3. El modo de escritura es APPEND

En [`bigquery_adapter.py`](../../src/app/infrastructure/bigquery_adapter.py) (línea 229):

```python
job_config.write_disposition = bq_module.WriteDisposition.WRITE_APPEND
```

Cada Load Job **añade** las ~272K filas al final de la tabla. No verifica si ya existen. Al ejecutar el pipeline 4 veces se generan 4 copias idénticas.

### Historial de Load Jobs que lo comprueban

| # | Job ID | Fecha (UTC) | Resultado |
|---|--------|-------------|-----------|
| 1 | `pvod_load_a0a4f6...` | 2026-05-20 20:02:59 | DONE *(tabla anterior, eliminada)* |
| 2 | `pvod_load_f3ee97...` | 2026-05-20 20:16:47 | DONE *(creó la tabla actual)* |
| 3 | `pvod_load_aaffea...` | 2026-05-26 18:52:59 | DONE *(+272K = 544K)* |
| 4 | `pvod_load_6fa694...` | 2026-05-26 19:07:54 | DONE *(+272K = 816K)* |
| 5 | `pvod_load_661ed5...` | 2026-05-27 15:57:11 | DONE *(+272K = 1,088K)* |

Todos los jobs procesaron exactamente **43,514,720 bytes** — el mismo dataset con diferente nombre de archivo.

---

## ¿Por Qué Redis NO Es la Solución?

La idea de interponer un caché Redis entre la API de lectura (`/api/v1/metrics/aggregate`) y BigQuery puede parecer lógica: "si BigQuery tiene datos sucios, que la API lea de un caché limpio". Pero esta aproximación es **incorrecta** por múltiples razones:

### 1. Trata el síntoma, no la causa

Redis no evita que la tabla siga acumulando duplicados. Cada nueva ejecución del pipeline añadiría otra copia (~272K filas más). La tabla crecería indefinidamente: 5x, 6x, 7x... generando costos de almacenamiento crecientes en BigQuery, aunque nadie la consultara directamente.

### 2. El dataset es estático y pequeño — BigQuery ya tiene caché nativo

El PVOD es un dataset histórico fijo (~2018-2019) que no cambia entre ejecuciones del ETL. BigQuery automáticamente cachea los resultados de queries idénticas durante 24 horas sin costo adicional. El código actual ya aprovecha esto:

```python
# query_service.py, línea 77
use_query_cache=not request.dry_run,  # Ya usa caché nativo de BQ
```

Agregar Redis sería redundante — un segundo caché encima del caché nativo de BQ.

### 3. Complejidad operativa injustificada

| Componente | Costo / Esfuerzo |
|---|---|
| Cloud Memorystore (Redis) | ~$37/mes mínimo (instancia Basic, 1GB) |
| Lógica de invalidación de caché | TTLs, keys por rango de fechas, serialización/deserialización |
| Infraestructura adicional | VPC connector para conectar Cloud Run → Memorystore |
| Monitoreo | Alertas de memoria, conexiones, latencia |

Todo esto para un endpoint (`/aggregate`) que procesa ~272K filas de ~6.5 MB (sin duplicados) — una query que BigQuery resuelve en <1 segundo.

### 4. El resultado de `/aggregate` ya es correcto (por casualidad)

La query actual usa `AVG(power)` agrupado por `station_id`. Como las filas duplicadas tienen exactamente los mismos valores, el promedio es idéntico con 1 o 4 copias. Pero esto es una coincidencia del operador `AVG` — si en el futuro se agregan queries con `COUNT()`, `SUM()`, `PERCENTILE`, o paginación, los resultados serían **silenciosamente incorrectos** sin que nadie lo note.

### Conclusión: Lo correcto es limpiar la fuente

> **Regla general:** Si los datos están corruptos, arregla los datos. No pongas una capa intermedia que los esconda.

---

## Qué Hubiera Sido Lo Correcto Desde el Principio

El diseño original intentó resolver la idempotencia con un Job ID determinista basado en MD5. La intención era buena, pero la implementación tiene un defecto lógico fundamental: **incluir un componente variable (la URI con timestamp) dentro del hash que debería ser estable**.

### Opción A: `WRITE_TRUNCATE` (la más simple y recomendada para este caso)

```python
job_config.write_disposition = bq_module.WriteDisposition.WRITE_TRUNCATE
```

Con `WRITE_TRUNCATE`, cada Load Job **reemplaza toda la tabla** con los datos nuevos. Es imposible duplicar porque no se acumula nada — cada ejecución deja la tabla con exactamente las ~272K filas del Parquet.

**Cuándo usar esta estrategia:**
- Cuando el pipeline siempre procesa el dataset **completo** (no incremental).
- Cuando los datos fuente son inmutables o se reprocesan desde cero cada vez.
- Cuando hay una sola fuente de datos (un solo Parquet → una tabla).

Este es exactamente el caso del PVOD: el CSV fuente siempre contiene las mismas ~272K filas, el pipeline las limpia, y las carga completas.

### Opción B: Nombre determinista del blob (idempotencia real)

Si se quisiera mantener `WRITE_APPEND` (por ejemplo, para carga incremental futura), el nombre del blob debería ser determinista — no basado en timestamp:

```python
# En vez de:
ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
return f"gold/pvod_{ts}.parquet"

# Usar un nombre fijo:
return "gold/pvod_latest.parquet"
```

Con la misma URI → el mismo blob_md5 (si los datos no cambiaron) → el mismo Job ID → BigQuery rechaza el job como "ya ejecutado" → sin duplicación.

### Opción C: Merge/Upsert (para pipelines incrementales complejos)

Para pipelines que cargan datos parciales, BigQuery soporta `MERGE` statements:

```sql
MERGE target_table T
USING staging_table S
ON T.date_time = S.date_time AND T.station_id = S.station_id
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
```

Esto es innecesario para el PVOD actual (carga completa, no incremental), pero sería la solución correcta si el pipeline evolucionara a cargas incrementales.

### La combinación correcta desde el inicio hubiera sido: Opción A

`WRITE_TRUNCATE` — simple, infalible, y alineado con la naturaleza del pipeline (carga completa del dataset PVOD cada vez).

---

## Plan de Implementación

### Fase 1: Limpieza de la tabla existente

Ejecutar un `CREATE OR REPLACE TABLE` que deduplique las filas manteniendo el esquema, particionamiento y clustering:

```sql
CREATE OR REPLACE TABLE `serverless-solar-etl.serverless_solar_etl_dataset.pvod_metrics`
PARTITION BY DATE(date_time)
CLUSTER BY station_id
AS
SELECT DISTINCT *
FROM `serverless-solar-etl.serverless_solar_etl_dataset.pvod_metrics`;
```

**Verificación post-limpieza:**

```sql
SELECT COUNT(*) as total_rows
FROM `serverless-solar-etl.serverless_solar_etl_dataset.pvod_metrics`;
-- Esperado: 271,967
```

### Fase 2: Prevención — Cambiar `WRITE_APPEND` → `WRITE_TRUNCATE`

#### Archivo: [`src/app/infrastructure/bigquery_adapter.py`](../../src/app/infrastructure/bigquery_adapter.py)

**Antes (línea 229):**

```python
job_config.write_disposition = bq_module.WriteDisposition.WRITE_APPEND
```

**Después:**

```python
job_config.write_disposition = bq_module.WriteDisposition.WRITE_TRUNCATE
```

El comentario del PRD §4 en las líneas 225-228 debería actualizarse para reflejar el nuevo comportamiento:

```python
# PRD §4: Idempotencia y modo de escritura
# WRITE_TRUNCATE garantiza que cada ejecución del pipeline deje
# la tabla con exactamente los registros del Parquet actual,
# eliminando cualquier posibilidad de acumulación de duplicados.
job_config.write_disposition = bq_module.WriteDisposition.WRITE_TRUNCATE
```

### Fase 3: Verificación

1. **Ejecutar el pipeline** (`POST /api/v1/etl/run`) después del cambio.
2. **Verificar el conteo** — la tabla debe tener exactamente ~271,967 filas.
3. **Ejecutar el pipeline una segunda vez** — el conteo debe seguir siendo ~271,967 (no ~544K).
4. **Verificar la query `/aggregate`** — los resultados deben ser idénticos antes y después.

### Fase 4 (Opcional): Limpiar Parquets duplicados en GCS

Los 5 Parquets en `gs://\<bucket\>/gold/` contienen los mismos datos con diferentes nombres. Se puede limpiar manualmente o dejar que un lifecycle policy los archive.

---

## Archivos Involucrados

| Archivo | Cambio | Descripción |
|---|---|---|
| [`src/app/infrastructure/bigquery_adapter.py`](../../src/app/infrastructure/bigquery_adapter.py) | Línea 229 | Cambiar `WRITE_APPEND` → `WRITE_TRUNCATE` |
| BigQuery (consola) | Query única | `CREATE OR REPLACE TABLE ... AS SELECT DISTINCT *` |

---

## Impacto en Costos

| Concepto | Antes (4x) | Después (1x) |
|---|---|---|
| Almacenamiento lógico BQ | 124.5 MB | ~31 MB |
| Bytes escaneados por query | ~26 MB | ~6.5 MB |
| Queries futuras con `SUM()`/`COUNT()` | **Resultados incorrectos** | Correctos |
| Ejecuciones repetidas del pipeline | Acumulan +272K filas | Reemplazan (siempre 272K) |
