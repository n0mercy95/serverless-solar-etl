# Task 4.3 Implementation Plan: Despliegue Final en Cloud Run

Este plan detalla los pasos finales para llevar nuestra API Serverless a producción en Google Cloud Run, asegurando el auto-escalado desde cero y cumpliendo con las políticas de seguridad estipuladas en el PRD.

## User Review Required

> [!IMPORTANT]
> **Gestión de Secretos**: El PRD especifica: *"En Cloud Run de producción, inyectar variables en memoria vía Google Cloud Secret Manager, jamás dentro de la imagen estática."*
> ¿Ya tienes creados los secretos en GCP (como tu `BQ_DATASET_ID`, credenciales, etc.), o prefieres que el script de despliegue referencie variables de entorno estándar por el momento para pruebas?

> [!IMPORTANT]
> **Acceso a la API**: Por defecto, configuraremos el despliegue de Cloud Run para permitir acceso no autenticado (`--allow-unauthenticated`) de manera que puedas hacer pruebas rápidas con herramientas como `curl` o Postman. ¿Estás de acuerdo con esto para esta fase?

## Proposed Changes

---

### Scripts de Automatización

#### [NEW] `scripts/deploy_to_cloud_run.sh`
Se creará un script bash que encapsule el comando `gcloud run deploy` con los siguientes argumentos clave para cumplir el PRD:
- `--image`: La URI de la imagen en Artifact Registry (construida en la Tarea 4.2).
- `--min-instances 0`: Garantiza el **auto-escalado a cero** para no incurrir en costos cuando no hay tráfico.
- `--max-instances 5`: Límite superior para evitar costos inesperados si hay un pico de tráfico.
- `--port 8080`: Puerto donde escucha el contenedor de Uvicorn/FastAPI.
- `--set-secrets`: Integración con Google Cloud Secret Manager para inyectar configuración de manera segura (ej. `GCP_PROJECT_ID=project_id_secret:latest`).
- `--allow-unauthenticated`: Para permitir validaciones públicas.

---

### Documentación

#### [MODIFY] `README.md`
Actualizaremos el `README.md` del proyecto añadiendo:
1. Instrucciones de despliegue usando los scripts `build_and_push.sh` y `deploy_to_cloud_run.sh`.
2. Documentación de los endpoints generados para que futuros consumidores sepan cómo usar el *dry_run* y las consultas de métricas.

## Verification Plan

### Manual Verification
Una vez que el despliegue termine, Cloud Run nos retornará una URL pública (ej. `https://pvod-api-xyz.a.run.app`).

1. **Prueba de Health Check**:
   Ejecutar un GET a `https://[URL_CLOUD_RUN]/health` y validar que el contenedor arranca en frío (cold start) y retorna `{"status": "healthy"}`.
2. **Prueba de Dry Run**:
   Ejecutar un `POST` usando `curl` hacia `/api/v1/metrics/aggregate` con `"dry_run": true` en el payload JSON.
3. **Validación End-to-End**:
   Ejecutar el `POST` definitivo para obtener el promedio de potencia de una estación y revisar los logs de Google Cloud Logging para certificar que el formato estructurado JSON esté funcionando.
