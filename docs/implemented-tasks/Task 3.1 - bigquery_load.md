# Tarea 3.1 — Activación Global de Manipuladores Estructurales JSON (Google Cloud Logging)

## Contexto

El PRD §5 (Observabilidad y Formato de Logging) exige:

> Abandonar logs en texto plano. Implementar un **CloudLoggingHandler** (JSON Structured Logging) emitido a **stdout** integrado con Google Cloud Logging. Requerimientos clave para la estructura JSON: llaves reservadas **`severity`**, **`message`**, **`logging.googleapis.com/trace`**, y un diccionario **`attributes`** adjuntando métricas vitales como `records_processed`, `anomalies_detected`, y `station_id`.

Actualmente, los 10 módulos del proyecto usan `logging.getLogger(__name__)` con `logging.basicConfig()` en `main.py`. Los mensajes `extra={"attributes": {...}}` ya están preparados en todo el codebase, pero **no se formatean como JSON estructurado** — simplemente se pierden con el formatter por defecto.

## Propuesta de Cambios

### Componente 1: Módulo Centralizado de Logging (Infrastructure)

#### [NEW] [cloud_logging.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/cloud_logging.py)

Módulo centralizado que implementa:

1. **`StructuredJSONFormatter(logging.Formatter)`** — Formateador que serializa cada log record a JSON compatible con Google Cloud Logging:
   - `severity` → mapeado desde `record.levelname` (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - `message` → texto del log
   - `logging.googleapis.com/trace` → extraído de variable de entorno `X_CLOUD_TRACE_CONTEXT` o del header inyectado por Cloud Run (si disponible)
   - `timestamp` → ISO 8601 UTC
   - `logger` → `record.name` (ej. `app.infrastructure.github_extractor`)
   - `attributes` → diccionario de métricas del `record.__dict__.get("attributes", {})`
   - `source_location` → `{"file": record.pathname, "line": record.lineno, "function": record.funcName}`
   - `exception` → traceback formateado si `record.exc_info` no es `None`

2. **`setup_cloud_logging(log_level: str, gcp_project_id: str, environment: str)`** — Función de inicialización global que:
   - Crea un `logging.StreamHandler(sys.stdout)` (no stderr, requisito de Cloud Run)
   - Asigna `StructuredJSONFormatter` al handler
   - Lo adjunta al logger raíz (`logging.getLogger()`)
   - Configura el nivel global desde `Settings.log_level`
   - En producción (`environment == "production"`), integra opcionalmente con `google.cloud.logging.Client` para enviar logs directamente a Cloud Logging API (además de stdout)

> [!IMPORTANT]
> Todo el output se emite a **stdout** como JSON de una línea. Cloud Run/Cloud Logging parsea automáticamente JSON de stdout y lo estructura en la consola de GCP.

---

### Componente 2: Excepciones Extendidas (Domain)

#### [MODIFY] [exceptions.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/domain/exceptions.py)

Agregar dos nuevas excepciones para la Fase 3:

- **`BigQueryConnectionError(SolarETLError)`** — Fallo de conexión o autenticación con BigQuery (requerida explícitamente en PRD §5)
- **`ObservabilityConfigError(SolarETLError)`** — Error de configuración del sistema de logging (handler no inicializado, project_id inválido, etc.)

---

### Componente 3: Integración con Entry Point

#### [MODIFY] [main.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/main.py)

- Reemplazar `logging.basicConfig(level=logging.INFO)` por una llamada a `setup_cloud_logging()` que inicializa el handler estructurado JSON globalmente.
- Importar `Settings` para obtener `log_level`, `gcp_project_id`, y `environment`.
- Añadir un event handler de startup de FastAPI para loggear el arranque del servicio con métricas estructuradas.

---

### Componente 4: Excepciones Faltantes en Módulos Existentes

Se revisarán los módulos existentes para asegurar que:
- Los `except Exception as exc` que aún existan se reemplacen por excepciones específicas donde sea posible (PRD §5: "eludiendo cláusulas amplias de captura").
- Cada módulo que ya usa `extra={"attributes": {...}}` seguirá funcionando **sin cambios** — el nuevo formatter los consumirá automáticamente.

> [!NOTE]
> Los 10 módulos existentes **no requieren cambios en sus llamadas a `logging`**. Todos ya usan `logger = logging.getLogger(__name__)` y `extra={"attributes": {...}}`. El cambio es 100% transparente: solo se cambia el formatter global.

---

## Estructura de un Log Entry (Ejemplo)

```json
{
  "severity": "INFO",
  "message": "Extracción desde GitHub Raw completada",
  "timestamp": "2026-05-11T14:20:00.123456Z",
  "logging.googleapis.com/trace": "projects/my-project/traces/abc123",
  "logger": "app.infrastructure.github_extractor",
  "attributes": {
    "source": "github_raw",
    "bytes_downloaded": 45678901,
    "size_mb": 43.55
  },
  "source_location": {
    "file": "src/app/infrastructure/github_extractor.py",
    "line": 101,
    "function": "extract_data_to_buffer"
  }
}
```

## Plan de Verificación

### Tests Automatizados
- Ejecutar `pytest tests/` para verificar que los tests existentes no rompen.
- Crear test unitario `tests/test_cloud_logging.py` que:
  - Verifique que un log record con `extra={"attributes": {...}}` se serializa a JSON válido.
  - Verifique las llaves reservadas de GCP (`severity`, `message`, `logging.googleapis.com/trace`).
  - Verifique que excepciones se formatean correctamente en el campo `exception`.

### Verificación Manual
- Ejecutar `uvicorn app.main:app` localmente y verificar que los logs de stdout son JSON de una línea.
