# Fase 2.1 — Carga Perezosa y Joins Temporales NWP ↔ LMD

## Contexto

La Fase 1 implementó la ingesta (Factory Pattern) que descarga el CSV consolidado PVOD a un `io.BytesIO`. La Tarea 2.1 del PRD exige:

> *Carga perezosa (lazy query vía `scan_csv`) en entorno Polars. Ejecución de Joins temporales alineados cada 15 minutos exactos para cruzar matrices LMD y NWP.*

El dataset PVOD consolidado (`pvod.csv`, 271,968 registros) ya contiene ambas matrices (NWP y LMD) como columnas dentro de cada fila, junto con `station_id` y `date_time`. **No son datasets separados** que requieran un join externo — las columnas NWP y LMD coexisten en el mismo CSV, alineadas por timestamp.

### Estructura del CSV PVOD (15 columnas + station_id)

| Columna | Categoría | Descripción |
|:--|:--|:--|
| `date_time` | Temporal | Timestamp (YYYY-MM-DD HH:MM) |
| `nwp_globalirrad` | NWP | Irradiancia Global (W/m²) |
| `nwp_directirrad` | NWP | Irradiancia Directa (W/m²) |
| `nwp_temperature` | NWP | Temperatura (°C) |
| `nwp_humidity` | NWP | Humedad Relativa (%) |
| `nwp_windspeed` | NWP | Velocidad del Viento (m/s) |
| `nwp_winddirection` | NWP | Dirección del Viento (°) |
| `nwp_pressure` | NWP | Presión Atmosférica (hPa) |
| `lmd_totalirrad` | LMD | Irradiancia Global (W/m²) |
| `lmd_diffuseirrad` | LMD | Irradiancia Difusa (W/m²) |
| `lmd_temperature` | LMD | Temperatura (°C) |
| `lmd_pressure` | LMD | Presión Atmosférica (hPa) |
| `lmd_winddirection` | LMD | Dirección del Viento (°) |
| `lmd_windspeed` | LMD | Velocidad del Viento (m/s) |
| `power` | LMD | Salida de Potencia (kW) |
| `station_id` | Metadata | ID de estación (0–9, inyectado en consolidación) |

## User Review Required

> [!IMPORTANT]
> **Interpretación de "Joins temporales NWP ↔ LMD"**: Dado que NWP y LMD coexisten en el mismo CSV (misma fila = mismo timestamp), el "join temporal" del PRD se interpreta como:
> 1. **Carga lazy** del CSV con `pl.scan_csv()` (no `read_csv`)
> 2. **Parsing y normalización** del campo `date_time` a `Datetime` con truncamiento exacto a 15 minutos
> 3. **Validación de integridad temporal**: verificar que no existan gaps ni duplicados en la grilla de 15 min por estación
> 4. **Creación de vistas analíticas NWP/LMD**: separar lógicamente las matrices para facilitar correlaciones posteriores (columnas calculadas de desviación NWP vs LMD)
>
> Si tu intención es diferente (ej. unir datasets de archivos separados), por favor indícamelo.

## Open Questions

> [!NOTE]
> **Columnas de diferencia NWP-LMD**: ¿Quieres que se generen columnas de **desviación** (delta) entre las mediciones NWP y LMD para variables compartidas (irradiancia, temperatura, presión, viento)? Esto facilita el análisis de error del modelo NWP. Ejemplo: `delta_irrad = nwp_globalirrad - lmd_totalirrad`. Lo incluyo en el plan como columnas calculadas opcionales.

## Proposed Changes

### Capa Domain — Excepciones de Transformación

#### [MODIFY] [exceptions.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/domain/exceptions.py)

Agregar excepciones específicas para la fase de transformación:

```python
class DataTransformationError(SolarETLError):
    """Fallo genérico durante la transformación de datos."""

class TemporalAlignmentError(DataTransformationError):
    """Las marcas de tiempo no cumplen la grilla de 15 minutos."""

class IrradianceOutOfBoundsError(DataTransformationError):
    """La irradiancia global excede la constante solar extraterrestre
    o es negativa (restricción física del PRD §4)."""
```

---

### Capa Application — Puerto de Transformación y Servicio de Carga Lazy

#### [NEW] [transformation_ports.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/transformation_ports.py)

Puerto abstracto `PVODTransformationPipeline(ABC)` con el contrato que la Tarea 2.2 (Strategy Pattern) necesitará consumir. Define el método:
- `load_and_align(buffer: io.BytesIO) → pl.LazyFrame`: Carga lazy y alineamiento temporal

```python
class PVODTransformationPipeline(ABC):
    @abstractmethod
    def load_and_align(self, buffer: io.BytesIO) -> pl.LazyFrame:
        """Carga el CSV desde un buffer en modo lazy y ejecuta
        el alineamiento temporal a la grilla de 15 min."""
        ...
```

---

### Capa Infrastructure — Servicio Concreto de Carga y Alineamiento

#### [NEW] [pvod_lazy_loader.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/pvod_lazy_loader.py)

Implementación concreta `PVODLazyLoader(PVODTransformationPipeline)`:

**Responsabilidades:**

1. **Carga Lazy via `scan_csv`**: Polars requiere un path para `scan_csv` (no acepta buffers). El servicio escribe el buffer a un archivo temporal (`tempfile.NamedTemporaryFile`), luego ejecuta `pl.scan_csv()` para obtener un `LazyFrame`. 

2. **Parsing temporal**: Cast de `date_time` de `Utf8` a `pl.Datetime` con `strptime`, luego truncamiento a 15 minutos via `.dt.truncate("15m")`.

3. **Tipado estricto de columnas**: Cast explícito de todas las columnas numéricas a `Float64` y `station_id` a `UInt8` según el esquema del dataset.

4. **Validaciones de integridad temporal** (ejecutadas vía `.collect()` parcial):
   - Verificar que no existan timestamps duplicados por estación (`group_by + count > 1`)
   - Verificar que la frecuencia sea exactamente 15 min (sin gaps) por estación
   - Verificar restricción física: irradiancia ≥ 0 y ≤ constante solar (~1361 W/m²)

5. **Columnas analíticas calculadas** (deltas NWP vs LMD):
   - `delta_globalirrad` = `nwp_globalirrad - lmd_totalirrad`
   - `delta_temperature` = `nwp_temperature - lmd_temperature`
   - `delta_pressure` = `nwp_pressure - lmd_pressure`
   - `delta_windspeed` = `nwp_windspeed - lmd_windspeed`

6. **Retorno**: `pl.LazyFrame` optimizado con todas las transformaciones declaradas como operaciones lazy (serán ejecutadas por Polars en un solo plan optimizado cuando se haga `.collect()` downstream).

```
Flujo:
buffer (io.BytesIO)
  → tempfile (disco)
    → pl.scan_csv() → LazyFrame
      → .with_columns(parse datetime, truncate 15m)
      → .with_columns(cast tipos estrictos)
      → .with_columns(columnas delta NWP-LMD)
      → validaciones de integridad (collect parcial)
      → return LazyFrame
```

---

### Capa Domain — Constantes Físicas

#### [NEW] [constants.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/domain/constants.py)

Constantes del dominio solar utilizadas en validaciones:

```python
SOLAR_CONSTANT_W_M2: float = 1361.0  # Constante solar extraterrestre (TSI)
SAMPLING_INTERVAL_MINUTES: int = 15   # Intervalo de muestreo del PVOD
NUM_STATIONS: int = 10                # Estaciones fotovoltaicas
EXPECTED_RECORDS: int = 271_968       # Registros totales esperados

# Columnas del dataset PVOD
NWP_COLUMNS: list[str] = [
    "nwp_globalirrad", "nwp_directirrad", "nwp_temperature",
    "nwp_humidity", "nwp_windspeed", "nwp_winddirection", "nwp_pressure",
]
LMD_COLUMNS: list[str] = [
    "lmd_totalirrad", "lmd_diffuseirrad", "lmd_temperature",
    "lmd_pressure", "lmd_winddirection", "lmd_windspeed",
]
TARGET_COLUMN: str = "power"
TEMPORAL_COLUMN: str = "date_time"
STATION_COLUMN: str = "station_id"
```

---

### Resumen de Archivos

| Acción | Archivo | Capa |
|:--|:--|:--|
| MODIFY | `domain/exceptions.py` | Domain |
| NEW | `domain/constants.py` | Domain |
| NEW | `application/transformation_ports.py` | Application |
| NEW | `infrastructure/pvod_lazy_loader.py` | Infrastructure |

## Verification Plan

### Automated Tests

1. **Test unitario con CSV sintético**: Crear un CSV mínimo (ej. 2 estaciones × 10 timestamps) para verificar:
   - Parsing correcto de `date_time` a `Datetime`
   - Truncamiento a 15 min exactos
   - Cálculo correcto de deltas NWP-LMD
   - Detección de duplicados temporales
   - Rechazo de irradiancia negativa (`IrradianceOutOfBoundsError`)

2. **Test de integración con `pvod.csv` real** (si está disponible localmente):
   ```bash
   python -c "
   from app.infrastructure.pvod_lazy_loader import PVODLazyLoader
   import io, polars as pl
   loader = PVODLazyLoader()
   with open('data/pvod.csv', 'rb') as f:
       buf = io.BytesIO(f.read())
   lf = loader.load_and_align(buf)
   print(lf.collect().describe())
   "
   ```

### Manual Verification

- Revisión de tipos del `LazyFrame` schema (`lf.schema`)
- Confirmar que el plan de ejecución de Polars (`lf.explain()`) es óptimo y no fuerza materialización innecesaria

### Resumen

**En resumen:** No unimos dos tablas. Forzamos a que las columnas de dos orígenes distintos (NWP y LMD) que comparten una fila se anclen a un reloj perfecto de 15 minutos -osea, se hace un Join temporal-, y calculamos su diferencia geométrica para calcular el margen de error del modelo predictivo que usaron frente a lo real captado por los sensores.