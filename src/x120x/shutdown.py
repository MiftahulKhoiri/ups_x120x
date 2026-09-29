"""Aksi shutdown. Default proyek ini hanya mencatat log (aman untuk development)."""
from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)


class LogOnlyShutdown:
    """Tidak mematikan apa pun; hanya menulis log."""

    def schedule(self, minutes: int) -> None:
        log.warning("[log-only] shutdown akan dijadwalkan dalam %d menit "
                    "(jalankan dengan --shutdown untuk benar-benar mematikan)", minutes)

    def cancel(self) -> None:
        log.info("[log-only] jadwal shutdown dibatalkan")


class SystemShutdown:
    """Memakai perintah `shutdown` milik sistem (butuh root atau sudo tanpa password)."""

    def _prefix(self) -> list:
        return [] if os.geteuid() == 0 else ["sudo", "-n"]

    def schedule(self, minutes: int) -> None:
        msg = f"Daya UPS hampir habis, sistem mati dalam {minutes} menit."
        subprocess.run([*self._prefix(), "shutdown", "-P", f"+{minutes}", msg], check=True)
        log.warning(msg)

    def cancel(self) -> None:
        subprocess.run([*self._prefix(), "shutdown", "-c", "Listrik pulih, shutdown dibatalkan."],
                       check=False)
        log.info("Shutdown dibatalkan karena listrik pulih")
