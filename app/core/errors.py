import os
import random
import asyncio
import traceback
from datetime import datetime
from typing import Optional, Callable, Any


from app.core.logging import logger

# --- Custom Exception Classes ---

class MetaApiException(Exception):
    """Base exception for Meta WhatsApp API errors."""
    pass

class MetaRateLimitException(MetaApiException):
    """Raised on Meta HTTP 429 rate limit errors."""
    pass

class MetaServerException(MetaApiException):
    """Raised on Meta HTTP 5xx server errors."""
    pass

class MetaAuthException(MetaApiException):
    """Raised on Meta HTTP 401/403 authorization/token expiry errors."""
    pass

class AICircuitBreakerOpenException(Exception):
    """Raised when the AI provider's circuit breaker is OPEN."""
    pass


# --- Circuit Breaker ---

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 15.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_state_change = datetime.utcnow()

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_state_change = datetime.utcnow()

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.last_state_change = datetime.utcnow()
            logger.error(
                "Circuit breaker tripped to OPEN state!",
                extra={"failure_threshold": self.failure_threshold}
            )

    def allow_request(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            elapsed = (datetime.utcnow() - self.last_state_change).total_seconds()
            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                self.last_state_change = datetime.utcnow()
                logger.info("Circuit breaker entered HALF_OPEN state, testing next request")
                return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return False

# Shared AI Circuit Breaker instance
ai_circuit_breaker = CircuitBreaker()


# --- Retry with Backoff ---

async def retry_with_backoff(
    func: Callable[..., Any],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    **kwargs: Any
) -> Any:
    """Execute a function with exponential backoff and jitter, handling Meta and general errors."""
    for attempt in range(attempts):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except MetaAuthException as auth_err:
            # Abort immediately on auth failure (token expired)
            logger.error("Critical authentication failure, aborting retries", extra={"error": str(auth_err)})
            raise auth_err
        except (MetaRateLimitException, MetaServerException, Exception) as e:
            if attempt == attempts - 1:
                logger.error("All retry attempts failed", extra={"attempts": attempts, "error": str(e)})
                raise e
            
            # Calculate exponential delay with jitter
            delay = min(max_delay, base_delay * (2.0 ** attempt))
            jitter = random.uniform(0, 0.5 * delay)
            sleep_time = delay + jitter
            
            logger.warning(
                "Request failed. Retrying...",
                extra={"attempt": attempt + 1, "next_retry_in": sleep_time, "error": str(e)},
                exc_info=True
            )
            await asyncio.sleep(sleep_time)


# --- Global Error Handler ---

def redact_phone(phone: Optional[str]) -> str:
    """Obfuscate phone number digits for logging privacy."""
    if not phone:
        return "UNKNOWN"
    phone_str = str(phone)
    if len(phone_str) <= 6:
        return "***"
    return phone_str[:3] + "***" + phone_str[-3:]

async def handle_unhandled_error(exc: Exception, phone: Optional[str]) -> None:
    """Global unhandled exception dispatcher."""
    redacted_phone = redact_phone(phone)
    logger.critical(
        "Unhandled error occurred in webhook processing flow",
        extra={"phone_redacted": redacted_phone, "error": str(exc)},
        exc_info=exc
    )
    
    # 1. Increment AI error metric if relevant
    if isinstance(exc, (AICircuitBreakerOpenException, Exception)) and "ai" in str(exc).lower():
        try:
            from app.services.metrics import metrics_service
            metrics_service.increment_ai_errors()
        except Exception:
            pass

    # 2. Config-driven Alert Channel
    alert_channel = os.environ.get("ALERT_CHANNEL", "log").lower()
    alert_msg = f"🚨 *SYSTEM ALERT: Unhandled Error*\nUser: {redacted_phone}\nError: {str(exc)}"
    
    if alert_channel == "webhook":
        alert_url = os.environ.get("ALERT_WEBHOOK_URL")
        if alert_url:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    await client.post(alert_url, json={"text": alert_msg})
            except Exception as alert_err:
                logger.error("Failed to dispatch webhook alert", extra={"error": str(alert_err)})
    else:
        # Default log alert
        logger.error(f"CRITICAL SYSTEM ALERT DISPATCHED: {alert_msg}")

    if phone:
        try:
            from app.whatsapp.client import whatsapp_client
            await whatsapp_client.send_text(phone, "तकनीकी समस्या आई है 🙏 कृपया थोड़ी देर बाद पुनः प्रयास करें।")
        except Exception as send_err:
            logger.error(
                "Failed to send fallback message to user",
                extra={"phone_redacted": redacted_phone, "error": str(send_err)}
            )
