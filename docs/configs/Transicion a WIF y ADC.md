# Plan de Implementación: Transición a Workload Identity Federation (WIF) y Application Default Credentials (ADC)

Este plan detalla los cambios técnicos necesarios para eliminar la dependencia explícita del archivo estático `credentials.json` en los inicializadores de cliente de GCP. Se implementará una arquitectura basada en **Application Default Credentials (ADC)**, facilitando la transición a **Workload Identity Federation (WIF)** en producción (Cloud Run) y en pipelines de CI/CD (GitHub Actions), al tiempo que se mantiene la compatibilidad local.

## Resumen de Cambios

1. **`config.py`**: Simplificar la lógica de resolución del path de credenciales. Si la ruta existe en desarrollo local, se inyectará directamente en la variable de entorno `os.environ["GOOGLE_APPLICATION_CREDENTIALS"]` para que el SDK de Google la consuma de manera nativa. Si no existe, no se realiza ninguna acción (evitando fallos/crashes) para permitir que ADC use el servidor de metadatos o WIF en producción.
2. **`main.py`**: Cambiar la instanciación de `bigquery.Client` para usar el constructor estándar compatible con ADC: `bigquery.Client(project=settings.gcp_project_id)`.
3. **`pipeline.py`**: Eliminar el argumento `credentials_path` al instanciar los componentes de infraestructura/aplicación (`GCSParquetExporter`, `BigQueryAdapter`, `ScatterPlotGenerator`).
4. **`bigquery_adapter.py`**, **`gcs_parquet_exporter.py`** y **`scatter_plot_generator.py`**: Eliminar el uso de `.from_service_account_json()`. Instanciar los clientes con el constructor estándar (`bigquery.Client(project=...)` y `storage.Client()`) para que el SDK de Google busque las credenciales automáticamente usando ADC.

---

## Cambios Propuestos

### Componente: Configuración y API

#### [MODIFY] [config.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/config.py)
* Refactorizar el validador `_resolve_credentials_path` para configurar de manera nativa la variable de entorno del sistema `GOOGLE_APPLICATION_CREDENTIALS` si el archivo existe localmente.
* Asegurar que no se lance una excepción si el archivo no existe (producción/WIF). Si la variable de entorno apunta a un archivo que no existe localmente, se remueve de `os.environ` para evitar errores del SDK de Google y forzar la caída a ADC nativo.

#### [MODIFY] [main.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/main.py)
* Eliminar por completo el método `bigquery.Client.from_service_account_json(...)`.
* Inicializar el cliente global de BigQuery de la siguiente manera:
  ```python
  app.state.bq_client = bigquery.Client(project=settings.gcp_project_id)
  ```

#### [MODIFY] [pipeline.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/pipeline.py)
* Eliminar el argumento obsoleto `credentials_path` al instanciar los exportadores y adaptadores dentro de la función `build_pipeline(...)`.

---

### Componente: Infraestructura y Adaptadores

#### [MODIFY] [bigquery_adapter.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/bigquery_adapter.py)
* Eliminar el parámetro `credentials_path` del constructor `__init__` (o marcarlo como deprecado/sin efecto para compatibilidad).
* Modificar la instanciación interna del cliente para usar ADC nativo:
  ```python
  bq_client = bigquery.Client(project=self._project_id)
  ```

#### [MODIFY] [gcs_parquet_exporter.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/infrastructure/gcs_parquet_exporter.py)
* Eliminar el parámetro `credentials_path` del constructor `__init__`.
* Modificar la instanciación interna del cliente para usar ADC nativo:
  ```python
  storage_client = storage.Client()
  ```

#### [MODIFY] [scatter_plot_generator.py](file:///Users/matias95lopez/Desktop/serverless-solar-etl/src/app/application/scatter_plot_generator.py)
* Eliminar el parámetro `credentials_path` del constructor `__init__`.
* Modificar la instanciación interna del cliente para usar ADC nativo:
  ```python
  client = storage.Client()
  ```

---

## Plan de Verificación

### Pruebas Automatizadas
* Ejecutar la suite de tests existente para asegurar que el pipeline sigue ejecutándose sin problemas locales:
  ```bash
  pytest
  ```

### Verificación Manual
* Levantar el servidor localmente con `uvicorn app.main:app --reload` y realizar una petición de prueba al endpoint `/run` o `/aggregate` para constatar que el cliente de BigQuery y GCS se autentican correctamente usando el archivo local inyectado vía `os.environ`.

---

## Integración con Workload Identity Federation (WIF) y GitHub Actions

Para escalar la seguridad del proyecto y eliminar el uso de llaves JSON estáticas en el flujo de despliegue continuo (CI/CD), se implementa la federación de identidades mediante OIDC. A continuación se documenta el flujo general de configuración en Google Cloud y el diseño del workflow de GitHub Actions que complementa esta arquitectura utilizando nombres y valores genéricos.

### 1. Flujo de Configuración General en GCP (`gcloud`)

#### A. Creación del Pool de Identidades de Trabajo (Workload Identity Pool)
Esto crea el contenedor lógico que agrupará a los proveedores de identidad:
```bash
gcloud iam workload-identity-pools create "github-actions-pool" \
  --project="TU_PROJECT_ID" \
  --location="global" \
  --display-name="GitHub Actions Pool"
```

#### B. Creación del Proveedor OIDC para GitHub
Esto le dice a GCP exactamente qué atributos de GitHub debe leer (como el nombre del repositorio) y define una condición de seguridad estricta para que solo tu organización o usuario de GitHub pueda negociar credenciales:
```bash
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project="TU_PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="github-actions-pool" \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-condition="assertion.repository_owner == 'TU_GITHUB_USER'"
```

#### C. Obtención del Número del Proyecto
GCP utiliza el número identificador numérico único (no el ID de texto) para los enlaces de IAM de WIF. Ejecuta este comando y copia el número de retorno:
```bash
gcloud projects describe "TU_PROJECT_ID" --format="value(projectNumber)"
```

#### D. Vinculación del Repositorio con tu Service Account
Aquí ocurre la vinculación de seguridad. Se concede el rol de **Usuario de Workload Identity** (`roles/iam.workloadIdentityUser`) a las ejecuciones que provengan estrictamente de tu repositorio de GitHub específico. Reemplaza `NUMERO_DE_PROYECTO` con el valor obtenido en el paso C:
```bash
gcloud iam service-accounts add-iam-policy-binding "TU_SERVICE_ACCOUNT@TU_PROJECT_ID.iam.gserviceaccount.com" \
  --project="TU_PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/NUMERO_DE_PROYECTO/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/TU_GITHUB_USER/TU_GITHUB_REPO"
```

---

### 2. Configuración del Workflow de CI/CD: [deploy.yml](file:///Users/matias95lopez/Desktop/serverless-solar-etl/.github/workflows/deploy.yml)

El archivo de configuración de GitHub Actions aprovecha esta federación de identidades para autenticar la ejecución del pipeline de forma temporal y segura sin inyectar secretos JSON.

```yaml
name: Deploy Solar ETL to Cloud Run

on:
  push:
    branches:
      - main

# CRÍTICO: Concede los permisos necesarios para emitir y escribir el token OIDC JWT de GitHub
permissions:
  contents: 'read'
  id-token: 'write'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      # Paso de Intercambio de Credenciales WIF (OIDC)
      - name: Google Auth
        id: auth
        uses: 'google-github-actions/auth@v2'
        with:
          workload_identity_provider: 'projects/NUMERO_DE_PROYECTO/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider'
          service_account: 'TU_SERVICE_ACCOUNT@TU_PROJECT_ID.iam.gserviceaccount.com'

      - name: Set up Cloud SDK
        uses: 'google-github-actions/setup-gcloud@v2'

      # Construcción y subida de la imagen Docker usando scripts locales
      - name: Build and Push Docker Image
        env:
          GCP_PROJECT_ID: 'TU_PROJECT_ID'
          GCP_REGION: 'us-central1'
          AR_REPO_NAME: 'solar-etl-repo'
        run: ./scripts/build_and_push.sh

      # Despliegue automático a Cloud Run sin credenciales JSON estáticas
      - name: Deploy to Cloud Run
        env:
          GCP_PROJECT_ID: 'TU_PROJECT_ID'
          GCP_REGION: 'us-central1'
          AR_REPO_NAME: 'solar-etl-repo'
          GCS_BUCKET_NAME: 'TU_GOLD_BUCKET_NAME'
          GITHUB_RAW_URL: 'https://raw.githubusercontent.com/TU_GITHUB_USER/TU_GITHUB_REPO/data/upload-pvod-dataset/data/pvod.csv'
          SCIDB_FALLBACK_URL: 'https://scidb.cn/api/v1/dataset/pvod.csv'
        run: ./scripts/deploy_to_cloud_run.sh
```

### Impacto y Escalabilidad del Push
Al realizar `git push` de este archivo a la rama `main`:
1. El pipeline de GitHub Actions se activará automáticamente de forma segura.
2. Intercambiará un JWT firmado por GitHub por un token federado de Google Cloud en milisegundos.
3. Se construirá la imagen del contenedor del ETL y se desplegará de forma totalmente Serverless a Cloud Run.
4. **Cero Secretos Expuestos**: La infraestructura elimina de raíz el riesgo de filtraciones de credenciales en repositorios de código, logrando el estándar más avanzado de madurez y seguridad en la nube (SecOps).
