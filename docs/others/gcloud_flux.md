# Flujo de GCP - Ejecución Manual del ETL

Si prefieres ejecutar el pipeline ETL alojado en Cloud Run manualmente desde la terminal (en lugar de hacerlo mediante Cloud Scheduler o la consola web de Google Cloud), puedes utilizar `curl` pasándole tu token de identidad de `gcloud` para pasar la autenticación IAM.

### Comando para ejecutar el ETL

```bash
# Reemplaza la URL por la de tu servicio Cloud Run
URL="https://pvod-solar-api-264931673910.us-central1.run.app"

curl -X POST "${URL}/api/v1/etl/run" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

### ¿Qué sucede al ejecutar esto?
1. Se valida el token Bearer contra IAM de Google Cloud.
2. Si tienes permisos (ej. `roles/run.invoker`), el endpoint FastAPI dispara asincrónicamente el proceso ETL.
3. Se limpian los gráficos `plots/` antiguos del bucket.
4. Se procesan, limpian y perfilan los datos.
5. Se generan y suben los nuevos gráficos de dispersión.
6. La data limpia "Gold" se serializa en un Parquet particionado y se hace load a BigQuery.
