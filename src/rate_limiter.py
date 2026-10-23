import time
import random
import threading
import logging

logger = logging.getLogger("VintedBot.RateLimiter")

class VintedRateLimiter:
    """Régulateur de débit garantissant un espacement minimal strict (>= 3.0s) entre requêtes sur un même domaine avec priorités."""

    def __init__(self, min_interval_seconds: float = 3.0):
        # Strictement >= 3.0s (Phase 3.3 : "Ne descends jamais sous ce seuil")
        self.min_interval = max(3.0, float(min_interval_seconds))
        self.last_request_time = 0.0
        self.paused_until = 0.0
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.high_priority_waiting = 0

    def pause(self, duration_seconds: float = 45.0):
        """Met en pause uniquement ce domaine en cas de 429 (Phase 3.3)."""
        with self.lock:
            self.paused_until = max(self.paused_until, time.time() + duration_seconds)
            logger.warning(f"Régulateur de débit : pause de {duration_seconds}s activée.")
            self.condition.notify_all()

    def is_paused(self) -> bool:
        """Indique si ce domaine est actuellement en pause 429."""
        with self.lock:
            return time.time() < self.paused_until

    def wait_for_token(self, priority: str = "low"):
        """
        Bloque si nécessaire pour respecter le délai minimal strict (>=3.0s) et la pause 429.
        Si priority == 'high', passe avant les requêtes 'low' en attente.
        """
        with self.lock:
            if priority == "high":
                self.high_priority_waiting += 1
            try:
                while True:
                    # Si priorité basse et qu'une requête haute priorité attend, laisser la priorité
                    if priority != "high" and self.high_priority_waiting > 0:
                        self.condition.wait(timeout=0.2)
                        continue

                    now = time.time()
                    if now < self.paused_until:
                        pause_wait = self.paused_until - now
                        self.condition.wait(timeout=min(pause_wait, 1.0))
                        continue

                    elapsed = now - self.last_request_time
                    target_interval = self.min_interval + random.uniform(0.1, 0.4)
                    if elapsed < target_interval:
                        sleep_time = target_interval - elapsed
                        self.condition.wait(timeout=min(sleep_time, 0.5))
                        continue

                    # Jeton accordé
                    self.last_request_time = time.time()
                    break
            finally:
                if priority == "high":
                    self.high_priority_waiting -= 1
                self.condition.notify_all()
