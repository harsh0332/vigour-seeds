import hmac
import hashlib
import json
import time
from typing import Optional
from fastapi import APIRouter, Request, Response, status, Header, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse
from app.core.config import settings
from app.core.logging import logger
from app.whatsapp.parser import whatsapp_parser
from app.flows.router import conversation_router
from app.core.middleware import rate_limiter
from app.core.errors import handle_unhandled_error
from app.services.metrics import metrics_service

router = APIRouter()

async def process_webhook_payload(payload: dict) -> None:
    try:
        from app.services.attribution import attribute_message_payload
        await attribute_message_payload(payload)
        
        messages = await whatsapp_parser.parse_webhook_payload(payload)
        for msg in messages:
            try:
                await conversation_router.route_message(msg)
            except Exception as routing_error:
                await handle_unhandled_error(routing_error, msg.from_phone if msg else None)
    except Exception as parsing_error:
        # Attempt to extract the sender phone number from the payload to notify them
        phone = None
        try:
            phone = payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
        except Exception:
            pass
        await handle_unhandled_error(parsing_error, phone)

@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    challenge: str = Query(None, alias="hub.challenge"),
    verify_token: str = Query(None, alias="hub.verify_token")
):
    logger.info("WhatsApp webhook verification request received", extra={"mode": mode, "verify_token": verify_token})
    
    if mode == "subscribe" and verify_token == settings.META_VERIFY_TOKEN:
        logger.info("Webhook verification successful")
        try:
            return str(int(challenge))
        except (ValueError, TypeError):
            return challenge
    else:
        logger.warning("Webhook verification failed. Token mismatch.")
        return Response(content="Verification token mismatch", status_code=status.HTTP_403_FORBIDDEN)

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256")
):
    start_time = time.time()
    metrics_service.increment_msgs_in()
    
    # Read raw body
    body_bytes = await request.body()
    
    # Verify signature
    if not x_hub_signature_256:
        logger.warning("Missing X-Hub-Signature-256 header")
        duration = time.time() - start_time
        metrics_service.record_response_time(duration)
        return Response(content="Signature missing", status_code=status.HTTP_403_FORBIDDEN)
        
    if not x_hub_signature_256.startswith("sha256="):
        logger.warning("Signature must start with sha256=")
        duration = time.time() - start_time
        metrics_service.record_response_time(duration)
        return Response(content="Invalid signature format", status_code=status.HTTP_403_FORBIDDEN)
        
    received_sig = x_hub_signature_256.split("sha256=")[1].strip()
    
    # Calculate HMAC SHA256 signature
    app_secret_bytes = settings.META_APP_SECRET.encode("utf-8")
    expected_sig = hmac.new(app_secret_bytes, body_bytes, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(received_sig, expected_sig):
        logger.warning("Signature verification failed", extra={"received": received_sig, "expected": expected_sig})
        duration = time.time() - start_time
        metrics_service.record_response_time(duration)
        return Response(content="Signature verification failed", status_code=status.HTTP_403_FORBIDDEN)
        
    # Signature valid, parse JSON
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        logger.error("Failed to parse webhook JSON payload", extra={"error": str(e)})
        duration = time.time() - start_time
        metrics_service.record_response_time(duration)
        return Response(content="Invalid JSON", status_code=status.HTTP_400_BAD_REQUEST)
        
    logger.info("Webhook message received", extra={"payload": payload})
    
    # Extract phone number for rate-limiting
    phone = None
    try:
        phone = payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
    except Exception:
        pass
        
    # Anti-spam rate limiting: soft cap and ignore floods
    if phone and rate_limiter.is_rate_limited(phone):
        logger.warning("Rate limit hit, ignoring payload silently", extra={"phone": phone})
        duration = time.time() - start_time
        metrics_service.record_response_time(duration)
        # Always return 200 OK to Meta to prevent retry storms
        return Response(content="EVENT_RECEIVED", status_code=status.HTTP_200_OK)
        
    # Mark message as read immediately if typing indicator / first reply speed flag is enabled
    import os
    if os.environ.get("ENABLE_TYPING_INDICATOR", "false").lower() == "true":
        try:
            msg_id = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
            from app.whatsapp.client import whatsapp_client
            background_tasks.add_task(whatsapp_client.mark_as_read, msg_id)
        except Exception:
            pass

    # Queue processing to background to respond to Meta immediately
    background_tasks.add_task(process_webhook_payload, payload)
    
    duration = time.time() - start_time
    metrics_service.record_response_time(duration)
    return Response(content="EVENT_RECEIVED", status_code=status.HTTP_200_OK)

