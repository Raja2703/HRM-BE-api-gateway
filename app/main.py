from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import os
import logging
from fastapi.responses import JSONResponse
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICES = {
    "/api/v1/auth": os.getenv("AUTH_SERVICE_URL", "http://localhost:7071"),
    "/api/v1/billing": os.getenv("BILLING_SERVICE_URL", "http://localhost:7072"),
    "/api/v1/tenants": os.getenv("TENANT_SERVICE_URL", "http://localhost:7073"),
    "/api/v1/employees": os.getenv("EMPLOYEE_SERVICE_URL", "http://localhost:7074"),
    "/api/v1/superadmin": os.getenv("SUPERADMIN_SERVICE_URL", "http://localhost:7075"),
    "/api/v1/notifications": os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:7076"),
    "/api/v1/orchestrate": os.getenv("ORCHESTRATOR_SERVICE_URL", "http://localhost:8002"),
    "/api/v1/jobs": os.getenv("JOB_SERVICE_URL", "http://localhost:7078"),
    "/api/v1/cms": os.getenv("CMS_SERVICE_URL", "http://localhost:7080"),
    "/api/v1/candidates": os.getenv("RESUME_PARSING_SERVICE_URL", "http://localhost:8003"),
}

@app.get("/health")
async def health_check():
    return JSONResponse(status_code=200, content={"status": "ok", "service": "api_gateway-service"})


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def gateway(request: Request, path: str):
    requested_path = f"/{path}"
    target_service_url = None
    
    # Sort keys by length descending to match most specific prefix first
    for prefix in sorted(SERVICES.keys(), key=len, reverse=True):
        if requested_path.startswith(prefix):
            target_service_url = SERVICES[prefix]
            break
            
    if not target_service_url:
        logger.warning(f"No service mapping found for path: {requested_path}")
        raise HTTPException(status_code=404, detail="Service not found for the requested path")

    # Transform path
    if "/api/v1/cms" in requested_path:
        # For CMS (Azure Function), strip /api/v1/cms and prepend /api
        target_path = requested_path.replace("/api/v1/cms", "/api", 1)
    elif not requested_path.startswith("/api/v1/"):
        # If the frontend stripped /api/v1, add it back for the microservice
        target_path = f"/api/v1{requested_path}"
    else:
        # PASS THROUGH EXACTLY AS IS (Candidates, Orchestrator, etc.)
        target_path = requested_path
    
    target_url = f"{target_service_url}{target_path}"
    
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"
        
    logger.info(f"Routing {request.method} {requested_path} -> {target_url}")

    # Forward the request
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            body = await request.body()
            
            # Exclude headers that cause issues when proxying
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("content-length", None)
            
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )
            
            # Exclude response headers that should not be forwarded
            resp_headers = dict(response.headers)
            resp_headers.pop("content-encoding", None)
            resp_headers.pop("content-length", None)

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=resp_headers
            )
        except httpx.RequestError as e:
            logger.error(f"Error communicating with {target_url}: {e}")
            raise HTTPException(status_code=502, detail=f"Bad Gateway: Unable to reach upstream service.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
