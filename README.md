# ETL Solar Serverless - Procesamiento del Dataset PVOD ☀️

> **Estado del Proyecto:** 🚧 En construcción (Fase 0: Setup Inicial y Diseño de Arquitectura).

## 📖 Descripción del Proyecto

[cite_start]Este proyecto es un sistema de ingeniería de datos nativo en la nube, diseñado para la ingesta automatizada, limpieza matemática estricta, transformación algorítmica y disponibilidad analítica del Photovoltaic Power Output Dataset (PVOD)[cite: 295]. 

[cite_start]El objetivo principal es habilitar el monitoreo y proporcionar métricas para modelos precisos de pronóstico de potencia fotovoltaica (NWP y LMD), fundamentales para el balanceo de carga en mercados de energía[cite: 296]. [cite_start]El flujo culmina exponiendo métricas agregadas mediante una API RESTful de alto rendimiento[cite: 297].

## 🏗️ Arquitectura del Sistema (GCP)

[cite_start]La solución está diseñada bajo principios de Clean Architecture y opera de forma 100% serverless en Google Cloud Platform (GCP)[cite: 299]:

* [cite_start]**Orquestación:** Utilización de **Cloud Scheduler** para la invocación asíncrona y automatizada del pipeline ETL[cite: 300].
* [cite_start]**Almacenamiento Intermedio (Data Lake):** **Cloud Storage** actúa como buffer temporal (nivel oro), almacenando datos extraídos en formato binario altamente comprimido Apache Parquet[cite: 303].
* [cite_start]**Data Warehouse:** **BigQuery** gestiona la persistencia transaccional ACID de los datos procesados, utilizando esquemas estrictamente tipados y almacenamiento columnar[cite: 304].
* [cite_start]**Procesamiento y API:** Contenedores Docker inmutables desplegados en **Cloud Run** que alojan las rutinas del ETL (basadas en Polars) y el microservicio de la API (construido con FastAPI)[cite: 301, 307].

## 🗺️ Roadmap y Próximos Pasos

El desarrollo de este proyecto está dividido en milestones progresivos:

* [x] **Fase 0: Setup Inicial**
    * Definición del Product Requirements Document (PRD).
    * Configuración del repositorio, `.gitignore` y variables de entorno base.
* [cite_start][ ] **Fase 1: Aprovisionamiento de Infraestructura, Seguridad y Componentes de Ingesta** [cite: 350]
    * [cite_start]Implementación de capas de ingesta usando el Patrón Factory[cite: 352].
* [cite_start][ ] **Fase 2: Transformación Analítica, Fusión Numérica y Perfilado** [cite: 354]
    * [cite_start]Carga perezosa con Polars y ejecución de joins temporales[cite: 355].
    * [cite_start]Aplicación del Patrón Strategy para la purga heurística y manejo de anomalías[cite: 357].
* [cite_start][ ] **Fase 3: Integración Transaccional Resiliente y Despliegue de Observabilidad** [cite: 359]
    * [cite_start]Implementación de JSON Structured Logging integrado con Google Cloud Logging[cite: 346].
    * [cite_start]Ejecución atómica e idempotente del BigQuery Load Job[cite: 360].
* [cite_start][ ] **Fase 4: Contenedorización Final, Despliegue API Serverless y Servicio de Consulta** [cite: 361]
    * [cite_start]Desarrollo de la API con FastAPI y Pydantic[cite: 362].
    * [cite_start]Despliegue final de la imagen multi-stage en Google Cloud Run[cite: 364, 365].
