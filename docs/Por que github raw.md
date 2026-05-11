GitHub RAW y Fallback de datos: ¿por qué?

La elección de GitHub Raw es una solución optimizada específicamente para la naturaleza estática y de archivo único del dataset PVOD.

Si estuviéramos ante un escenario de datos dinámicos, la arquitectura de tu "refinería" tendría que cambiar drásticamente. Aquí te explico cómo se diferenciarían ambos mundos:

1. El escenario actual: Datos Estáticos (Batch Processing)

Como el dataset PVOD comprende un periodo cerrado (julio 2018 - junio 2019), lo tratamos como una "Carga de Lote" (Batch).

Fuente: Un archivo CSV inmutable alojado en GitHub o SciDB.

Frecuencia: Se procesa una vez (o bajo demanda si hay cambios en las reglas de limpieza).

Herramienta: El GitHubRawExtractor es suficiente porque solo necesitamos descargar el bloque completo de datos para procesarlo con Polars.

2. El escenario alternativo: Datos Dinámicos (Real-time o Streaming)

Si estuviéramos monitoreando las estaciones solares hoy mismo en tiempo real, no podríamos usar GitHub Raw. Tendríamos que implementar:

Consumo de APIs: En lugar de un extractor de archivos, usarías un RestApiExtractor que consulte endpoints cada 15 minutos para obtener las últimas lecturas de irradiancia y potencia.

Webhooks / Pub/Sub: Los inversores solares podrían enviar sus datos directamente a un servicio de mensajería (como Google Cloud Pub/Sub) apenas los generen.

Orquestación Continua: Usarías Cloud Scheduler para "despertar" a tu contenedor de Cloud Run cada pocos minutos, procesar el nuevo registro y añadirlo a BigQuery.

3. ¿Por qué el PRD exige ambos (GitHub y SciDB)?

Incluso siendo estáticos, tu PRD exige resiliencia.

GitHub Raw actúa como una "CDN de archivos": es extremadamente rápido para descargar archivos pesados.

SciDB es la fuente de verdad científica. Si GitHub llega a borrar el archivo o falla su servidor, tu pipeline cambia de estrategia para no quedar desabastecido.

Resumen de tu configuración final

Para tu proyecto, el CSV en GitHub es perfecto porque:

Es determinista: Los 271,968 registros no cambiarán.

Es eficiente: Permite probar toda la lógica de Clean Architecture y Polars sin la complejidad de manejar autenticaciones de APIs externas dinámicas en esta etapa.

Para que tu proyecto pueda consumir el CSV desde GitHub de forma profesional, tienes que subir el archivo a un repositorio y luego obtener el enlace "Raw". Aquí tienes los pasos exactos para hacerlo:

¿Cómo dejar el .csv maestro en GitHub raw?

1. Preparar el archivo

Asegúrate de que el archivo se llame pvod.csv. Como el dataset PVOD original suele venir dividido por estaciones o años, lo ideal es que para este proyecto tengas un solo archivo consolidado con los 271,968 registros que menciona tu PRD.

2. Crear el Repositorio en GitHub

Si ya tienes el repositorio de tu proyecto (donde estás trabajando el código), puedes subirlo ahí mismo en una carpeta llamada data/.

Ve a tu repositorio en GitHub.

Haz clic en Add file > Upload files.

Sube el archivo pvod.csv.

Haz el Commit (ej: data: agrega dataset crudo PVOD).

Sin embargo, si el archivo pesa mas de 25 MB, esto no sirve, y hay que optar por esta otra opción:

Lo que sucedió es que hiciste el Merge de tu rama a main (probablemente a través de la interfaz de GitHub o mediante un proceso automatizado al hacer el pull), y luego borraste la rama local. ¡No hay problema! Es parte del flujo normal.
Como ahora estás en main y ya tienes el código ahí, simplemente vamos a crear una nueva rama específica para subir el dataset. Esto mantiene tu historial limpio: el código vive en main, y el archivo pesado entrará en un nuevo commit.

Sigue estos pasos para subir el pvod.csv por terminal:

i. Crear rama para el Data Push

git checkout -b data/upload-pvod-dataset


ii. Generar el archivo (si aún no lo haces)
Asegúrate de ejecutar el script para que el archivo aparezca en la carpeta data/:

python scripts/consolidate_pvod.py


iii. Forzar el rastreo del archivo
Como mencionaste antes, es probable que tu .gitignore esté ignorando archivos .csv. Vamos a forzar la adición de este archivo específico:

git add -f data/pvod.csv


iv. Commit y Push
Aquí es donde la terminal permite superar el límite de los 25MB de la web (soporta hasta 100MB):

git commit -m "data: sube dataset maestro consolidado PVOD (271,968 registros)"
git push -u origin data/upload-pvod-dataset


3. Obtener la URL "Raw" (La que va en el .env)

Una vez que el comando push termine con éxito:

Obtener la URL Raw: Ve a GitHub en tu navegador, entra en la rama data/upload-pvod-dataset, busca data/pvod.csv, haz clic en él y luego en el botón "Raw".

Configurar tu .env: Copia esa URL en tu variable GITHUB_RAW_URL.

Fase 1.0: Con el dataset ya disponible en la nube (vía GitHub), ya tienes todo el "petróleo" listo para empezar a programar la Fase 1.0 de tu guía.

Nota sobre los roles de GCP: Recuerda que para que tu código de Python interactúe con el resto de la infraestructura (Storage y BigQuery), tu cuenta de servicio debe tener activados los roles de roles/bigquery.dataEditor, roles/bigquery.jobUser, roles/storage.objectCreator y roles/logging.logWriter que definiste en tu guía definitiva.

¿Cómo quedaría en tu .env?

Si tu usuario de GitHub es n0mercy95 y tu repo se llama solar-etl, la variable se vería así:

GITHUB_RAW_URL=[https://raw.githubusercontent.com/n0mercy95/solar-etl/main/data/pvod.csv](https://raw.githubusercontent.com/n0mercy95/solar-etl/main/data/pvod.csv)


¿Por qué lo hacemos así?

Capa de Ingesta: Según tu PRD, el GitHubRawExtractor es la fuente prioritaria porque la red de entrega de contenido (CDN) de GitHub es más rápida para descargar archivos estáticos.

Separación de Preocupaciones: El código no "lleva" los datos dentro; los "busca" en una fuente externa. Esto permite que si el dataset se actualiza, no tengas que cambiar ni una sola línea de código, solo el archivo en GitHub.

Nota sobre el tamaño del archivo y subida en web

Si el CSV pesa más de 100 MB GitHub te pedirá usar LFS (Large File Storage). Si es menor a eso -y menor a 25 MB-, la subida normal funcionará perfecto por la web, si no se debe hacer por comando como lo indica arriba.