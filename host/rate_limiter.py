"""
Per-user rate limiting for chat commands.
Prevents spam and rapid-fire abuse.
"""

import time
import threading
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_per_minute: int = 12, cooldown: float = 1.0):
        self.max_per_minute = max_per_minute
        self.cooldown = cooldown
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._last_command: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_allowed(self, user: str) -> bool:
        now = time.time()
        with self._lock:
            # Per-command cooldown
            last = self._last_command.get(user, 0)
            if now - last < self.cooldown:
                return False

            # Sliding window rate limit
            window = [t for t in self._timestamps[user] if now - t < 60]
            if len(window) >= self.max_per_minute:
                return False

            window.append(now)
            self._timestamps[user] = window
            self._last_command[user] = now
            return True

    def reset(self, user: str) -> None:
        with self._lock:
            self._timestamps.pop(user, None)
            self._last_command.pop(user, None)
