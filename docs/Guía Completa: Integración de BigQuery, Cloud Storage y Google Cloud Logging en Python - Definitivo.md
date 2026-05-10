# Guía Completa: Integración de BigQuery, Cloud Storage y Google Cloud Logging en Python
**(De Desarrollo a Producción)**

## Introducción 

Dado que este proyecto de Energía Solar es robusto y sigue una **Arquitectura de Capas (Clean Architecture)**, los roles deben ser más específicos para cubrir no solo BigQuery, sino también Cloud Storage y el manejo de logs# ETL Solar Serverless - Procesamiento del Dataset PVOD ☀️

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

* [x] **Fase 0: Setup Inicial & Preprocesamiento Off-line**
    * Definición del Product Requirements Document (PRD).
    * Configuración del repositorio, `.gitignore` y variables de entorno base.
    * **Preprocesamiento Off-line:** Creación del script `scripts/consolidate_pvod.py` con Polars para consolidar los 10 CSVs del dataset PVOD en un único archivo maestro `data/pvod.csv`, validando sus 271,968 registros e incluyendo la columna `station_id` para el clustering en BigQuery.
* [ ] **Fase 1: Aprovisionamiento de Infraestructura, Seguridad y Componentes de Ingesta**
    * [x] **Fase 1.0 (Entorno de Desarrollo):** Configuración de la Cuenta de Servicio en Google Cloud con roles estrictos (BigQuery Editor/User, Storage Creator, Logging Writer) y obtención de las credenciales base para `.env.example` (`GCP_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`).
    * [x] **Fase 1.1 (BigQuery):** Creación del Dataset en BigQuery (`solar_etl_dataset`) y definición de la tabla destino (`pvod_metrics`).
    * [x] **Fase 1.2 (Cloud Storage):** Creación y configuración del GCS Bucket (Capa Oro) multiregional (`GCS_BUCKET_NAME`).
    * [ ] Implementación de capas de ingesta usando el Patrón Factory.

Después de la configuración de entorno del proyecto, sigue las configuraciones necesarias para obtener las credenciales que usaremos para los servicios de Google Cloud Platform. Estas son:

1.  **GCP_PROJECT_ID**: Se puede ver al crear el proyecto que usaremos para obtener las credenciales de la cuenta de servicio. Para ello vamos a [console.cloud.google.com/welcome/](https://console.cloud.google.com/welcome/) y al lado del logo de Google Cloud creamos nuestro proyecto, lo seleccionamos y ahí mismo en la ruta welcome aparecerá. Este proyecto será usado en la Fase 1.0.
2.  **GOOGLE_APPLICATION_CREDENTIALS**: `credentials.json` que se obtiene en la Fase 1.0.
3.  **BQ_DATASET_ID**: `serverless_solar_etl_dataset` (confirmado en ubicación US). Se explica cómo sacar en la Fase 1.1.
4.  **BQ_TABLE_ID**: `pvod_metrics` (se creará por código, se explica en Fase 1.1).
5.  **GCS_BUCKET_NAME**: se explica cómo crear bucket en la Fase 1.3 (también en US).

## ¿Por qué usaremos esta combinación de servicios de Google, BigQuery, Cloud Storage y Google Cloud Logging?

Es importante notar que este proyecto no busca producir el pronóstico en sí mismo, sino la **infraestructura crítica** que lo hará posible[cite: 82].

* **La Entrada:** Son los datos crudos del dataset PVOD (irradiancia, temperatura, potencia local de 10 estaciones) capturados cada 15 minutos[cite: 83].
* **El Proceso:** El sistema limpia anomalías (como errores de sensores), realiza "Joins" para alinear variables climáticas y de potencia, y asegura que la data sea físicamente coherente (reglas de negocio)[cite: 84].
* **La Salida (El Producto):**
    * **Data Warehouse Refinado:** Una base de datos en BigQuery con datos "limpios y listos para ML", particionados y organizados para consultas rápidas[cite: 86].
    * **API de Métricas:** Un servicio que expone KPIs (como el Performance Ratio) y promedios de generación[cite: 88].

> **¿Se busca hacer un pronóstico?** La salida de este proyecto es el insumo perfecto para que un modelo de Machine Learning pueda realizar pronósticos intra-horarios precisos, pero no son pronósticos en sí[cite: 89]. En el mundo real, los Data Scientists pierden el 80% de su tiempo limpiando datos; este proyecto automatiza ese 80% para que el pronóstico sea trivial de implementar después[cite: 90, 91].

Básicamente, se está construyendo la **refinería** que convierte el "petróleo crudo" (dataset PVOD) en "gasolina de alto octanaje" (datos limpios en BigQuery) para que cualquier motor de Inteligencia Artificial pueda correr sobre ellos y realizar pronósticos, pero esto se hará después[cite: 92].

### El Rol de cada Servicio en nuestra "Refinería" de Datos:
Básicamente, estamos construyendo una refinería automatizada, donde cada servicio de Google Cloud cumple una función vital en la cadena de suministro, en este orden:

1.  **Google Cloud Storage (El Depósito de Seguridad):** Actúa como nuestra **Capa Oro (Gold Layer)**[cite: 109, 110]. Antes de que los datos lleguen al consumidor final, se almacenan aquí en formato **Apache Parquet**[cite: 111]. Este bucket sirve como un "buffer" de alta durabilidad que nos permite persistir los datos ya procesados y optimizados, garantizando que siempre tengamos un respaldo inmutable y eficiente antes de la carga final.
2.  **Google BigQuery (La Planta de Distribución):** Es nuestro **Data Warehouse**[cite: 106]. Su rol es transformar los archivos masivos en tablas analíticas estructuradas, particionadas y listas para ser consultadas[cite: 133]. Es aquí donde la "gasolina de alto octanaje" queda disponible para que los motores de IA realicen pronósticos en milisegundos.
3.  **Google Cloud Logging (La Torre de Control):** Es el encargado de la **Observabilidad**. Su rol es registrar cada evento, error o métrica de rendimiento del sistema en tiempo real[cite: 112]. Gracias al uso de **Structured Logging**, esta torre de control nos permite auditar el comportamiento del pipeline, detectar fallas de sensores en el dataset PVOD y asegurar que la refinería opere sin interrupciones[cite: 113, 114].

**En resumen:** Cloud Storage resguarda el producto semi-terminado, BigQuery lo entrega listo para el análisis y Cloud Logging vigila que todo el proceso sea seguro y eficiente. Esta infraestructura automatiza el 80% del trabajo de limpieza que suele detener rutinariamente trabajos con datos.

---

## Fase 1.0: Entorno de Desarrollo (Configuración Básica y Conectividad)

Para lograr que tu script de Python lea los datos inicialmente, se debe crear una cuenta de servicio en lugar de usar un correo personal[cite: 94]. Los pasos fundamentales en la consola de Google Cloud son:

### 1. Creación de la Cuenta de Servicio (El "Usuario" para Python)
Primero, se debe seleccionar el proyecto (ej. tech4apps) en Google Cloud[cite: 96]. Desde el menú de navegación (las 3 rayas en la parte superior izquierda), se debe acceder a **IAM y administración > Cuentas de servicio**[cite: 97].
* Haz clic en **+ CREAR CUENTA DE SERVICIO**[cite: 98].
* Asigna un nombre (ej. `lector-bigquery-python`) y haz clic en **CREAR Y CONTINUAR**[cite: 99].

### 2. Roles Requeridos para el Proyecto Solar ETL
Para que tu pipeline funcione de punta a punta, debes asignar exactamente estos roles a tu cuenta de servicio en la consola de IAM[cite: 100]:

* **Editor de datos de BigQuery** (`roles/bigquery.dataEditor`): A diferencia de tu proyecto anterior donde solo leías, aquí el ETL debe escribir los datos procesados del PVOD en las tablas[cite: 101, 104]. Este rol permite insertar filas y crear tablas si no existen[cite: 105].
* **Usuario de BigQuery** (`roles/bigquery.jobUser`): Es el permiso fundamental para que Python pueda "ejecutar" cualquier trabajo (Load Job o Query) en BigQuery[cite: 106, 107]. Sin este rol, no podrás realizar la carga atómica e idempotente que exige el PRD[cite: 108].
* **Creador de objetos de Storage** (`roles/storage.objectCreator`): Tu arquitectura usa Cloud Storage como un Buffer (Capa Oro)[cite: 109, 110]. Tu script necesita permiso para subir los archivos `.parquet` generados por Polars antes de que BigQuery los absorba[cite: 111].
* **Escritor de logs** (`roles/logging.logWriter`): El PRD exige JSON Structured Logging integrado con Google Cloud Logging[cite: 112, 113]. Este rol permite que tu código envíe esos logs estructurados directamente a la consola de Google para su monitoreo[cite: 114].

### 3. Generación del archivo `google-cloud-key.json`
* Selecciona la cuenta recién creada y ve a la pestaña **CLAVES**[cite: 117].
* Haz clic en **AGREGAR CLAVE > Crear clave nueva**, selecciona el formato **JSON** y haz clic en **CREAR**[cite: 118].
* Guarda el archivo descargado en tu carpeta `credentials/`[cite: 119].

---

## Fase 1.1: Dataset y tabla en BigQuery

El siguiente paso es configurar tu infraestructura de datos directamente en la consola de Google BigQuery[cite: 121]. En el mundo de los datos, un **Dataset** es el contenedor lógico (como una carpeta) y la **Table** es donde vive la data estructurada[cite: 122].

### 1. Crear el Dataset en BigQuery
1.  En la consola de GCP, busca **BigQuery** en la barra superior[cite: 125].
2.  En el panel "Explorador", haz clic en los tres puntos junto al ID de tu proyecto y selecciona **"Crear conjunto de datos"** (Create dataset)[cite: 126].
3.  **ID del conjunto de datos:** Escribe `solar_etl_dataset`. Este es el valor para tu variable `BQ_DATASET_ID`[cite: 127].
4.  **Ubicación de los datos:** Selecciona una región (ej. `us-central1`)[cite: 128]. **Importante:** Tu Bucket de Cloud Storage debe estar en la misma región para evitar costos de transferencia y latencia[cite: 129].
5.  Haz clic en **Crear**[cite: 130].

### 2. Definir la Tabla
Para la tabla `pvod_metrics`, seguiremos esta opción:
* **Opción A (Recomendada):** No la crees manualmente[cite: 132, 133]. En la Fase 3 de tu PRD, programaremos el `BigQueryAdapter` para que cree la tabla automáticamente con el esquema correcto (incluyendo particionamiento y clustering) la primera vez que el ETL corra[cite: 133]. Solo asegúrate de poner `pvod_metrics` en tu `.env`[cite: 134].

---

## Fase 1.2: Configuración de Google Cloud Storage

### Pasos para crear tu GCS Bucket (Capa Oro)
Sigue esta lista para obtener tu `GCS_BUCKET_NAME` correctamente[cite: 137]:
1.  Busca **Cloud Storage** en la barra superior de la consola de GCP y entra en **Buckets**[cite: 138].
2.  Haz clic en el botón **+ CREAR**[cite: 139].
3.  **Dale un nombre al bucket:** Debe ser único globalmente (ej: `serverless-solar-etl-gold-n0mercy95`)[cite: 140, 141]. Copia este nombre en tu `.env`.
4.  **Elegir dónde almacenar los datos:** Selecciona **Multi-región**[cite: 142, 144]. En el desplegable, asegúrate de que diga **US** (varias regiones en Estados Unidos)[cite: 145]. Esto lo alinea con tu dataset de BigQuery, evitando costos[cite: 146].
5.  **Clase de almacenamiento:** Selecciona **Standard** (la mejor para datos que se procesan frecuentemente)[cite: 147].
6.  **Control de acceso:** Deja marcada la opción **"Uniforme"** (más sencilla de gestionar con IAM)[cite: 148].
7.  **Protección de datos:** Puedes dejarlo por defecto y haz clic en **CREAR**[cite: 149].

---

## Fase 2: Entorno de Producción (Gobernanza, Seguridad y Control de Costos)

Se reestructura la configuración inicial mediante cinco estrategias avanzadas obligatorias[cite: 151]:

### 1. Uso de Identidades Nativas (Cloud Run) en lugar de Claves JSON
Dado que el proyecto se desplegará en Google Cloud Run, no utilizaremos archivos JSON, sino la identidad predeterminada del servicio[cite: 153, 154]. Esto elimina el riesgo de "fuga de credenciales" y pasa de una seguridad basada en "lo que tengo" (archivo) a una basada en "donde estoy" (entorno seguro)[cite: 155, 157].

### 2. Segmentación de Permisos por Recurso (IAM Granular)
Aplicar el **Principio de Mínimo Privilegio**[cite: 159]. En lugar de roles a nivel de proyecto, se asignan únicamente sobre el dataset `solar_etl_dataset` y el bucket `pvod-gold-layer`[cite: 161, 162]. Esto reduce el "radio de explosión" ante fallos o vulnerabilidades[cite: 163].

### 3. Optimización de Carga Atómica e Idempotencia
Usamos BigQuery Load Jobs con configuración `WRITE_TRUNCATE` o `WRITE_APPEND` basada en particiones temporales[cite: 165]. Dado que el dataset PVOD es una serie temporal, el pipeline debe ser **idempotente**: el resultado debe ser el mismo sin duplicados al ejecutarlo dos veces para la misma fecha, lo cual se logra particionando por la columna `timestamp`[cite: 167, 168].

### 4. Gestión de Secretos y Configuración Inmutable
**Secret Manager** es el baúl cifrado donde guardaremos variables sensibles (URLs externas o tokens API)[cite: 171]. Las variables del `.env` se inyectan en Cloud Run y las credenciales externas se extraen dinámicamente[cite: 172, 173]. Esto evita exponer datos sensibles en logs o Git (estándar **12-Factor App**)[cite: 174].

### 5. Ingeniería de Costos y Eficiencia de Consultas (Modelo Columnar)
BigQuery cobra por bytes procesados[cite: 176]. 
* **Prohibir el SELECT *:** Las consultas deben pedir columnas específicas[cite: 177].
* **Particionamiento y Clustering:** Organizamos por `station_id` (Clustering) y `date` (Partitioning), reduciendo el costo de consulta hasta en un 90%[cite: 178, 179].
* **Dry Runs Obligatorios:** Implementamos simulaciones; si una consulta supera un umbral de GB predefinido, el sistema aborta la operación[cite: 180, 181].

## Conclusión

Migrar de un script con `credentials.json` local a una infraestructura en **Cloud Run**, con particionamiento en **BigQuery** y validación de costos por **Dry Run**, transforma este proyecto en una plataforma de datos resiliente, diseñada para los rigurosos estándares de la industria energética actual[cite: 183].