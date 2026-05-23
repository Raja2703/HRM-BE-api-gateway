import os
import json
import logging
import asyncio
from fastapi import Request
from jose import jwt
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage

logger = logging.getLogger(__name__)

async def publish_audit_event(request: Request, body: bytes, response_status: int):
    # Only audit state-changing requests
    if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
        return

    # Skip failed requests (or you can log them based on your needs)
    if response_status >= 400:
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return

    token = auth_header.split(" ", 1)[1]
    
    try:
        # Decode without verification because API Gateway trusts the microservices to verify
        # or we just want to extract claims for logging purposes
        payload = jwt.get_unverified_claims(token)
    except Exception as e:
        logger.warning(f"Could not parse JWT for audit: {e}")
        return

    # Extract user ID
    actor_id = payload.get("sub") or payload.get("preferred_username") or "unknown"
    actor_role = "user"
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    if "superadmin" in realm_roles:
        actor_role = "superadmin"
    elif "tenant-admin" in realm_roles:
        actor_role = "tenant-admin"

    # Resolve tenant_id
    org_claim = payload.get("organization")
    tenant_id = None
    if isinstance(org_claim, dict):
        for _, org_info in org_claim.items():
            if isinstance(org_info, dict) and "id" in org_info:
                tenant_id = org_info["id"]
                break
    elif isinstance(org_claim, list) and org_claim:
        tenant_id = org_claim[0]
    elif isinstance(org_claim, str):
        tenant_id = org_claim
    if not tenant_id:
        tenant_id = payload.get("tenant_id")
        
    if not tenant_id:
        return

    # Determine action and entity
    path_parts = request.url.path.strip("/").split("/")
    
    entity_type = path_parts[2] if len(path_parts) > 2 else "unknown"
    entity_id = path_parts[3] if len(path_parts) > 3 else "unknown"
    
    action_type = f"{request.method}_{entity_type}".upper()

    delta = None
    if body:
        try:
            delta = json.loads(body)
        except:
            delta = body.decode('utf-8', errors='ignore')

    audit_event = {
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "actor_ip": request.client.host if request.client else "unknown",
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "delta": delta
    }

    conn_str = os.getenv("SERVICE_BUS_CONNECTION_STRING")
    if not conn_str:
        logger.error("No SERVICE_BUS_CONNECTION_STRING for audit logging")
        return

    try:
        async with ServiceBusClient.from_connection_string(conn_str) as client:
            sender = client.get_queue_sender(queue_name="evt.audit.log")
            async with sender:
                msg = ServiceBusMessage(json.dumps(audit_event))
                await sender.send_messages(msg)
                logger.info(f"Published audit event for {action_type} on {entity_type}/{entity_id}")
    except Exception as e:
        logger.error(f"Failed to publish audit event: {e}")
