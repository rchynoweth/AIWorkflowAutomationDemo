"""Spark repository used by Databricks notebooks (same interface as the SQL-warehouse repository)."""
from __future__ import annotations

import pandas as pd

from src.repositories.base import OPS_TABLES, ServicingRepository, decode_record, encode_record
from src.repositories.databricks_sql import SILVER_SOURCE_COLUMNS
from src.transformations.silver import SilverDataset, build_silver


class SparkRepository(ServicingRepository):
    backend = "databricks"

    def __init__(self, spark, settings, catalog: str | None = None, schema: str | None = None):
        self.spark = spark
        self.settings = settings
        self.catalog = catalog or settings.catalog
        self.schema = schema or settings.schema
        self._ready = False

    def fq(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{table}`"

    def ensure_ops_tables(self) -> None:
        if self._ready:
            return
        for table, (_, columns) in OPS_TABLES.items():
            cols = ", ".join(f"`{c}` STRING" for c in columns)
            self.spark.sql(f"CREATE TABLE IF NOT EXISTS {self.fq(table)} ({cols}) USING DELTA "
                           "COMMENT 'Loan Servicing Intelligence operational state (synthetic demonstration)'")
        self._ready = True

    def read_strings(self, table: str, columns: list[str]) -> pd.DataFrame:
        select = ", ".join(f"CAST(`{c}` AS STRING) AS `{c}`" for c in columns)
        return self.spark.sql(f"SELECT {select} FROM {self.fq(table)}").toPandas().fillna("")

    def load_source_silver(self) -> SilverDataset:
        frames = {bronze: self.read_strings(silver, cols) for bronze, (silver, cols) in SILVER_SOURCE_COLUMNS.items()}
        return build_silver(frames, self.settings)

    def load_ops(self) -> dict[str, list[dict]]:
        self.ensure_ops_tables()
        out = {}
        for table in OPS_TABLES:
            pdf = self.spark.table(self.fq(table)).toPandas()
            out[table] = [decode_record({k: (None if pd.isna(v) else v) for k, v in row.items()})
                          for row in pdf.to_dict("records")]
        return out

    def upsert(self, table: str, records: list[dict]) -> None:
        if not records:
            return
        self.ensure_ops_tables()
        keys, columns = OPS_TABLES[table]
        pdf = pd.DataFrame([encode_record(table, r) for r in records], columns=columns).astype("string")
        view = f"lsi_upsert_{table}"
        self.spark.createDataFrame(pdf).createOrReplaceTempView(view)
        on = " AND ".join(f"t.`{k}` <=> s.`{k}`" for k in keys)
        self.spark.sql(f"MERGE INTO {self.fq(table)} t USING {view} s ON {on} "
                       "WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")

    def reset_ops(self) -> None:
        self.ensure_ops_tables()
        for table in OPS_TABLES:
            self.spark.sql(f"DELETE FROM {self.fq(table)}")
