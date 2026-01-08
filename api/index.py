"""
Main API Entrypoint - FastAPI application
File path: api/index.py -> becomes /api endpoint
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="StreamGobhar API", version="1.0.0")


@app.get("/")
async def root():
    """API root endpoint - shows available endpoints"""
    return JSONResponse({
        "status": "ok",
        "message": "StreamGobhar API - Telegram File Streaming Service",
        "version": "1.0.0",
        "endpoints": {
            "webhook": "/api/webhook",
            "stream": "/api/stream/{msg_id}",
            "download": "/api/download/{msg_id}"
        }
    })


@app.get("/health")
async def health():
    """Health check endpoint"""
    return JSONResponse({"status": "healthy"})
