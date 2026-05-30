# Problema de Arquitectura en Artifact Registry y Cloud Run (Apple Silicon)

## 📌 El Problema

Al intentar desplegar la API a Google Cloud Run utilizando una imagen Docker alojada en Artifact Registry, el despliegue falló con el siguiente error:

```text
ERROR: (gcloud.run.deploy) Revision 'pvod-solar-api-00013-xsf' is not ready and cannot serve traffic. Cloud Run does not support image 'us-central1-docker.pkg.dev/serverless-solar-etl/solar-etl-repo/pvod-api:fix-duplication': Container manifest type 'application/vnd.oci.image.index.v1+json' must support amd64/linux.
```

## 🔍 Causa Raíz

El error ocurre por una discrepancia de arquitecturas de hardware:

1. **Entorno Local (Mac con Apple Silicon):** Cuando ejecutas `docker build` en un Mac moderno (procesadores M1, M2, M3, etc.), Docker por defecto construye la imagen para la arquitectura de ese procesador, que es `arm64`.
2. **Entorno de Destino (Google Cloud Run):** El entorno estándar de Google Cloud Run donde se ejecutan los contenedores está basado en servidores Intel/AMD, por lo que exige que las imágenes estén compiladas para la arquitectura `linux/amd64`.

Cuando Cloud Run intentó levantar el contenedor, detectó que el manifiesto de la imagen en Artifact Registry indicaba que era una imagen `arm64`, por lo que rechazó el despliegue.

## ✅ La Solución

Para solucionar esto, es necesario forzar a Docker a compilar la imagen para la arquitectura correcta usando la bandera `--platform`.

### 1. Construir la imagen para la arquitectura correcta

```bash
docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/serverless-solar-etl/solar-etl-repo/pvod-api:fix-duplication .
```

Al especificar `--platform linux/amd64`, Docker en macOS utiliza un emulador interno (Rosetta 2 o QEMU) para compilar la imagen de forma que sea compatible con los servidores de Cloud Run.

### 2. Subir la imagen a Artifact Registry

Una vez construida con la arquitectura correcta, la imagen se sube de forma normal:

```bash
docker push us-central1-docker.pkg.dev/serverless-solar-etl/solar-etl-repo/pvod-api:fix-duplication
```

### 3. Desplegar en Cloud Run

Finalmente, el comando de despliegue puede ejecutarse sin problemas:

```bash
gcloud run deploy pvod-solar-api \
    --image us-central1-docker.pkg.dev/serverless-solar-etl/solar-etl-repo/pvod-api:fix-duplication \
    --region us-central1 \
    --project serverless-solar-etl \
    --allow-unauthenticated \
    ...
```

## 💡 Recomendación para CI/CD

Si en el futuro automatizas este proceso usando **Google Cloud Build** (ej. `gcloud builds submit`), este problema generalmente no ocurre porque Cloud Build ejecuta el comando `docker build` nativamente en un servidor de Google (que ya es `amd64`), generando la imagen correcta por defecto. Este error es típico sólo del flujo de desarrollo donde se construye localmente en macOS y se hace _push_ manual.
