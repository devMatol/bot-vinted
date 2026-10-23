import os
import sys
import logging
import atexit

logger = logging.getLogger("VintedBot.Lock")

class ProcessLock:
    """
    Empêche l'exécution simultanée de plusieurs instances du bot via bot.lock.
    Utilise le verrouillage non-bloquant au niveau de l'OS (msvcrt sous Windows, fcntl sous Unix).
    """

    def __init__(self, lock_file: str = "bot.lock"):
        self.lock_file = lock_file
        self.file_handle = None

    def acquire(self) -> bool:
        """Tente d'acquérir le verrou exclusif non-bloquant."""
        try:
            self.file_handle = open(self.lock_file, "a+", encoding="utf-8")
            if os.name == "nt":
                import msvcrt
                self.file_handle.seek(0)
                msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Écrire les métadonnées de l'instance
            self.file_handle.seek(0)
            self.file_handle.truncate(0)
            self.file_handle.write(f"PID: {os.getpid()}\n")
            self.file_handle.flush()
            atexit.register(self.release)
            return True
        except (IOError, OSError):
            if self.file_handle:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
                self.file_handle = None
            return False

    def release(self):
        """Libère le verrou et nettoie le fichier."""
        if self.file_handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.file_handle.close()
            except Exception:
                pass
            self.file_handle = None

        if os.path.exists(self.lock_file):
            try:
                os.remove(self.lock_file)
            except Exception:
                pass
