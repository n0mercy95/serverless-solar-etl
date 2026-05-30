# Resolución: Redundancia en Scatter Plots de Irradiancia y Limpieza NWP vs LMD

## Descripción del Problema
Tras solucionar el desfase horario (Timezone Bug), se observó que los gráficos de dispersión (scatter plots) comparando la irradiancia predicha (NWP) frente a la medición local (LMD) se veían idénticos en las fases "Pre-Cleaning" y "Post-Cleaning (Gold)".

### ¿Por qué los scatter plots se "duplicaban" visualmente?
Esto ocurría porque el pipeline original no contaba con ninguna heurística diseñada para corregir la desviación o correlación entre NWP y LMD. Analicemos el impacto de las estrategias previas sobre la irradiancia:

* **NighttimeZeroingStrategy**: Forzaba a 0 ambas columnas (NWP y LMD) durante la noche. Como la irradiancia ya es ~0 de noche de forma natural, forzar 0 sobre 0 no producía ningún cambio visible en el gráfico.
* **HampelFilterStrategy**: Operaba exclusivamente sobre la velocidad del viento.
* **MissingValueImputerStrategy**: Interpolaba valores nulos, pero no corregía lecturas anómalas existentes.

Como resultado, los puntos dispersos donde la predicción NWP fallaba drásticamente respecto a la realidad LMD pasaban intactos por todo el pipeline. La aparente "mejora" masiva que se veía antes en los gráficos era simplemente el bug horario destruyendo lecturas legítimas del mediodía.

## Solución: IrradianceOutlierStrategy

Para que la limpieza mejore la coherencia física de los datos y acerque el gráfico post-cleaning a una recta 1:1 (donde Predicción ≈ Medición), se implementó una nueva estrategia basada en criterios físicos de desviación.

### Criterios Físicos y Lógica de Limpieza

Se realizó un análisis estadístico del dataset diurno que reveló que la mediana del ratio NWP/LMD es de 0.97 (casi 1:1 perfecto), con desviaciones estándar infladas por valores atípicos (fallos de sensor, sombras o errores de modelo). En base a esto, se establecieron los siguientes criterios físicos:

* **Lógica**: Para cada par NWP/LMD, se calcula el ratio `NWP / LMD`. 
* **Umbral Mínimo**: Si ambos valores son significativos (> 50 W/m²) y el ratio cae fuera del rango aceptable **[0.3, 3.0]**, ambas columnas se consideran outliers. Se ignora el ruido en umbrales muy bajos (como el amanecer) donde la luz tenue provoca fluctuaciones extremas en los ratios.
* **Nullificación e Interpolación**: Los valores anómalos se reemplazan con `null`. Después, la estrategia de imputación (`MissingValueImputerStrategy`) los interpola de manera continua en función del tiempo.

### Orden del Pipeline de Limpieza Actualizado

El orden del pipeline es crítico para que la interpolación funcione sobre la forma correcta del día:

1. **NighttimeZeroingStrategy** → Define la forma física del ciclo diurno y aplana a cero absoluto la noche.
2. **IrradianceOutlierStrategy (NUEVA)** → Elimina divergencias severas NWP vs LMD (fijando a null).
3. **HampelFilterStrategy** → Remueve anomalías (picos) de viento.
4. **MissingValueImputerStrategy** → Interpola todos los nulls (incluyendo los generados intencionalmente en el paso 2).

### Resultado Medido y Observabilidad

Al aplicar este nuevo filtro físico:
* La desviación estándar del ratio NWP/LMD bajó de **0.741 a 0.572** (−23%).
* Los puntos con divergencia extrema fueron eliminados e interpolados, acercando visiblemente el scatter plot Post-Cleaning a una recta 1:1.
* Los falsos positivos de correlación fueron reducidos, resultando en un dataset de "Gold Layer" mucho más confiable para el modelado fotovoltaico posterior.
