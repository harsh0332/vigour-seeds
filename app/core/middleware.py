import time
from collections import deque
from typing import Dict
from app.core.logging import logger

class PhoneRateLimiter:
    def __init__(self, limit: int = 20, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.history: Dict[str, deque] = {}

    def is_rate_limited(self, phone: str) -> bool:
        """
        Check if the phone number has exceeded the limit in the window.
        Returns True if rate-limited (ignore/discard message), False otherwise.
        """
        if not phone:
            return False
            
        now = time.time()
        if phone not in self.history:
            self.history[phone] = deque()

        queue = self.history[phone]
        # Clean timestamps older than the sliding window
        while queue and queue[0] < now - self.window_seconds:
            queue.popleft()

        if len(queue) >= self.limit:
            logger.warning(
                "Phone number rate-limited (flood detected)",
                extra={"phone": phone, "msg_count_in_window": len(queue), "limit": self.limit}
            )
            return True

        queue.append(now)
        return False

# Global instance of rate limiter (20 messages per minute)
rate_limiter = PhoneRateLimiter(limit=20, window_seconds=60)
