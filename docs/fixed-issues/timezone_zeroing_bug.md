# Resolución de Incidente: Desfase Horario en Zeroing Nocturno (Timezone Awareness Bug)

## Descripción del Problema Original
Durante la fase de Data Profiling visual del pipeline ETL, observamos que el gráfico del **Perfil Diurno de Potencia (Power vs Tiempo)** mostraba una anomalía grave en los datos post-limpieza: la estrategia `NighttimeZeroingStrategy` estaba "amputando" (forzando a cero) la mitad izquierda de la campana principal de producción solar. 

Esto provocó que se destruyeran lecturas de potencia totalmente válidas que ocurrían durante el día, afectando gravemente el promedio (Mean) de producción solar y corrompiendo la física del dataset.

## Causa Raíz
El dataset original de producción solar PVOD recopila datos de estaciones ubicadas en China (aprox. UTC+8), pero los timestamps crudos en el CSV venían en zona horaria **UTC (Universal Time Coordinated)**. 

El modelo astronómico utilizado por la `NighttimeZeroingStrategy` para calcular la elevación solar asume implícitamente que la hora ingresada es la **hora local**. Al alimentar el algoritmo con timestamps UTC ingenuos (naive):
1. El mediodía solar en China ocurría a las `04:00` del reloj UTC.
2. El algoritmo evaluaba la elevación solar para las `04:00 AM`, concluyendo que el sol estaba por debajo del horizonte.
3. Forzaba a `0.0` toda la irradiancia y potencia producida en ese momento.

Básicamente, el ETL estaba tratando el mediodía como si fuera madrugada, y la noche como si fuera día.

## Solución Implementada
Implementamos una corrección estricta de Timezone Awareness utilizando evaluación "lazy" (perezosa) de Polars en la capa de ingesta (`PVODLazyLoader`) para evitar overhead de memoria:

```python
# Corrección en src/app/infrastructure/pvod_lazy_loader.py
lazy_df = lazy_df.with_columns(
    pl.col("date_time")
    .dt.replace_time_zone("UTC")              # 1. Declarar que la data cruda es UTC
    .dt.convert_time_zone("Asia/Shanghai")    # 2. Trasladar a la hora local física
)
```

### Impacto y Observabilidad
1. **Conservación de Datos**: La campana de producción solar ahora se preserva al 100%. El pico vuelve a coincidir correctamente con el mediodía local (12:00 - 14:00 CST).
2. **Data Profiling Realista**: La `NighttimeZeroingStrategy` ahora solo plancha a cero pequeños ruidos de sensor durante la noche real. El perfilador detectó que se purgan exitosamente ~2,600 registros de ruido nocturno por corrida.
3. **Mejora en Visualización**: Actualizamos el gráfico diurno (`ScatterPlotGenerator`) para usar **escala logarítmica** en el eje Y, permitiendo visualizar claramente el ruido nocturno microscópico (0.03 MW - 0.13 MW) frente al pico diurno de ~30 MW.

## Prevención Futura
* Siempre declarar explícitamente las zonas horarias al inicio del pipeline (Shift-Left validation).
* No confiar en Datetimes ingenuos (`naive`) cuando el pipeline involucra modelado físico o astronómico.
