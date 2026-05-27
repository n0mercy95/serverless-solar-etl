# Fix: Configuración Dual Local/Producción en `config.py`

Este documento explica los cambios realizados en [`src/app/application/config.py`](../../src/app/application/config.py) para que el proyecto funcione de forma transparente tanto en **desarrollo local** como en **producción (Cloud Run)**, usando un único archivo `.env`.

---

## El Problema de Fondo

El proyecto tiene **dos entornos de ejecución** con estructuras de filesystem diferentes:

| Aspecto | Local (Uvicorn directo) | Producción (Docker → Cloud Run) |
|---|---|---|
| **Raíz de trabajo** | `/Users/.../serverless-solar-etl/` | `/app/` (WORKDIR del Dockerfile) |
| **Código fuente** | `./src/app/main.py` | `/app/src/app/main.py` |
| **Credenciales** | `./src/app/credentials/credentials.json` | `/app/src/app/credentials/credentials.json` |
| **PYTHONPATH** | Configurado por `--app-dir src` | Configurado por `ENV PYTHONPATH=/app/src` |
| **`.env`** | En la raíz del proyecto `./` | No se usa — las variables se inyectan vía Cloud Run + Secret Manager |

El archivo `.env` contiene rutas pensadas para el contenedor Docker:

```env
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/credentials.json
```

Esa ruta **solo existe dentro del contenedor**. En local, el archivo real está en `<proyecto>/src/app/credentials/credentials.json`.

---

## Qué Se Arregló

### 1. Ruta absoluta al `.env` (resolución determinista)

**Antes:**
```python
model_config = SettingsConfigDict(
    env_file=".env",       # ← Relativa al CWD, no al proyecto
    ...
)
```

**Después:**
```python
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),   # ← Absoluta, siempre encuentra el .env
        ...
    )
```

**¿Por qué fallaba?** `pydantic-settings` resolvía `".env"` desde el **directorio de trabajo actual** (CWD). En Docker el CWD es `/app/` y funciona. Pero localmente, si lanzabas Uvicorn con `--app-dir src` o desde una subcarpeta, el CWD no coincidía con la raíz del proyecto y **el `.env` no se encontraba**. La aplicación arrancaba sin variables configuradas y fallaba con errores de validación o valores por defecto incorrectos.

**Solución:** Se calcula la raíz del proyecto de forma determinista subiendo 3 niveles desde la ubicación física de `config.py`:

```
config.py → application/ → app/ → src/ → PROJECT_ROOT
   [0]          [1]         [2]     [3]
```

Esto garantiza que el `.env` se localice correctamente sin importar desde dónde se ejecute el servidor.

---

### 2. Remapeo automático de la ruta de credenciales

**Antes:** No existía — el valor del `.env` se usaba tal cual.

**Después:** Se añadió un `@model_validator` que detecta y corrige rutas del contenedor Docker cuando se ejecuta en local.

```python
@model_validator(mode="after")
def _resolve_credentials_path(self) -> Settings:
    cred = self.google_application_credentials
    if cred is None:
        return self

    cred_path = Path(cred)
    if cred_path.exists():
        # La ruta ya es válida (ej. dentro del contenedor Docker)
        return self

    # Intentar resolver: /app/X → <PROJECT_ROOT>/src/app/X
    if cred_path.parts[:2] == ("/", "app"):
        local_path = _PROJECT_ROOT / "src" / "app" / Path(*cred_path.parts[2:])
        if local_path.exists():
            self.google_application_credentials = str(local_path)

    return self
```

**¿Por qué fallaba?** El `.env` declara `GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/credentials.json`. Dentro del contenedor Docker esa ruta existe (porque el Dockerfile hace `COPY ./src /app/src`). Pero en local, no existe `/app/` — el archivo real está en `<proyecto>/src/app/credentials/credentials.json`. Sin el validador, la aplicación intentaba leer un archivo inexistente y lanzaba:

```
[Errno 2] No such file or directory: '/app/credentials/credentials.json'
```

**Lógica del remapeo:**

1. Si la ruta ya existe en el filesystem → no hacer nada (estamos en Docker).
2. Si la ruta empieza con `/app/` y no existe → remapear a `<PROJECT_ROOT>/src/app/...` y verificar que el archivo local sí existe.

Esto permite mantener **un solo `.env`** con rutas del contenedor, sin necesidad de crear un `.env.local` separado.

---

## ¿Por Qué Funciona en Ambos Entornos?

### En producción (Cloud Run / Docker)

```
Dockerfile:
  WORKDIR /app
  COPY ./src /app/src
  ENV PYTHONPATH=/app/src
  ENTRYPOINT ["uvicorn", "app.main:app", ...]
```

1. **`.env` no se usa** — las variables se inyectan directamente por Cloud Run (`--set-env-vars`) y Secret Manager (`--set-secrets`).
2. Si se usara el `.env`, `_PROJECT_ROOT` resolvería a `/app/` y `env_file` apuntaría a `/app/.env` — funciona.
3. `GOOGLE_APPLICATION_CREDENTIALS` apunta a `/app/credentials/credentials.json` — existe en el contenedor, el validador no hace nada.
4. En producción con Cloud Run, la autenticación se resuelve automáticamente por la **cuenta de servicio del contenedor**, por lo que `GOOGLE_APPLICATION_CREDENTIALS` puede ser `None`.

### En desarrollo local

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload --app-dir src
```

1. `_PROJECT_ROOT` resuelve a `/Users/.../serverless-solar-etl/` (3 niveles arriba desde `config.py`).
2. `env_file` apunta a `/Users/.../serverless-solar-etl/.env` — se encuentra correctamente.
3. `GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/credentials.json` se carga del `.env`.
4. El validador detecta que `/app/credentials/credentials.json` **no existe** → remapea a `/Users/.../serverless-solar-etl/src/app/credentials/credentials.json` → existe → funciona.

---

## Cómo Trabajar en Producción

### Despliegue

```bash
# 1. Autenticarse con GCP
gcloud auth login

# 2. Construir y subir la imagen Docker a Artifact Registry
cd scripts
./build_and_push.sh

# 3. Desplegar a Cloud Run
./deploy_to_cloud_run.sh
```

Al finalizar, Cloud Run imprime la URL del servicio:

```
Service URL: https://pvod-solar-api-XXXXXXXXXX.us-central1.run.app
```

### Consultas en producción

La API es pública (`--allow-unauthenticated`) y se puede consultar de tres formas:

**1. Swagger UI (navegador):**
```
https://<URL_CLOUD_RUN>/docs
```

**2. cURL (terminal):**
```bash
# Ejecutar ETL
curl -X POST "https://<URL_CLOUD_RUN>/api/v1/etl/run"

# Consultar métricas
curl -X POST "https://<URL_CLOUD_RUN>/api/v1/metrics/aggregate" \
     -H "Content-Type: application/json" \
     -d '{
           "start_date": "2018-07-01T00:00:00",
           "end_date": "2018-07-02T23:59:59",
           "dry_run": true
         }'
```

**3. Postman / Thunder Client:**
- Método: `POST`
- URL: `https://<URL_CLOUD_RUN>/api/v1/metrics/aggregate`
- Body (raw JSON):
  ```json
  {
    "start_date": "2018-07-01T00:00:00",
    "end_date": "2018-07-02T23:59:59",
    "dry_run": true
  }
  ```

### Actualización de configuración en producción

Si necesitas cambiar el nombre del dataset de BigQuery u otro secreto:

```bash
# Actualizar un secreto en Secret Manager
echo -n "nuevo_valor" | gcloud secrets versions add nombre_del_secreto --data-file=-

# Redesplegar para que Cloud Run tome la nueva versión
./deploy_to_cloud_run.sh
```

---

## Archivos Involucrados

| Archivo | Rol |
|---|---|
| [`src/app/application/config.py`](../../src/app/application/config.py) | Resolución dual de rutas `.env` y credenciales |
| [`.env`](../../.env) | Variables de entorno (rutas en formato Docker) |
| [`Dockerfile`](../../Dockerfile) | Define la estructura `/app/src/` del contenedor |
| [`scripts/deploy_to_cloud_run.sh`](../../scripts/deploy_to_cloud_run.sh) | Inyecta variables y secretos a Cloud Run |
