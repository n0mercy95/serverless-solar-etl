# Plan de Implementación: Transición a Workload Identity Federation (WIF) y Application Default Credentials (ADC)

Este plan detalla los cambios técnicos necesarios para eliminar la dependencia explícita del archivo estático `credentials.json` en los inicializadores de cliente de GCP. Se implementará una arquitectura basada en **Application Default Credentials (ADC)**, facilitando la transición a **Workload Identity Federation (WIF)** en producción (Cloud Run) y en pipelines de CI/CD (GitHub Actions), al tiempo que se mantiene la compatibilidad local.

## Resumen de Cambios

1. **`config.py`**: Simplificar la lógica de resolución del path de credenciales. Si la ruta existe en desarrollo local, se inyectará directamente en la variable de entorno `os.environ["GOOGLE_APPLICATION_CREDENTIALS"]` para que el SDK de Google la consuma de manera nativa. Si no existe, no se realiza ninguna acción (evitando fallos/crashes) para permitir que ADC use el servidor de metadatos o WIF en producción.
2. **`main.py`**: Cambiar la instanciación de `bigquery.Client` para usar el constructor estándar compatible con ADC: `bigquery.Client(project=settings.gcp_project_id)`.
3. **`pipeline.py`**: Eliminar el argumento `credentials_path` al instanciar los componentes de infraestructura/aplicación (`GCSParquetExporter`, `BigQueryAdapter`, `ScatterPlotGenerator`).
4. **`bigquery_adapter.py`**, **`gcs_parquet_exporter.py`** y **`scatter_plot_generator.py`**: Eliminar el uso de `.from_service_account_json()`. Instanciar los clientes con el constructor estándar (`bigquery.Client(project=...)` y `storage.Client()`) para que el SDK de Google busque las credenciales automáticamente usando ADC.

---

## Cambios Propuestos

### Componente: Configuración y API

#### [MODIFY] [config.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/config.py)
* Refactorizar el validador `_resolve_credentials_path` para configurar de manera nativa la variable de entorno del sistema `GOOGLE_APPLICATION_CREDENTIALS` si el archivo existe localmente.
* Asegurar que no se lance una excepción si el archivo no existe (producción/WIF). Si la variable de entorno apunta a un archivo que no existe localmente, se remueve de `os.environ` para evitar errores del SDK de Google y forzar la caída a ADC nativo.

#### [MODIFY] [main.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/main.py)
* Eliminar por completo el método `bigquery.Client.from_service_account_json(...)`.
* Inicializar el cliente global de BigQuery de la siguiente manera:
  ```python
  app.state.bq_client = bigquery.Client(project=settings.gcp_project_id)
  ```

#### [MODIFY] [pipeline.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/pipeline.py)
* Eliminar el argumento obsoleto `credentials_path` al instanciar los exportadores y adaptadores dentro de la función `build_pipeline(...)`.

---

### Componente: Infraestructura y Adaptadores

#### [MODIFY] [bigquery_adapter.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/bigquery_adapter.py)
* Eliminar el parámetro `credentials_path` del constructor `__init__` (o marcarlo como deprecado/sin efecto para compatibilidad).
* Modificar la instanciación interna del cliente para usar ADC nativo:
  ```python
  bq_client = bigquery.Client(project=self._project_id)
  ```

#### [MODIFY] [gcs_parquet_exporter.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/gcs_parquet_exporter.py)
* Eliminar el parámetro `credentials_path` del constructor `__init__`.
* Modificar la instanciación interna del cliente para usar ADC nativo:
  ```python
  storage_client = storage.Client()
  ```

#### [MODIFY] [scatter_plot_generator.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/scatter_plot_generator.py)
* Eliminar el parámetro `credentials_path` del constructor `__init__`.
* Modificar la instanciación interna del cliente para usar ADC nativo:
  ```python
  client = storage.Client()
  ```

---

## Plan de Verificación

### Pruebas Automatizadas
* Ejecutar la suite de tests existente para asegurar que el pipeline sigue ejecutándose sin problemas locales:
  ```bash
  pytest
  ```

### Verificación Manual
* Levantar el servidor localmente con `uvicorn app.main:app --reload` y realizar una petición de prueba al endpoint `/run` o `/aggregate` para constatar que el cliente de BigQuery y GCS se autentican correctamente usando el archivo local inyectado vía `os.environ`.
