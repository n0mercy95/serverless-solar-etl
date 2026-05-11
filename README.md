# ETL Solar Serverless - Procesamiento del Dataset PVOD ☀️

> **Estado del Proyecto:** 🚧 En construcción (Fase 4: Contenedorización Final, Despliegue API Serverless y Servicio de Consulta).

## 📖 Descripción del Proyecto

Este proyecto es un sistema de ingeniería de datos nativo en la nube, diseñado para la ingesta automatizada, limpieza matemática estricta, transformación algorítmica y disponibilidad analítica del Photovoltaic Power Output Dataset (PVOD). 

El objetivo principal es habilitar el monitoreo y proporcionar métricas para modelos precisos de pronóstico de potencia fotovoltaica (NWP y LMD), fundamentales para el balanceo de carga en mercados de energía. El flujo culmina exponiendo métricas agregadas mediante una API RESTful de alto rendimiento.

## 🏗️ Arquitectura del Sistema (GCP)

La solución está diseñada bajo principios de Clean Architecture y opera de forma 100% serverless en Google Cloud Platform (GCP).

* **Orquestación:** Utilización de **Cloud Scheduler** para la invocación asíncrona y automatizada del pipeline ETL.
* **Almacenamiento Intermedio (Data Lake):** **Cloud Storage** actúa como buffer temporal (nivel oro), almacenando datos extraídos en formato binario altamente comprimido Apache Parquet.
* **Data Warehouse:** **BigQuery** gestiona la persistencia transaccional ACID de los datos procesados, utilizando esquemas estrictamente tipados y almacenamiento columnar.
* **Procesamiento y API:** Contenedores Docker inmutables desplegados en **Cloud Run** que alojan las rutinas del ETL (basadas en Polars) y el microservicio de la API (construido con FastAPI).

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
* [ ] **Fase 4: Contenedorización Final, Despliegue API Serverless y Servicio de Consulta**
    * Desarrollo de la API con FastAPI y Pydantic.
    * Despliegue final de la imagen multi-stage en Google Cloud Run.[cite: 364, 365].
