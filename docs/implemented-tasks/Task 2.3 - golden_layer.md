# Fase 2.3 — Volcado Parquet Comprimido a GCS (Capa Oro)

## Contexto

La Tarea 2.2 entrega un `pl.DataFrame` limpio (sin nulls, sin outliers, irradiancia nocturna en cero). La Tarea 2.3 del PRD exige:

> *Aplicación estricta de Data Types de Polars y volcado final binario altamente comprimido en Apache Parquet a GCS (Capa Oro).*

PRD §4 complementa:
> *Exportar de Polars obligatoriamente a formato Apache Parquet (con compresión RLE y diccionarios) antes de realizar el Load Job masivo a BigQuery.*

## Proposed Changes

### Capa Domain — Constantes de Exportación

#### [MODIFY] [constants.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/domain/constants.py)

Agregar esquema final de tipos Polars y configuración Parquet:

```python
# Esquema estricto final para el export a Parquet
PVOD_FINAL_SCHEMA: dict[str, pl.DataType] = {
    "date_time": pl.Datetime,
    "station_id": pl.UInt8,
    "nwp_*": pl.Float64,       # 7 columnas NWP
    "lmd_*": pl.Float64,       # 6 columnas LMD
    "power": pl.Float64,
    "delta_*": pl.Float64,     # 4 columnas delta
}

PARQUET_COMPRESSION: str = "zstd"
GCS_GOLD_PREFIX: str = "gold/"
```

---

### Capa Application — Puerto de Exportación

#### [NEW] [gold_layer_port.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/gold_layer_port.py)

Puerto abstracto para la exportación a la capa Gold:

```python
class GoldLayerExportPort(ABC):
    @abstractmethod
    def export_to_gold_layer(self, dataframe: pl.DataFrame) -> str:
        """Exporta el DataFrame a Parquet y lo sube a la capa Gold.
        Returns: URI del objeto en GCS (gs://bucket/path)."""
        ...
```

---

### Capa Infrastructure — Exportador GCS + Parquet

#### [NEW] [gcs_parquet_exporter.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/gcs_parquet_exporter.py)

Implementación concreta `GCSParquetExporter(GoldLayerExportPort)`:

1. **Enforcement de tipos finales**: Cast de cada columna al tipo exacto del esquema (`Float64`, `UInt8`, `Datetime`)
2. **Serialización Parquet**: `df.write_parquet()` con `compression="zstd"` y `use_pyarrow=True` (habilita RLE + dictionary encoding automático por PyArrow)
3. **Upload a GCS**: Usa `google.cloud.storage.Client` para subir el archivo Parquet al bucket configurado
4. **Naming**: `gold/pvod_{YYYYMMDD_HHMMSS}.parquet`
5. **Retorna**: URI completa `gs://bucket/gold/pvod_*.parquet`

```
Flujo:
pl.DataFrame (limpio)
  → enforce_final_schema()        ← Tipos estrictos
  → write_parquet(tempfile, zstd) ← Serialización binaria
  → upload_to_gcs(bucket, blob)   ← Cloud Storage
  → return "gs://bucket/gold/pvod_*.parquet"
```

---

### Resumen de Archivos

| Acción | Archivo | Capa |
|:--|:--|:--|
| MODIFY | `domain/constants.py` | Domain |
| NEW | `application/gold_layer_port.py` | Application |
| NEW | `infrastructure/gcs_parquet_exporter.py` | Infrastructure |

**Total: 3 archivos** (1 modificado + 2 nuevos)

## Verification Plan

### Automated Tests

1. **Test de serialización Parquet**: Crear DataFrame sintético, exportar a Parquet local (sin GCS), verificar que se pueda re-leer con tipos correctos
2. **Test de enforcement de schema**: Verificar que columnas mal tipadas se castean correctamente
3. **Test de naming**: Verificar formato del blob name generado

> [!NOTE]
> El test de upload real a GCS requiere credenciales activas. Se verificará la lógica de serialización localmente y el upload se validará cuando se ejecute el pipeline completo.

Viewed .env:1-19

### Notas Adicionales

## 1. ¿Qué es Parquet?

Imagina que tienes un CSV con 271,968 filas y 20 columnas. En CSV, los datos se guardan **por fila**:

```
# CSV (orientado a filas) — como una planilla Excel
fecha,irrad,temp,power
2018-07-01,800,32,120
2018-07-01,750,31,110
...271,966 filas más...
```

**Parquet** invierte eso. Guarda los datos **por columna**:

```
# Parquet (orientado a columnas)
columna "irrad":  [800, 750, 600, 800, 750, 600, ...]   ← toda junta
columna "temp":   [32, 31, 28, 32, 31, 28, ...]         ← toda junta
columna "power":  [120, 110, 90, 120, 110, 90, ...]     ← toda junta
```

### ¿Por qué importa esto?

Cuando BigQuery necesita calcular `SELECT AVG(power) FROM pvod`:
- **CSV**: Tiene que leer TODAS las filas enteras (800 + 32 + 120, 750 + 31 + 110...) para extraer solo la columna `power`. Lee datos innecesarios.
- **Parquet**: Lee SOLO la columna `power` [120, 110, 90...]. Ignora las demás. **Mucho más rápido y barato.**

### ¿Y la compresión ("zstd")?

Como los datos de una columna son del mismo tipo (ej. todos Float64), se repiten patrones. Parquet aplica:
- **RLE (Run-Length Encoding)**: `[0, 0, 0, 0, 0]` → `"5 ceros"` (irradiancia nocturna)
- **Dictionary Encoding**: `[station_0, station_0, station_1]` → `{0: "station_0", 1: "station_1"}` + `[0, 0, 1]`
- **Zstandard**: Compresión adicional sobre todo lo anterior

Resultado: tu CSV de ~40 MB se convierte en un Parquet de ~**5-8 MB** — y se lee más rápido.

## 2. ¿Por qué no subir el CSV directamente a BigQuery?

| | CSV | Parquet |
|:--|:--|:--|
| Tamaño | ~40 MB | ~5-8 MB |
| Tipos de datos | Todo es texto ("32.0") | Tipado nativo (Float64, UInt8, Datetime) |
| BigQuery Load Job | Tiene que parsear/inferir tipos | Los lee directamente |
| Costo GCS | Más almacenamiento | Menos almacenamiento |
| Velocidad de carga | Lenta (parsing) | Rápida (binario nativo) |

BigQuery está optimizado internamente para formato columnar — **Parquet es su idioma nativo**.

## 3. ¿Cómo se sube a GCS? — Sí, mediante el bucket

El flujo concreto en nuestro código (`gcs_parquet_exporter.py`):

```
DataFrame limpio (en memoria RAM)
    │
    ▼ df.write_parquet(tempfile, compression="zstd")
Archivo .parquet en /tmp local
    │
    ▼ google.cloud.storage.Client → bucket.blob.upload_from_filename()
gs://serverless-solar-etl-gold-n0mercy95/gold/pvod_20260510_220000.parquet
```

1. **Polars escribe** el DataFrame a un archivo temporal `.parquet` en disco
2. **El cliente de GCS** (`google-cloud-storage`) lee ese archivo y lo sube al bucket que configuraste en tu `.env`:
   ```
   GCS_BUCKET_NAME=serverless-solar-etl-gold-n0mercy95
   ```
3. El archivo queda en la "carpeta virtual" `gold/` del bucket, con nombre `pvod_{timestamp}.parquet`
4. En la **Fase 3**, BigQuery leerá ese Parquet directamente desde el bucket para hacer el Load Job

El bucket actúa como el **intermediario** (la "Capa Oro") entre tu pipeline de limpieza y BigQuery. Es como dejar el paquete en un locker antes de que el destinatario lo recoja.