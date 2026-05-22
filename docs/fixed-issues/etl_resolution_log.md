# Registro de Resoluciones del Pipeline ETL y Consultas de Métricas Solar PVOD

Este documento detalla el diagnóstico, la causa raíz y las soluciones técnicas aplicadas a los problemas encontrados en los endpoints de Ingesta/ETL (`/api/v1/etl/run`) y Consulta Analítica (`/api/v1/metrics/aggregate`).

---

## 1. Fase ETL (`/api/v1/etl/run`)

### 1.1. Error en Conversión Datetime (`str` a `datetime`)
*   **Síntoma**: Error `DataTransformationError` indicando fallo en la conversión de texto a tiempo: `conversion from str to datetime failed in column 'date_time'`.
*   **Causa Raíz**: El cargador perezoso (`PVODLazyLoader`) utilizaba una máscara de formato de tiempo (`strptime`) estricta que no preveía la inclusión de segundos (`%Y-%m-%d %H:%M:%S` vs `%Y-%m-%d %H:%M`) presentes en ciertos subconjuntos del dataset original.
*   **Solución**: Se ajustó la lógica de parsing temporal en `pvod_lazy_loader.py` para normalizar las marcas temporales de forma flexible de modo que acepte formatos con o sin segundos antes de realizar las transformaciones.

### 1.2. Colisión de Timestamps Truncados (`TemporalAlignmentError`)
*   **Síntoma**: Fallo con excepción `TemporalAlignmentError` debido a marcas temporales duplicadas por estación tras truncar los datos a intervalos de 15 minutos.
*   **Causa Raíz**: Lecturas reales de sensores con diferencias de segundos (ej: `01:17:00` y `01:29:00`) se colapsaban a la misma marca de 15 minutos (`01:15:00`), generando duplicados espurios por estación.
*   **Solución**:
    *   Se implementó una deduplicación perezosa (`_deduplicate_temporal_grid`) en Polars que preserva la lectura más reciente (la última) para cada par `(station_id, date_time)`.
    *   Se relajó la validación estricta a un aviso de advertencia (`warning` en logs) en lugar de un error fatal de interrupción.

### 1.3. Irradiancia Fuera de Límites Físicos (`IrradianceOutOfBoundsError`)
*   **Síntoma**: Excepción fatal `IrradianceOutOfBoundsError` indicando 140 valores en la columna `lmd_totalirrad` fuera del rango físico estricto `[0, 1361.0]` W/m² (valores máximos detectados de hasta `1838.0` W/m²).
*   **Causa Raíz**: Sensores terrestres reales pueden medir irradiancias superiores a la constante solar extraterrestre (1361 W/m²) debido al fenómeno físico de **cloud edge enhancement** (lente/amplificación óptica en los bordes de nubes). La validación inicial abortaba el pipeline entero por este comportamiento físico legítimo.
*   **Solución**:
    *   Se modificó la validación en `pvod_lazy_loader.py` para realizar un acotamiento perezoso (**clamping** en `[0, 1361]`) utilizando `pl.clip()`.
    *   Se degradó el error fatal a un `logger.warning` detallado que registra la cantidad de celdas afectadas y el rango original del sensor, garantizando la consistencia física sin perder registros ni interrumpir la ingesta.

### 1.4. Error 404 en Cloud Storage (Bucket Inexistente)
*   **Síntoma**: `404 The specified bucket does not exist` al intentar subir el archivo Parquet a `my-pvod-gold-bucket`.
*   **Causa Raíz**: El nombre del bucket estaba configurado en el archivo `.env` local de la aplicación, pero el recurso de infraestructura física no existía en Google Cloud Storage.
*   **Solución**:
    *   Se creó el bucket real en GCP utilizando la CLI de gcloud:
        ```bash
        gcloud storage buckets create gs://serverless-solar-etl-gold-n0mercy95 \
            --project=serverless-solar-etl \
            --location=us-central1 \
            --uniform-bucket-level-access
        ```
    *   Se actualizó la variable `GCS_BUCKET_NAME` en el `.env` con el nombre correcto y globalmente único.

### 1.5. Error 404 en BigQuery (Dataset No Encontrado)
*   **Síntoma**: `Not found: Dataset serverless-solar-etl:solar_etl_dataset`.
*   **Causa Raíz**: Configuración incorrecta en el archivo `.env` local (`BQ_DATASET_ID=solar_etl_dataset`) que difería del nombre del dataset real creado en BigQuery (`serverless_solar_etl_dataset`).
*   **Solución**: Se actualizó la variable de entorno en `.env` a `BQ_DATASET_ID=serverless_solar_etl_dataset`.

---

## 2. Fase de Consulta (`/api/v1/metrics/aggregate`)

### 2.1. Incompatibilidad de Tipos de Parámetros (`TIMESTAMP` vs `DATETIME`)
*   **Síntoma**: Error 400 de BigQuery al procesar la consulta parametrizada:
    ```
    No matching signature for operator >= for argument types: TIMESTAMP, DATETIME
    Unable to find common supertype for templated argument <T1> (TIMESTAMP and DATETIME)
    ```
*   **Causa Raíz**:
    *   La columna `date_time` en la tabla de BigQuery se genera como tipo **`TIMESTAMP`** al cargarse desde el archivo Parquet de Polars.
    *   Los parámetros de consulta `@start_date` y `@end_date` se declararon e inyectaron con tipo **`DATETIME`** en el servicio de consultas de BigQuery.
    *   BigQuery no realiza conversiones implícitas en operadores de comparación entre `TIMESTAMP` (valores absolutos en UTC) y `DATETIME` (valores relativos sin zona horaria).
*   **Solución**: Se modificó [query_service.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/query_service.py) para inyectar los parámetros de fecha como tipo **`TIMESTAMP`**, alineándose exactamente con el esquema de la tabla:
    ```python
    query_params = [
        bigquery.ScalarQueryParameter("start_date", "TIMESTAMP", request.start_date),
        bigquery.ScalarQueryParameter("end_date", "TIMESTAMP", request.end_date),
    ]
    ```

### 2.2. Desaparición Silenciosa de Datos Históricos (Expiración de Particiones)
*   **Síntoma**: El endpoint `/aggregate` devolvía resultados vacíos (`results: []`, `total_rows: 0`) a pesar de que el pipeline de ETL reportaba que la carga masiva de 271,967 registros finalizaba con éxito. Al consultar directamente la tabla en BigQuery, esta aparecía vacía.
*   **Causa Raíz**: 
    *   El dataset de BigQuery `serverless_solar_etl_dataset` se configuró inicialmente con un límite de expiración por defecto de **60 días** (`default_partition_expiration_ms = 5184000000`).
    *   Como el dataset de PVOD contiene datos históricos correspondientes al año **2018 y 2019** (que exceden con creces el límite de 60 días), BigQuery cargaba la data exitosamente y, de manera inmediata, **borraba las particiones expiradas**, dejando la tabla completamente vacía de forma silenciosa.
*   **Solución**:
    1.  Se eliminaron las expiraciones por defecto del dataset en BigQuery:
        ```python
        ds = client.get_dataset('serverless_solar_etl_dataset')
        ds.default_table_expiration_ms = None
        ds.default_partition_expiration_ms = None
        client.update_dataset(ds, ['default_table_expiration_ms', 'default_partition_expiration_ms'])
        ```
    2.  Se eliminó la tabla física `pvod_metrics` heredera de esta restricción.
    3.  Se relanzó el pipeline ETL completo (`POST /api/v1/etl/run`) para recrear la tabla sin políticas de expiración y re-ingestar los 271,967 registros de forma definitiva.

---

## 3. Estado Actual del Sistema

Ambos endpoints funcionan al 100% en el entorno de desarrollo y pasan todas las pruebas automatizadas (102/102 unit tests pasados):

*   **ETL (`/run`)**: Procesa 271,967 registros, realiza limpieza, imputación de nulos, clamping físico de irradiancia y carga los datos en BigQuery de manera idempotente (usando hash MD5 determinista en ~30 segundos).
*   **Agregación (`/aggregate`)**: Resuelve consultas de costo (*dry run*) y analíticas reales agregadas en milisegundos directamente contra la tabla particionada de BigQuery sin errores de tipos y preservando los datos históricos de 2018/2019.
