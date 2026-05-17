# Guía de Uso de Scripts de Despliegue

Esta guía describe los pasos necesarios para preparar el entorno y desplegar la API Serverless PVOD en Google Cloud Run utilizando los scripts proporcionados.

## 1. Configuración Previa

Antes de ejecutar cualquier script, asegúrate de tener el entorno local correctamente configurado.

### Entorno Virtual (`uv`)
Asegúrate de tener activado el entorno virtual del proyecto. Si estás usando `uv`, actívalo desde la raíz del proyecto (donde se encuentra la carpeta `.venv`):

```bash
# Activar el entorno virtual
source .venv/bin/activate
```

### Archivo de Configuración `.env`
Los scripts dependen de las variables definidas en el archivo `.env` ubicado en la raíz del proyecto. Asegúrate de que exista y contenga los valores correctos para tu entorno, especialmente:

- `GCP_PROJECT_ID`
- `GCP_REGION`
- `AR_REPO_NAME`
- `GCS_BUCKET_NAME`
- `GITHUB_RAW_URL`
- `SCIDB_FALLBACK_URL`

*Nota: Los scripts cargarán automáticamente estas variables al ejecutarse.*

### Autenticación en Google Cloud
Asegúrate de estar autenticado en Google Cloud CLI con tu cuenta y que tienes los permisos necesarios sobre el proyecto:

```bash
# Iniciar sesión en GCP
gcloud auth login

# (Opcional) Configurar el proyecto por defecto
gcloud config set project tu-proyecto-id
```

---

## 2. Proceso de Despliegue

El despliegue se realiza en dos etapas mediante los scripts ubicados en esta carpeta (`scripts/`). Debes ejecutarlos en el siguiente orden:

### Paso 1: Construir y subir la imagen Docker
Este script compila la imagen Docker de la aplicación (forzando la arquitectura `linux/amd64` compatible con Cloud Run) y la sube a Google Artifact Registry.

```bash
# Ejecutar desde la carpeta scripts/
./build_and_push.sh
```

### Paso 2: Desplegar en Cloud Run
Una vez que la imagen está en Artifact Registry, este script se encarga de crear o actualizar el servicio en Google Cloud Run. Inyectará las variables de entorno necesarias y configurará los secretos de Secret Manager.

```bash
# Ejecutar desde la carpeta scripts/
./deploy_to_cloud_run.sh
```

Al finalizar, el script mostrará en la terminal la URL pública de tu API desplegada (ej. `https://pvod-solar-api-[ID].run.app`).

---

## 3. Verificación y Uso de la API

Una vez desplegada, tu API ya es pública y está lista para recibir peticiones.

### Probar la API desde el Navegador (Swagger UI)
FastAPI incluye documentación interactiva por defecto. Puedes hacer pruebas directamente desde tu navegador:

1. Abre la URL que te dio el script de despliegue y añádele `/docs` al final.
   - Ejemplo: `https://pvod-solar-api-264931673910.us-central1.run.app/docs`
2. Verás la interfaz de Swagger UI con los endpoints disponibles.
3. Puedes hacer clic en el endpoint `/api/v1/metrics/aggregate`, luego en **"Try it out"**, ingresar las fechas y ejecutar la consulta a BigQuery visualmente.

### Realizar una petición POST por Terminal (cURL)
También puedes interactuar con el endpoint directamente usando `curl`. Para el endpoint de métricas agregadas, debes enviar las fechas de inicio y fin (y opcionalmente `dry_run` en true si solo quieres estimar costos):

```bash
curl -X POST "https://pvod-solar-api-264931673910.us-central1.run.app/api/v1/metrics/aggregate" \
     -H "Content-Type: application/json" \
     -d '{
           "start_date": "2018-01-01T00:00:00",
           "end_date": "2018-12-31T23:59:59",
           "dry_run": false
         }'
```

### Revisar Logs en Google Cloud Platform
Tu API usa Logging Estructurado. Para ver en tiempo real cómo se comporta, qué errores hay o el uso:
1. Ve a la consola de Google Cloud: [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. En el menú de navegación, busca **Cloud Run**.
3. Selecciona tu servicio (`pvod-solar-api`).
4. Ve a la pestaña **Registros** (Logs). Ahí podrás ver todo el historial de peticiones, arranques y cualquier excepción que registre tu aplicación.

---

## 4. Solución de Problemas (Troubleshooting)

Si encuentras errores de servidor (Error 500) o la aplicación de Cloud Run se cae en el arranque (Container failed to start), es altamente probable que necesites modificar código fuente Python o el archivo `.env`.

**Regla de Oro en Cloud Run**: Cloud Run no lee tu código local en tiempo real. Ejecuta la *imagen Docker* que está en Artifact Registry.

Por lo tanto, **CADA VEZ** que modifiques:
- Archivos `.py` en la carpeta `src/` (tu código).
- Archivos `requirements.txt` o librerías.
- Variables en el `.env` (ya que los scripts los usan al desplegar).

**DEBES volver a compilar y subir la imagen antes de desplegar**. Sigue siempre este flujo completo:

1. **Revisar los Logs:** Identifica el error en la consola de GCP (Cloud Run > Registros).
2. **Corregir el código:** Haz los arreglos en tus archivos locales de Python o en el `.env`.
3. **Reconstruir la imagen:**
   ```bash
   ./build_and_push.sh
   ```
   *(Espera a que termine y te confirme "Proceso completado con éxito")*
4. **Desplegar la nueva revisión:**
   ```bash
   ./deploy_to_cloud_run.sh
   ```
   *(Cloud Run tomará la nueva imagen con tu código corregido y la pondrá en producción).*
