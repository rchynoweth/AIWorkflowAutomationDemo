"""Process-wide service singleton shared by the API and the in-process Streamlit client."""
from __future__ import annotations

import logging
import threading

from src.config.settings import get_settings
from src.repositories.factory import create_repository
from src.services.servicing_service import LoanServicingService

log = logging.getLogger(__name__)
_lock = threading.Lock()
_service: LoanServicingService | None = None
_error: str | None = None


def get_service() -> LoanServicingService:
    global _service, _error
    if _service is not None:
        return _service
    with _lock:
        if _service is None:
            settings = get_settings()
            try:
                service = LoanServicingService(settings, create_repository(settings)).load()
            except Exception as exc:  # noqa: BLE001
                if settings.backend == "databricks":
                    _error = f"Databricks backend unavailable ({type(exc).__name__}: {str(exc)[:200]}); using local."
                    log.exception("Falling back to local repository")
                    service = LoanServicingService(settings, create_repository(settings, "local")).load()
                else:
                    raise
            _service = service
    return _service


def startup_warning() -> str | None:
    return _error


def set_service(service: LoanServicingService | None) -> None:
    """Testing hook."""
    global _service
    _service = service
