# Plan de Implementación: Tarea 4.2 (Contenedorización Final)

Este documento detalla retrospectivamente el plan de ejecución seguido para completar la Tarea 4.2 ("Construir y purgar imagen Docker multi-stage sobre Debian base y subir a Artifact Registry") definida en el PRD.

## Objetivo
Empaquetar el código fuente de la aplicación, las dependencias y el entorno de ejecución (Uvicorn/FastAPI) en una imagen Docker inmutable, segura y optimizada. Posteriormente, subirla a Google Artifact Registry para su ingesta por Cloud Run.

---

## 1. Validación del Entorno de Construcción (`Dockerfile`)

El PRD especifica restricciones estrictas sobre el sistema base para mantener la compatibilidad binaria (evitando Alpine/musl libc por problemas con PyArrow/Polars).

*   **Imagen Base Estricta**: Se garantizó el uso de `python:3.11-slim-bullseye` (basado en Debian con `glibc`).
*   **Estrategia Multi-stage**:
    *   **Stage 1 (`builder`)**: Instala dependencias del sistema operativo (`build-essential`) y empaqueta las librerías de Python utilizando el gestor de paquetes determinista `uv`.
    *   **Stage 2 (`runtime`)**: Genera la imagen "purgada". Se desechan los compiladores (C/C++, Rust) y cachés para minimizar el tamaño y reducir la superficie de ataque (vulnerabilidades).
*   **Seguridad**: Configuración del usuario `appuser` (non-root) para la ejecución del Entrypoint, cumpliendo las normativas de seguridad en la nube.
*   **Entrypoint**: Exposición del puerto 8080 (estándar de Cloud Run) e inicialización del servidor `uvicorn`.

---

## 2. Automatización del Despliegue (Build & Push)

Para no depender de comandos manuales propensos a errores, se orquestó la subida a Artifact Registry.

### Creación de Script (`scripts/build_and_push.sh`)
Se implementó un script Bash encargado de:
1.  **Construcción Local (`docker build`)**: Etiqueta la imagen (`-t`) construyendo la URI esperada por GCP: `[REGION]-docker.pkg.dev/[PROJECT_ID]/[REPO_NAME]/[IMAGE_NAME]:[TAG]`.
2.  **Autenticación Automática (`gcloud auth configure-docker`)**: Configura el demonio de Docker local para que inyecte de manera transparente los tokens de acceso de OAuth 2.0 de Google Cloud.
3.  **Subida al Repositorio (`docker push`)**: Empuja la imagen purgada al registro.

---

## 3. Justificación de Diseño: Artifact Registry

Se definió el uso de Google Artifact Registry en lugar de otros registros públicos (ej. DockerHub) por tres directrices clave que rigen arquitecturas Serverless corporativas:
1.  **Cold Start Optimization**: Cloud Run extrae imágenes de Artifact Registry desde la misma red troncal de Google, reduciendo los tiempos de arranque (esencial para el escalado de 0 a $N$).
2.  **Escaneo de Vulnerabilidades (CVEs)**: Artifact Registry escanea automáticamente los binarios y dependencias Python por brechas de seguridad conocidas.
3.  **Identity and Access Management (IAM)**: Aisla la imagen de la API, requiriendo permisos explícitos para empujar código (`roles/artifactregistry.writer`) o desplegar contenedores (`roles/artifactregistry.reader`), previniendo accesos no autorizados al código propietario.

## Verificación
*   Revisión estática del `Dockerfile` validando las sentencias `FROM`.
*   Ejecución sintáctica del `build_and_push.sh` y verificación de `docker daemon` a través de pruebas unitarias locales.
