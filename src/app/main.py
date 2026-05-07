from fastapi import FastAPI
import logging

# Configure basic structured logging for the entrypoint test
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PVOD Serverless Solar ETL API",
    description="API for accessing aggregated metrics from the Photovoltaic Power Output Dataset",
    version="1.0.0"
)

@app.get("/")
async def root():
    logger.info("Root endpoint called.")
    return {"message": "PVOD Solar ETL API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
