#!/usr/bin/env bash
# scripts/build_and_push.sh
# Construye la imagen Docker multi-stage y la sube a Google Artifact Registry.

set -e

# Configuración por defecto (reemplazar con los valores reales del proyecto)
PROJECT_ID=${GCP_PROJECT_ID:-"tu-proyecto-gcp"}
REGION=${GCP_REGION:-"us-central1"}
REPO_NAME=${AR_REPO_NAME:-"solar-etl-repo"}
IMAGE_NAME="pvod-api"
TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "latest")

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

echo "=========================================================="
echo "🚀 Iniciando Build & Push a Google Artifact Registry"
echo "=========================================================="
echo "Project ID : ${PROJECT_ID}"
echo "Region     : ${REGION}"
echo "Repository : ${REPO_NAME}"
echo "Image URI  : ${IMAGE_URI}"
echo "=========================================================="

# 1. Construir la imagen Docker (Multi-stage)
echo -e "\n[1/3] Construyendo imagen Docker localmente..."
docker build -t ${IMAGE_URI} .

# 2. Autenticar Docker con Artifact Registry
echo -e "\n[2/3] Autenticando con Google Artifact Registry..."
# Requiere que gcloud esté instalado y autenticado
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# 3. Subir la imagen
echo -e "\n[3/3] Subiendo imagen a Artifact Registry..."
docker push ${IMAGE_URI}

echo -e "\n✅ ¡Proceso completado con éxito!"
echo "La imagen está lista para ser desplegada en Cloud Run."
