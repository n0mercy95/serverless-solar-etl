# Task 4.1 Implementation Plan: API Serverless & Consulta Segura

Este plan detalla la implementación de la Tarea 4.1 (Fase 4), la cual expone los datos procesados en BigQuery mediante una API construida con FastAPI. Se hace énfasis en la seguridad, eficiencia y el control de costos garantizando un nivel gratuito.

## User Review Required

> [!IMPORTANT]
> **Cuota de BigQuery**: Se establecerá por defecto un límite estricto de `bq_max_bytes_billed` (ej. 100 MB) para todas las consultas. Esto previene costos inesperados. ¿Es 100 MB un límite razonable para sus pruebas?

> [!IMPORTANT]
> **Endpoint(s) de Consulta**: Se proveerá un endpoint base `/api/v1/metrics/aggregate` que permitirá calcular promedios de potencia por estación en un rango de fechas. ¿Desea algún otro filtro o endpoint en específico en esta etapa?

## Proposed Changes

---

### Application Configuration
Se actualizarán las configuraciones para soportar el control de costos.

#### [MODIFY] `src/app/application/config.py`
- Añadir campo `bq_max_bytes_billed: int` a `Settings` con un valor por defecto (ej. 104857600 bytes = 100MB). Esto asegura que ninguna consulta excederá este costo, cumpliendo el requerimiento de "funcionar gratuitamente".

---

### Interfaces & Schemas
Modelos Pydantic tipados y dependencias de inyección para FastAPI.

#### [NEW] `src/app/interfaces/schemas.py`
- Crear el modelo Pydantic `MetricsQueryRequest` con campos (ej. `start_date`, `end_date`, `dry_run: bool = False`).
- Crear el modelo Pydantic `MetricsQueryResponse` y `DryRunResponse`.

#### [NEW] `src/app/interfaces/dependencies.py`
- Crear función `get_bq_client()` que retornará el cliente de BigQuery instanciado en el arranque de la app, permitiendo reciclar conexiones de red eficientemente a través de `Depends`.

---

### Application & Query Execution
La lógica responsable de armar la consulta parametrizada y ejecutarla.

#### [NEW] `src/app/application/query_service.py`
- Crear `BigQueryQueryService`.
- Implementar el método `get_aggregated_metrics()` que:
  1. Construya una consulta SQL usando `@start_date` y `@end_date`.
  2. Configure `bigquery.ScalarQueryParameter` para inyectar estos valores previniendo inyección SQL.
  3. Establezca `job_config = bigquery.QueryJobConfig(dry_run=dry_run, maximum_bytes_billed=settings.bq_max_bytes_billed, use_query_cache=False)`.
  4. Retorne los resultados reales o bien las métricas del *dry run* (`total_bytes_processed`).

---

### API Endpoints
Los controladores (routers) de FastAPI.

#### [NEW] `src/app/interfaces/api.py`
- Declarar un `APIRouter(prefix="/api/v1")`.
- Implementar el endpoint `POST /metrics/aggregate` recibiendo `MetricsQueryRequest` y utilizando la dependencia del cliente BigQuery para invocar el `BigQueryQueryService`.

#### [MODIFY] `src/app/main.py`
- En `@app.on_event("startup")`, instanciar el cliente BigQuery y asignarlo de forma global para la aplicación (`app.state.bq_client`).
- Incluir el nuevo router en la aplicación principal (`app.include_router(...)`).

## Verification Plan

### Automated Tests
- Ejecutar la API localmente mediante validación sintáctica (el código se compila/importa exitosamente).
- (Opcional) Si la base de código ya incluye un entorno de pruebas asíncronas (`pytest`), podríamos agregar tests del router, pero para este paso validaremos manualmente.

### Manual Verification
1. Arrancar el servicio uvicorn en local.
2. Hacer un request de tipo *dry run* a `/api/v1/metrics/aggregate` y verificar que la respuesta indica el costo estimado (en bytes) sin devolver datos y sin facturar a GCP.
3. Hacer un request normal intentando sobrepasar los límites para verificar que el API arroja un error de cuota controlada.
