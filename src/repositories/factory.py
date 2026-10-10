"""Repository selection."""
from __future__ import annotations

import logging

from src.repositories.base import ServicingRepository
from src.repositories.local import LocalRepository

log = logging.getLogger(__name__)


def create_repository(settings, backend: str | None = None) -> ServicingRepository:
    backend = (backend or settings.backend or "local").lower()
    if backend == "databricks":
        from src.repositories.databricks_sql import DatabricksSqlRepository
        return DatabricksSqlRepository(settings)
    return LocalRepository(settings)
