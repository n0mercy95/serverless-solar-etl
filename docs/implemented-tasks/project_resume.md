# Resumen del Proyecto: PVOD Serverless ETL & API

Este documento sintetiza los logros, flujos de datos y arquitectura alcanzados en el proyecto **Serverless Solar ETL** al ejecutar las rutas principales de la API (`/run` y `/aggregate`). Se detallan las transformaciones físicas de los datos, la generación de reportes/gráficos y la infraestructura utilizada en Google Cloud Platform (GCP).

---

## 1. Ruta de Ingesta y ETL (`/api/v1/etl/run`)

Esta ruta es el motor de procesamiento de datos. Se encarga de extraer los datos crudos de origen (PVOD), limpiarlos con rigor físico y cargarlos en un Data Warehouse.

### Extracción de Datos
El pipeline utiliza un **Patrón Factory** para la descarga resiliente de los datos crudos consolidados (~272,000 registros):
*   **Fuente Primaria**: Se descargan directamente en memoria (mediante un buffer binario temporal `io.BytesIO`) desde un repositorio público en **GitHub Raw** (`raw.githubusercontent.com`).
*   **Fuente de Contingencia**: En caso de fallo en GitHub, el sistema cuenta con un extractor de fallback hacia **ScienceDB** (`scidb.cn`).

### Limpieza y Transformación de Datos (Data Cleaning)
Al ejecutar el ETL, el pipeline utiliza **Polars** de manera perezosa (Lazy) para aplicar un flujo de limpieza secuencial sobre los datos extraídos en memoria:
1. **NighttimeZeroingStrategy**: Se fuerza a cero absoluto la irradiancia y producción nocturna para definir la forma física correcta del ciclo diurno.
2. **ThermodynamicBoundsStrategy (Límites Termodinámicos)**: Filtra e invalida (asigna `null`) registros que violan las leyes físicas y geográficas terrestres absolutas. Controla la humedad (`nwp_humidity` acotada estrictamente entre 0 y 100%), la dirección del viento (`nwp_winddirection` y `lmd_winddirection` entre 0° y 360°), y la presión atmosférica (`nwp_pressure` y `lmd_pressure` acotadas a rangos geográficos realistas de Hebei [800, 1100] hPa, marcando fallos severos si registran 0).
3. **IrradianceConsistencyStrategy (Consistencia Física Solar)**: Aplica la regla física de que la irradiancia difusa local (`lmd_diffuseirrad`) jamás puede superar a la irradiancia global local (`lmd_totalirrad`). Si se detecta una violación, se asume suciedad o sombra en el piranómetro y se invalida la medición con `null`.
4. **IrradianceOutlierStrategy (Filtro de Desviación NWP vs LMD)**: Se analizan las desviaciones severas entre la predicción meteorológica (NWP) y la medición local (LMD). Si el ratio NWP/LMD cae fuera de un umbral físico aceptable [0.3, 3.0] para lecturas significativas (> 50 W/m²), se descartan como anomalías (outliers) fijándolos en `null`.
5. **HampelFilterStrategy**: Se eliminan picos atípicos o ruido transitorio en mediciones puntuales como la velocidad del viento (`nwp_windspeed` y `lmd_windspeed`) mediante el uso de la mediana móvil y el MAD (Median Absolute Deviation) en una ventana de tamaño 5.
6. **ThermalDeltaStrategy (Validación Cruzada Térmica)**: Compara la temperatura predicha por el modelo (`nwp_temperature`) con la medida localmente por el sensor (`lmd_temperature`). Si la diferencia absoluta supera un límite razonable ($\Delta T > 15^\circ\text{C}$), se asume un cortocircuito o sobrecalentamiento del sensor por mal aislamiento térmico, invalidando la lectura con `null`.
7. **MissingValueImputerStrategy**: Todos los valores nulos (originales y los generados intencionalmente por las estrategias anteriores) son imputados usando interpolación lineal continua calculada de forma independiente para cada estación (`station_id`).
8. **Corrección de Límites**: Acota (clipping) la irradiancia medida al límite físico absoluto dado por la constante solar extraterrestre (TSI ≈ ~1361 W/m²).

### Exportación a la Capa Oro (Google Cloud Storage)
*   **Conversión a Parquet**: Una vez limpio, el conjunto de datos (~272,000 registros) adquiere un esquema de tipos estrictos y se serializa a **Apache Parquet**.
*   **Compresión**: Utilizando algoritmos columnares, Run-Length Encoding (RLE) y el compresor `zstd`, un archivo CSV original de ~40 MB se reduce a un binario ultracompacto de **5 a 8 MB**.
*   **Alojamiento**: Este archivo se sube automáticamente al bucket de **Google Cloud Storage** designado para la Capa Oro (Golden Layer), listo para ser consumido de manera eficiente.

### Carga en el Data Warehouse (Google BigQuery)
*   Se orquesta un Job de carga (Load Job) masivo y de alta velocidad que lee el archivo Parquet directamente desde Cloud Storage y lo vuelca a **BigQuery**.
*   La carga es idempotente y tolerante a fallos, asegurando la preservación del histórico (datos de 2018/2019) sin expiración accidental de particiones.

---

## 2. Ruta de Consultas Analíticas (`/api/v1/metrics/aggregate`)

Esta ruta permite el consumo de la Capa Oro procesada directamente desde BigQuery, resolviendo agregaciones analíticas (ej. promedio de potencia generada por estación solar en un rango de fechas) en milisegundos.

### Consulta Segura y Control de Costos (Free Tier)
Para asegurar que el proyecto se mantenga dentro de los límites de la capa gratuita de GCP:
*   **Límite Estricto de Datos**: Toda consulta tiene inyectada una cuota máxima obligatoria (ej. máximo 100 MB de bytes facturados por consulta `bq_max_bytes_billed`).
*   **Modo *Dry Run***: La ruta soporta simulaciones (`dry_run=true`) que permiten a los consumidores estimar el coste de su consulta (cuántos bytes leerá de la tabla columnar) antes de gastar cuota real.
*   **Parametrización**: Las peticiones evitan la inyección de SQL mapeando directamente fechas y parámetros estandarizados como tipos `TIMESTAMP` nativos de BigQuery.

---

## 3. Impacto en Gráficos y Observabilidad (Plots)

Gracias a las correcciones introducidas por el ETL (`/run`), el análisis exploratorio de datos y los reportes logran un avance significativo en precisión:

*   **Scatter Plots (Gráficos de Dispersión) de Irradiancia**: Antes de la limpieza avanzada, los puntos de dispersión que comparaban la predicción (NWP) vs medición (LMD) mostraban enormes discrepancias inalteradas. Con la implementación del *IrradianceOutlierStrategy*, la dispersión aberrante es eliminada e interpolada.
*   **Resultados de Calidad (Gold Layer)**: El gráfico resultante tras el ETL muestra los puntos agrupados de forma muy cohesionada alrededor de una línea recta de ratio 1:1, disminuyendo la desviación estándar en un **23%**. Esto garantiza que los modelos fotovoltaicos posteriores sean entrenados sobre datos limpios de "falsos positivos" meteorológicos.

---

## 4. Arquitectura de Despliegue y Alojamiento

Todo el sistema descrito opera de manera completamente Serverless (Sin servidores dedicados), minimizando la carga operativa.

1. **Docker & Artifact Registry**: La aplicación FastAPI es empaquetada en una imagen Docker ligera y versionada en Google Artifact Registry.
2. **Google Cloud Run**: 
    *   La API reside en Cloud Run.
    *   **Auto-escalado a Cero**: Cuando las rutas no reciben peticiones, Cloud Run reduce las instancias de cómputo a **0**, garantizando que no se incurra en gastos por inactividad.
    *   Escala automáticamente (ej. a 5 instancias) solo ante picos de demanda.
3. **Google Secret Manager**: Todas las variables críticas de entorno y conexiones son inyectadas en tiempo de ejecución desde el gestor de secretos, garantizando que ninguna credencial quede expuesta en las imágenes base o en el código fuente.
