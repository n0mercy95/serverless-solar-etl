"""
interfaces/dependencies.py — Inyección de Dependencias de FastAPI
===================================================================
Provee objetos singleton u otras dependencias (ej. clientes de red)
para reciclar conexiones de red dentro de los request handlers.
"""

from __future__ import annotations

from fastapi import Request
from google.cloud import bigquery


def get_bq_client(request: Request) -> bigquery.Client:
    """Extrae el cliente BigQuery instanciado en el arranque de la app.
    
    Esta dependencia permite reciclar las conexiones HTTP nativas
    usando la misma instancia `Client` de Google Cloud, ahorrando
    costos de latencia por handshake (TLS/TCP) en cada petición.
    """
    return request.app.state.bq_client
