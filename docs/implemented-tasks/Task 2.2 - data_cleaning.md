# Fase 2.2 — Patrón Strategy: Purga Heurística de Datos Solares

## Contexto

La Tarea 2.1 entrega un `pl.LazyFrame` con timestamps alineados a 15 min, tipos estrictos, y columnas delta NWP-LMD. La Tarea 2.2 del PRD exige:

> *Aplicación estricta del Patrón Strategy para la purga heurística (Hampel Filter, Zeroing nocturno, Missing Value Imputing).*

PRD §3 define el contrato:
- **Interfaz**: `SolarDataCleaningStrategy(ABC)` con método `apply_cleaning(dataframe)`
- **3 implementaciones concretas**: `HampelFilterStrategy`, `NighttimeZeroingStrategy`, `MissingValueImputerStrategy`

### Datos de las Estaciones PVOD

Las 10 estaciones están en **Hebei, China** (Yao et al., Solar Energy 2021):
- Rango latitud: **36.64°N – 39.52°N**
- Rango longitud: **113.64°E – 117.46°E**
- Se usará una latitud representativa por defecto (~38°N) para el cálculo de elevación solar

## Proposed Changes

### Capa Domain — Constantes de Limpieza y Metadata de Estaciones

#### [MODIFY] [constants.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/domain/constants.py)

Agregar constantes para las 3 estrategias:

```python
# ── Parámetros del Hampel Filter ──────────────────────────────
HAMPEL_WINDOW_SIZE: int = 5          # Ventana móvil (registros)
HAMPEL_THRESHOLD: float = 3.0        # Umbral en MADs
WIND_SPEED_COLUMNS: tuple[str, ...] = ("nwp_windspeed", "lmd_windspeed")

# ── Parámetros del Nighttime Zeroing ──────────────────────────
DEFAULT_STATION_LATITUDE: float = 38.0    # ~centro Hebei
DEFAULT_STATION_LONGITUDE: float = 115.5  # ~centro Hebei
NIGHTTIME_ZEROING_COLUMNS: tuple[str, ...] = (
    "nwp_globalirrad", "nwp_directirrad",
    "lmd_totalirrad", "lmd_diffuseirrad", "power",
)

# ── Columnas para imputación de valores faltantes ─────────────
IMPUTATION_COLUMNS: tuple[str, ...] = (
    columnas NWP + LMD + power — todas las numéricas
)
```

---

### Capa Application — Puerto Strategy y Orquestador

#### [NEW] [cleaning_strategy_port.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/cleaning_strategy_port.py)

Puerto abstracto según PRD §3:

```python
class SolarDataCleaningStrategy(ABC):
    """Interfaz del Patrón Strategy para limpieza de datos fotovoltaicos."""

    @abstractmethod
    def apply_cleaning(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica la estrategia de limpieza y retorna el DataFrame modificado."""
        ...
```

> [!NOTE]
> Se usa `pl.DataFrame` (eager) en vez de `LazyFrame` porque las operaciones de rolling window del Hampel Filter y el cálculo de elevación solar requieren materialización. El `LazyFrame` de la Tarea 2.1 se materializa (`.collect()`) antes de entrar al pipeline de limpieza.

#### [NEW] [cleaning_pipeline.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/cleaning_pipeline.py)

Orquestador que aplica las estrategias en secuencia:

```python
class CleaningPipelineExecutor:
    """Ejecuta una cadena ordenada de estrategias de limpieza."""

    def __init__(self, strategies: Sequence[SolarDataCleaningStrategy]) -> None:
        self._strategies = strategies

    def execute(self, dataframe: pl.DataFrame) -> pl.DataFrame:
        """Aplica cada estrategia en orden, propagando el DataFrame."""
        for strategy in self._strategies:
            dataframe = strategy.apply_cleaning(dataframe)
        return dataframe
```

El orden de ejecución importa:
1. **NighttimeZeroingStrategy** (primero: define la "forma" física del ciclo diurno)
2. **HampelFilterStrategy** (segundo: filtra anomalías en datos ya "formados")
3. **MissingValueImputerStrategy** (último: interpola gaps sobre datos ya limpios)

---

### Capa Infrastructure — 3 Estrategias Concretas

#### [NEW] `infrastructure/strategies/__init__.py`

Package init para el directorio de estrategias.

#### [NEW] [hampel_filter_strategy.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/strategies/hampel_filter_strategy.py)

**Algoritmo**: Para cada columna de velocidad de viento (`nwp_windspeed`, `lmd_windspeed`):
1. Calcular mediana móvil (rolling median, ventana = 5)
2. Calcular MAD (Median Absolute Deviation) móvil
3. Marcar como outlier si `|valor - mediana| > 3.0 × MAD`
4. Reemplazar outliers con la mediana móvil

```
Flujo por columna:
rolling_median = col.rolling_median(window=5)
rolling_mad = |col - rolling_median|.rolling_median(window=5)
is_outlier = |col - rolling_median| > threshold * 1.4826 * rolling_mad
cleaned = when(is_outlier).then(rolling_median).otherwise(col)
```

> [!NOTE]
> El factor `1.4826` convierte MAD a escala de desviación estándar (consistency factor para distribución normal). Esto es estándar en la implementación del Hampel filter.

#### [NEW] [nighttime_zeroing_strategy.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/strategies/nighttime_zeroing_strategy.py)

**Algoritmo**: Para cada fila del DataFrame:
1. Calcular **día del año** desde `date_time`
2. Calcular **declinación solar**: `δ = 23.45° × sin(360/365 × (284 + day_of_year))`
3. Calcular **ángulo horario**: `ω = 15° × (hora + minuto/60 - 12)`
4. Calcular **elevación solar**: `α = arcsin(sin(lat)×sin(δ) + cos(lat)×cos(δ)×cos(ω))`
5. Donde `α ≤ 0°` (sol bajo el horizonte), forzar a **cero exacto**: `nwp_globalirrad`, `nwp_directirrad`, `lmd_totalirrad`, `lmd_diffuseirrad`, `power`

Toda la operación es vectorizada con expresiones Polars (sin loops Python).

#### [NEW] [missing_value_imputer_strategy.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/strategies/missing_value_imputer_strategy.py)

**Algoritmo**:
1. Para cada columna numérica (NWP + LMD + power):
   - Aplicar **interpolación lineal** (`pl.col().interpolate()`) para resolver gaps internos
   - Para los extremos (inicio/fin de serie por estación), aplicar **forward-fill** y luego **backward-fill**
2. La interpolación se ejecuta **por estación** (`group_by("station_id")`) para no interpolar entre estaciones distintas

> [!IMPORTANT]
> El PRD menciona "splines o curva base de irradiancia teórica extraterrestre". Usaremos la interpolación lineal nativa de Polars como base (performante y determinista), que para intervalos de 15 minutos es una aproximación excelente de un spline lineal. Si se requiere interpolación cúbica más adelante, se puede extender la estrategia sin cambiar el contrato.

---

### Resumen de Archivos

| Acción | Archivo | Capa |
|:--|:--|:--|
| MODIFY | `domain/constants.py` | Domain |
| NEW | `application/cleaning_strategy_port.py` | Application |
| NEW | `application/cleaning_pipeline.py` | Application |
| NEW | `infrastructure/strategies/__init__.py` | Infrastructure |
| NEW | `infrastructure/strategies/hampel_filter_strategy.py` | Infrastructure |
| NEW | `infrastructure/strategies/nighttime_zeroing_strategy.py` | Infrastructure |
| NEW | `infrastructure/strategies/missing_value_imputer_strategy.py` | Infrastructure |

**Total: 7 archivos** (1 modificado + 6 nuevos)

## Verification Plan

### Automated Tests

Test con CSV sintético que incluya:

1. **HampelFilter**: Datos de viento con outliers inyectados (ej. velocidad = 999 en una fila), verificar que se reemplaza por la mediana móvil
2. **NighttimeZeroing**: Timestamps nocturnos (ej. 2018-07-01 02:00) con irradiancia no-cero, verificar que se fuerza a 0. Timestamps diurnos (ej. 2018-07-01 12:00) deben conservar sus valores
3. **MissingValueImputer**: Columnas con `null` intercalados, verificar que se interpolan correctamente
4. **Pipeline completo**: Ejecutar las 3 estrategias en secuencia y verificar conteo de anomalías

### Resumen

### ¿Por qué limpiar? (La razón de la Fase 2.2)

Los sensores físicos de las 10 estaciones solares en Hebei, China, no son perfectos:
- Un **anemómetro** puede reportar una ráfaga de 999 m/s por un bug eléctrico → **Hampel Filter** lo detecta y corrige
- De **noche** no hay sol, pero un sensor puede registrar 5 W/m² de ruido → **Nighttime Zeroing** lo fuerza a 0 exacto
- Un sensor puede **desconectarse** 1 hora y dejar valores `null` → **Missing Value Imputer** interpola esos huecos

Sin esta limpieza, cualquier modelo de ML que use estos datos haría pronósticos basura ("garbage in, garbage out").