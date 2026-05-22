# Despliegue de API PVOD en Google Cloud Run

Aquí tienes exactamente los pasos recomendados que debes seguir a continuación para construir y desplegar tu API:

1. Confirmar el proyecto por defecto en la CLI
Aunque la terminal te indicó que el proyecto actual es serverless-solar-etl, es buena práctica asegurarlo explícitamente en la configuración de la CLI:

gcloud config set project serverless-solar-etl

2. Verificar Prerrequisitos en GCP
Antes de ejecutar los scripts de despliegue, necesitas asegurarte de que ciertos recursos y servicios estén habilitados/creados en tu consola de Google Cloud:

A. Habilitar las APIs necesarias en GCP
Si es la primera vez que despliegas en este proyecto, activa los servicios de Artifact Registry, Cloud Run y Secret Manager ejecutando:

gcloud services enable artifactregistry.googleapis.com \
                       run.googleapis.com \
                       secretmanager.googleapis.com

B. Crear el Repositorio en Artifact Registry
El script scripts/build_and_push.sh intentará subir la imagen a un repositorio de Docker llamado solar-etl-repo en la región us-central1 (por defecto). Si no lo has creado aún, puedes crearlo con este comando:

gcloud artifacts repositories create solar-etl-repo \
    --repository-format=docker \
    --location=us-central1 \
    --description="Repositorio Docker para PVOD API"

C. Configurar Secretos en Secret Manager (Si aplica)
Tu script deploy_to_cloud_run.sh busca dos secretos en Secret Manager: bq_dataset_id y bq_table_id.

Opción A (Recomendada): Crea los secretos en GCP:

echo -n "solar_etl_dataset" | gcloud secrets create bq_dataset_id --data-file=-
echo -n "pvod_metrics" | gcloud secrets create bq_table_id --data-file=-

Opción B: Si prefieres no usar Secret Manager por ahora y pasarlos como variables normales de entorno, deberás editar el archivo scripts/deploy_to_cloud_run.sh para remover la línea --set-secrets ... y agregarlos en --set-env-vars ....

3. Compilar y Desplegar
Una vez listo lo anterior, asegúrate de que Docker esté abierto y ejecutándose en tu Mac, y luego corre los scripts en orden desde la raíz del proyecto:

Construir y subir la imagen de Docker a GCP:

chmod +x scripts/build_and_push.sh
./scripts/build_and_push.sh

Desplegar el contenedor en Cloud Run:

chmod +x scripts/deploy_to_cloud_run.sh
./scripts/deploy_to_cloud_run.sh
