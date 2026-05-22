# ETL Solar Serverless - Procesamiento del Dataset PVOD ☀️

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Google Cloud](https://img.shields.io/badge/GCP-Serverless-4285F4?logo=google-cloud)
![Polars](https://img.shields.io/badge/Polars-Blazing%20Fast-E6A514)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-Multi--stage-2496ED?logo=docker)

> **Estado del Proyecto:** 🚧 En construcción (Fase 4: Contenedorización Final, Despliegue API Serverless y Servicio de Consulta).

## 📖 Descripción del Proyecto

La intermitencia es el mayor desafío de la energía solar. Este proyecto resuelve ese problema construyendo un **pipeline de datos serverless de grado industrial**. Al ingestar, limpiar matemáticamente (Zeroing nocturno, filtros Hampel) y alinear datos meteorológicos (NWP) con sensores locales (LMD), este Data Warehouse entrega métricas inmaculadas listas para alimentar modelos de Inteligencia Artificial. El resultado permite a los operadores de redes **predecir la generación con alta precisión**, evitar multas por desbalances y optimizar la venta de energía.

El flujo culmina exponiendo métricas agregadas mediante una API RESTful de alto rendimiento.

## 🏗️ Arquitectura del Sistema (GCP)

La solución está diseñada bajo principios de Clean Architecture y opera de forma 100% serverless en Google Cloud Platform (GCP).

* **Orquestación:** Utilización de **Cloud Scheduler** para la invocación asíncrona y automatizada del pipeline ETL.
* **Staging Area (Capa Oro):** **Cloud Storage** actúa como buffer temporal, almacenando datos extraídos en formato binario altamente comprimido Apache Parquet.
* **Data Warehouse:** **BigQuery** gestiona la persistencia transaccional ACID de los datos procesados, utilizando esquemas estrictamente tipados y almacenamiento columnar.
* **Procesamiento y API:** Contenedores Docker inmutables desplegados en **Cloud Run** que alojan las rutinas del ETL (basadas en Polars) y el microservicio de la API (construido con FastAPI).

## 🚀 Highlights Técnicos

* **Patrones de Diseño:** Implementación estricta de **Patrón Factory** (ingesta) y **Strategy** (limpieza).
* **FinOps Integrado:** Protección de costos mediante **Dry Runs** y cuotas límite en BigQuery (`maximum_bytes_billed`).
* **Performance:** Sustitución de Pandas por **Polars** (Lazy Evaluation) para maximizar la eficiencia de CPU/RAM en contenedores efímeros.

## 🗺️ Roadmap y Próximos Pasos

El desarrollo de este proyecto está dividido en milestones progresivos:

* [x] **Fase 0: Setup Inicial & Preprocesamiento Off-line**
    * Definición del Product Requirements Document (PRD).
    * Configuración del repositorio, `.gitignore` y variables de entorno base.
    * **Preprocesamiento Off-line:** Creación del script `scripts/consolidate_pvod.py` con Polars para consolidar los 10 CSVs del dataset PVOD en un único archivo maestro `data/pvod.csv`, validando sus 271,968 registros e incluyendo la columna `station_id` para el clustering en BigQuery.
* [x] **Fase 1: Aprovisionamiento de Infraestructura, Seguridad y Componentes de Ingesta**
    * [x] **Fase 1.0 (Entorno de Desarrollo):** Configuración de la Cuenta de Servicio en Google Cloud con roles estrictos (BigQuery Editor/User, Storage Creator, Logging Writer) y obtención de las credenciales base para `.env.example` (`GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`).
    * [x] **Fase 1.1 (BigQuery):** Creación del Dataset en BigQuery (`solar_etl_dataset`) y definición de la tabla destino (`pvod_metrics`).
    * [x] **Fase 1.2 (Cloud Storage):** Creación y configuración del GCS Bucket (Capa Oro) multiregional (`GCS_BUCKET_NAME`).
    * [x] Implementación de capas de ingesta usando el Patrón Factory.
* [x] **Fase 2: Transformación Analítica, Fusión Numérica y Perfilado**
    * [x] Carga perezosa con Polars (`scan_csv`) y alineamiento temporal a grilla de 15 minutos.
    * [x] Aplicación del Patrón Strategy para la purga heurística (NighttimeZeroing, HampelFilter, MissingValueImputer).
    * [x] Volcado final en Apache Parquet comprimido (Zstandard) a GCS (Capa Oro).
* [x] **Fase 3: Integración Transaccional Resiliente y Despliegue de Observabilidad**
    * [x] Implementación de JSON Structured Logging integrado con Google Cloud Logging.
    * [x] Ejecución atómica e idempotente del BigQuery Load Job.
* [x] **Fase 4: Contenedorización Final, Despliegue API Serverless y Servicio de Consulta**
    * [x] Desarrollo de la API con FastAPI y Pydantic.
    * [x] Contenedorización multi-stage purgada y validada.
    * [x] Scripts de despliegue final en Google Cloud Run y Artifact Registry.

## 🚀 Despliegue y Uso (Cloud Run)

Para desplegar la aplicación en Google Cloud Run, sigue estos pasos desde tu entorno local (asegurando tener `gcloud` autenticado y `docker` corriendo):

1. **Construir y subir la imagen (Artifact Registry):**
   ```bash
   ./scripts/build_and_push.sh
   ```

2. **Desplegar la API Serverless (Cloud Run):**
   ```bash
   ./scripts/deploy_to_cloud_run.sh
   ```
   *Nota: El servicio está configurado por defecto para **escalar a cero** (`--min-instances 0`) minimizando costos.*

### Consultando la API

Una vez desplegada (o corriendo localmente), puedes realizar consultas de agregación de potencia. La API está protegida por un límite de costos gratuito usando la funcionalidad de cuota de BigQuery (`maximum_bytes_billed`) y soporta **Dry Runs**.

Ejemplo de llamada `cURL` (reemplaza `[URL]` por tu endpoint de Cloud Run o `http://localhost:8080`):

```bash
curl -X POST "[URL]/api/v1/metrics/aggregate" \
     -H "Content-Type: application/json" \
     -d '{
           "start_date": "2018-07-01T00:00:00",
           "end_date": "2018-07-02T23:59:59",
           "dry_run": true
         }'
```

La respuesta estimará los costos en bytes sin incurrir en facturación real de GCP si `dry_run` es `true`.
