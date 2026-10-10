"""Local file repository: source CSVs -> bronze -> silver in memory; ops state as JSONL files."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from src.ingestion.bronze import SOURCE_FILES, ingest_directory
from src.repositories.base import OPS_TABLES, ServicingRepository, decode_record, encode_record
from src.transformations.silver import SilverDataset, build_silver


class LocalRepository(ServicingRepository):
    backend = "local"

    def __init__(self, settings, source_dir: str | Path | None = None, state_dir: str | Path | None = None):
        self.settings = settings
        landing = settings.path("landing_dir")
        has_landing = all((landing / f).exists() for f in SOURCE_FILES.values())
        self.source_dir = Path(source_dir) if source_dir else (landing if has_landing else settings.path("generated_dir"))
        self.state_dir = Path(state_dir) if state_dir else settings.path("processed_dir") / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, dict[tuple, dict]] | None = None

    def load_source_silver(self) -> SilverDataset:
        return build_silver(ingest_directory(self.source_dir), self.settings)

    def _path(self, table: str) -> Path:
        return self.state_dir / f"{table}.jsonl"

    def _load_cache(self) -> dict[str, dict[tuple, dict]]:
        if self._cache is None:
            self._cache = {}
            for table, (keys, _) in OPS_TABLES.items():
                rows: dict[tuple, dict] = {}
                path = self._path(table)
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            rec = json.loads(line)
                            rows[tuple(rec.get(k) for k in keys)] = rec
                self._cache[table] = rows
        return self._cache

    def load_ops(self) -> dict[str, list[dict]]:
        with self._lock:
            cache = self._load_cache()
            return {t: [decode_record(r) for r in rows.values()] for t, rows in cache.items()}

    def upsert(self, table: str, records: list[dict]) -> None:
        if not records:
            return
        keys, _ = OPS_TABLES[table]
        with self._lock:
            cache = self._load_cache()
            for record in records:
                enc = encode_record(table, record)
                cache[table][tuple(enc.get(k) for k in keys)] = enc
            with open(self._path(table), "w", encoding="utf-8") as fh:
                for rec in cache[table].values():
                    fh.write(json.dumps(rec) + "\n")

    def reset_ops(self) -> None:
        with self._lock:
            for table in OPS_TABLES:
                path = self._path(table)
                if path.exists():
                    path.unlink()
            self._cache = None
