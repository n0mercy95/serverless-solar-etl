# Cómo Usar la API — Ejecución Local y en la Nube

## Contexto Importante

Después de ejecutar los scripts de despliegue (`./build_and_push.sh` y `./deploy_to_cloud_run.sh`) desde la carpeta scripts,
tu API **queda activa únicamente en Google Cloud Run**, no en tu máquina local.

Esto significa que si intentas hacer una petición a `http://localhost:8080/...` desde Postman
u otra herramienta, recibirás un error como:

```
Error: connect ECONNREFUSED 127.0.0.1:8080
```

Eso ocurre porque **no hay ningún servidor escuchando en el puerto 8080 de tu máquina**.
El despliegue a Cloud Run sube tu imagen Docker a los servidores de Google; no levanta nada localmente.

---

## Opción 1 — Usar la URL de Cloud Run (Producción)

Si solo quieres probar el servicio ya desplegado, utiliza la URL pública que Cloud Run
te proporcionó al final del script `deploy_to_cloud_run.sh`.

**Ejemplo en Postman:**
```
POST https://pvod-solar-api-264931673910.us-central1.run.app/api/v1/etl/run
```

**Ejemplo con cURL:**
```bash
curl -X POST "https://pvod-solar-api-264931673910.us-central1.run.app/api/v1/etl/run"
```

> **Nota:** Reemplaza la URL de ejemplo por la que tu propio despliegue te haya generado.

---

## Opción 2 — Levantar el Servidor Localmente con Uvicorn (Desarrollo)

Si necesitas probar cambios en tiempo real sin tener que reconstruir la imagen Docker cada vez,
puedes levantar la API de FastAPI directamente en tu máquina usando **Uvicorn**.

### Pasos

1.  **Activar el entorno virtual** (desde la raíz del proyecto):
    ```bash
    source .venv/bin/activate
    ```

2.  **Ejecutar Uvicorn** apuntando al objeto `app` dentro de `main.py`:
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
    ```

    | Flag        | Descripción                                                                 |
    | ----------- | --------------------------------------------------------------------------- |
    | `app.main:app` | Ruta al objeto FastAPI: módulo `app.main`, variable `app`.               |
    | `--host 0.0.0.0` | Acepta conexiones desde cualquier interfaz (no solo `127.0.0.1`).     |
    | `--port 8080`    | Puerto en el que escuchará el servidor (igual que en Cloud Run).       |
    | `--reload`       | Recarga automáticamente al detectar cambios en el código (dev only).   |

3.  **Verificar que el servidor arrancó.** Deberías ver algo como:
    ```
    INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
    INFO:     Started reloader process [xxxxx]
    ```

4.  **Ahora sí** puedes hacer peticiones a `http://localhost:8080/...` desde Postman:
    ```
    POST http://localhost:8080/api/v1/etl/run
    ```

> **Importante:** El comando `uvicorn` se debe ejecutar desde la carpeta `src/`,
> ya que el módulo se resuelve como `app.main` (es decir, `src/app/main.py`).
>
> ```bash
> cd src
> uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
> ```

---

## Resumen Rápido

| Escenario                   | Comando / Acción                                                     |
| --------------------------- | -------------------------------------------------------------------- |
| **Probar en producción**    | Usar la URL de Cloud Run directamente (`https://...run.app/...`)     |
| **Probar localmente**       | `cd src && uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload`|
| **Reconstruir y desplegar** | `./build_and_push.sh` → `./deploy_to_cloud_run.sh`                  |
