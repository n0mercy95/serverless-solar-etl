# Fase 1.2 — Capas de Ingesta con Patrón Factory y Buffer de Descarga

## Contexto

La Tarea 1.2 del PRD exige implementar las capas de ingesta del CSV consolidado PVOD usando el **Patrón Factory** con dos fuentes:
- **Primaria:** GitHub Raw (`raw.githubusercontent.com`) — archivo `pvod.csv` ya consolidado (271,968 registros).
- **Contingencia:** ScienceDB (`scidb.cn`) — fallback HTTP directo.

El CSV descargado debe ir hacia un **buffer de memoria** o **GCS temporal**, según evaluación.

---

## User Review Required

### Buffer en Memoria (`io.BytesIO`) vs. GCS Temporal

> [!IMPORTANT]
> Esta es la decisión arquitectónica clave que necesita tu aprobación.

| Criterio | Buffer en memoria (`io.BytesIO`) | GCS Temporal (subida a bucket) |
|---|---|---|
| **Tamaño del CSV** | ~70-90 MB consolidado — cabe cómodamente en RAM de Cloud Run (256-512 MB) | Necesario si el archivo superara ~500 MB |
| **Latencia** | ✅ Cero latencia de red adicional — el CSV queda en RAM listo para Polars | ❌ Latencia adicional de subida + descarga al bucket |
| **Costo** | ✅ $0 — no hay operación de Storage | ❌ Costo marginal de escritura/lectura en GCS |
| **Resiliencia ante fallo** | ❌ Si el contenedor muere, se pierde el buffer y hay que re-descargar | ✅ El archivo persiste en GCS y se puede re-leer |
| **Complejidad** | ✅ Trivial — `io.BytesIO` nativo de Python | ❌ Requiere autenticación GCS, manejo de blobs, limpieza posterior |
| **Flujo del PRD** | El PRD dice *"buffer de memoria **o** GCS temporal"* — ambos son válidos | El GCS como Capa Oro se usa más adelante para el **Parquet** procesado (Fase 2.3) |
| **Alineamiento con Fase 2** | En Fase 2.3 el Parquet limpio **sí** va a GCS (Gold Layer) — ese es el uso real del bucket | Usar GCS aquí para el CSV *crudo* mezclaría datos raw con gold en el mismo bucket |

> [!TIP]
> **Recomendación: Buffer en memoria (`io.BytesIO`)** para la ingesta del CSV crudo. El archivo de ~80 MB cabe holgadamente en la RAM del contenedor Cloud Run. El bucket GCS queda reservado para su rol real: almacenar el Parquet procesado (Gold Layer) en la Fase 2.3. Esto es más limpio arquitectónicamente, más rápido, gratis, y respeta la separación entre datos crudos y refinados.

---

## Open Questions

> [!IMPORTANT]
> **URL de ScienceDB:** La investigación confirma que `scidb.cn` **no tiene API pública de descarga directa**. El dataset PVOD se descarga manualmente desde su portal web, o alternativamente desde el repo oficial de GitHub ([yaotc/PVODataset](https://github.com/yaotc/PVODataset)). Tu `.env` tiene `SCIDB_FALLBACK_URL=https://scidb.cn/api/v1/dataset/pvod.csv`, pero esa URL probablemente no funcione como endpoint real.
>
> **Opciones para el fallback:**
> 1. Usar el repo original de GitHub (`yaotc/PVODataset`) como fuente secundaria real.
> 2. Mantener la URL de scidb.cn como placeholder simbólico y confiar en el GitHub Raw de tu propio fork como fuente única real.
> 3. Dejar el `ScienceDBHttpExtractor` implementado pero con la lógica lista para recibir una URL válida cuando/si la consigues.
>
> Recomiendo la **opción 3**: implementamos el extractor completo, funcional, y si la URL falla en runtime, el Factory ya habrá intentado GitHub primero.

---

## Proposed Changes

La implementación sigue estrictamente la Clean Architecture del proyecto: contratos abstractos en la capa de **Application**, implementaciones concretas en **Infrastructure**, y el Factory como orquestador en **Application**.

### Capa de Dominio — Excepciones Custom

#### [NEW] [exceptions.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/domain/exceptions.py)

Jerarquía de errores específicos del ETL solar, según lo exigido por el PRD (evitar `except Exception as e`):

```python
class SolarETLError(Exception): ...          # Base
class DataExtractionError(SolarETLError): ... # Fallo de ingesta HTTP
class DataSourceUnavailableError(DataExtractionError): ... # Fuente no responde
class DataValidationError(SolarETLError): ... # CSV corrupto o vacío
```

---

### Capa de Application — Contratos Abstractos y Configuración

#### [NEW] [ports.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/ports.py)

Contrato abstracto `PVODExtractionPipeline(ABC)` con el método `extract_data_to_buffer() -> io.BytesIO`, tal cual lo exige el PRD.

```python
from abc import ABC, abstractmethod
import io

class PVODExtractionPipeline(ABC):
    @abstractmethod
    def extract_data_to_buffer(self) -> io.BytesIO:
        """Descarga el CSV PVOD y lo retorna como buffer binario en memoria."""
        ...
```

#### [NEW] [config.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/config.py)

Configuración centralizada con `pydantic-settings`, leyendo automáticamente del `.env`:

```python
class Settings(BaseSettings):
    # GCP
    gcp_project_id: str
    google_application_credentials: str
    # BigQuery
    bq_dataset_id: str
    bq_table_id: str
    # GCS
    gcs_bucket_name: str
    # Data Sources
    github_raw_url: HttpUrl
    scidb_fallback_url: HttpUrl
    # App
    environment: str = "development"
    log_level: str = "INFO"
```

#### [NEW] [extraction_factory.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/extraction_factory.py)

`ExtractionFactory` — evalúa las variables de entorno y devuelve dinámicamente el extractor apropiado. Implementa lógica de **fallback automático**: intenta GitHub primero, y si falla, cae a ScienceDB. Sin if/elif anidados (usa un registro de estrategias).

```python
class ExtractionFactory:
    def create_extractor(self, settings: Settings) -> PVODExtractionPipeline:
        """Retorna GitHubRawExtractor por defecto; ScienceDBHttpExtractor como fallback."""
```

---

### Capa de Infrastructure — Extractores Concretos

#### [NEW] [github_extractor.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/github_extractor.py)

`GitHubRawExtractor(PVODExtractionPipeline)` — descarga vía HTTP (`httpx`) el CSV desde `raw.githubusercontent.com`, usando streaming para no cargar todo el response en memoria de golpe. Retorna `io.BytesIO`.

- Usa `httpx.Client` con timeout configurable y streaming.
- Valida status code, content-length razonable y que el buffer no esté vacío.
- Lanza `DataSourceUnavailableError` si falla la conexión.
- Lanza `DataValidationError` si el contenido descargado está vacío o corrupto.

#### [NEW] [sciencedb_extractor.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/sciencedb_extractor.py)

`ScienceDBHttpExtractor(PVODExtractionPipeline)` — mismo contrato, misma lógica, diferente URL. Actúa como contingencia pura.

---

### Resumen de Archivos

```
src/app/
├── domain/
│   ├── __init__.py
│   └── exceptions.py              [NEW] — Jerarquía de excepciones
├── application/
│   ├── __init__.py
│   ├── ports.py                   [NEW] — Contrato abstracto PVODExtractionPipeline
│   ├── config.py                  [NEW] — Settings con pydantic-settings
│   └── extraction_factory.py      [NEW] — ExtractionFactory con fallback
├── infrastructure/
│   ├── __init__.py
│   ├── github_extractor.py        [NEW] — GitHubRawExtractor
│   └── sciencedb_extractor.py     [NEW] — ScienceDBHttpExtractor
└── main.py
```

---

## Verification Plan

### Automated Tests

1. **Script de integración manual** — ejecutar un script que instancie el Factory, descargue el CSV desde GitHub, y valide:
   - Que el buffer `io.BytesIO` no esté vacío.
   - Que Polars pueda hacer `pl.read_csv(buffer)` exitosamente.
   - Que el DataFrame resultante tenga 271,968 registros.
   - Que contenga la columna `station_id`.

2. **Test de fallback** — configurar `GITHUB_RAW_URL` con una URL inválida para forzar el fallback a ScienceDB y verificar que la jerarquía de excepciones funcione correctamente.

3. **Import check** — verificar que todos los módulos importan sin errores:
   ```bash
   python -c "from app.application.extraction_factory import ExtractionFactory; print('OK')"
   ```

### Manual Verification

- Revisión visual del logging durante la descarga (tamaño, tiempo, fuente usada).
- Confirmación de que el `.env` existente es compatible con la nueva `Settings` de pydantic.
