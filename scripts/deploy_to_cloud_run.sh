#!/usr/bin/env bash
# scripts/deploy_to_cloud_run.sh
# Despliega la API Serverless PVOD en Google Cloud Run.
# Asegura auto-escalado a cero y utiliza Secret Manager para credenciales.

set -e

# Configuración por defecto (reemplazar con los valores reales)
PROJECT_ID=${GCP_PROJECT_ID:-"tu-proyecto-gcp"}
REGION=${GCP_REGION:-"us-central1"}
REPO_NAME=${AR_REPO_NAME:-"solar-etl-repo"}
IMAGE_NAME="pvod-api"
TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "latest")
SERVICE_NAME="pvod-solar-api"

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${TAG}"

echo "=========================================================="
echo "☁️ Iniciando despliegue a Google Cloud Run"
echo "=========================================================="
echo "Project ID : ${PROJECT_ID}"
echo "Region     : ${REGION}"
echo "Service    : ${SERVICE_NAME}"
echo "Image URI  : ${IMAGE_URI}"
echo "=========================================================="

# Comando de despliegue a Cloud Run
# Nota sobre Secret Manager: Asegúrate de tener los secretos creados en GCP.
# Reemplaza 'tus_secretos' por los nombres correctos si usas nombres diferentes.
# --allow-unauthenticated permite peticiones públicas de prueba.
# --min-instances 0 asegura el auto-escalado a cero para reducir costos.

gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_URI} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --allow-unauthenticated \
    --port 8080 \
    --min-instances 0 \
    --max-instances 5 \
    --cpu 1 \
    --memory 512Mi \
    --set-env-vars ENVIRONMENT="production",LOG_LEVEL="INFO" \
    --set-env-vars GCP_PROJECT_ID=${PROJECT_ID} \
    --set-secrets BQ_DATASET_ID=bq_dataset_id:latest,BQ_TABLE_ID=bq_table_id:latest,GOOGLE_APPLICATION_CREDENTIALS=gcp_credentials:latest

echo -e "\n✅ ¡Despliegue ejecutado!"
echo "Tu API Serverless está operativa. Utiliza la URL que Cloud Run proveyó arriba para realizar pruebas."
