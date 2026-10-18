"""Municipal deed stream ingestion, sanitization, and SQL validation pipeline."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.types import DeedRecord, DocumentType


class RawDeedRecord(BaseModel):
    """Raw deed transfer export row from county assessor or municipal deed stream."""

    raw_id: Optional[str] = None
    parcel_id: Optional[str] = None
    grantor: Optional[str] = None
    grantee: Optional[str] = None
    sale_date: Optional[str] = None
    sale_price_raw: Optional[Any] = None
    deed_type: Optional[str] = "Warranty Deed"
    recording_number: Optional[str] = None


class CleanDeedRecord(BaseModel):
    """Sanitized, validated deed record ready for property graph."""

    deed_id: str
    parcel_id: str
    grantor: str
    grantee: str
    sale_date: date
    sale_price: float
    deed_type: str = DocumentType.WARRANTY_DEED.value
    recording_number: Optional[str] = None
    is_arms_length: bool = True


class QuarantineRecord(BaseModel):
    """Failed raw deed record flagged for quarantine."""

    raw_id: Optional[str] = None
    parcel_id: Optional[str] = None
    error_code: str
    error_reason: str
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class ValidationBatchResult(BaseModel):
    """Summary of municipal deed stream batch validation run."""

    total_records: int = 0
    clean_records: int = 0
    quarantined_records: int = 0
    total_dollar_volume: float = 0.0
    arms_length_count: int = 0
    quarantine_breakdown: Dict[str, int] = Field(default_factory=dict)
    processed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DeedStreamValidator:
    """Validates, sanitizes, and streams raw municipal recorder exports into clean deed records."""

    def __init__(
        self,
        min_arms_length_price: float = 1000.0,
        max_reasonable_price: float = 5_000_000_000.0,
    ) -> None:
        self.min_arms_length_price = min_arms_length_price
        self.max_reasonable_price = max_reasonable_price

    def generate_schema_ddl(self) -> str:
        """Generate PostgreSQL DDL for municipal deed streams."""
        return """-- Municipal Deed Stream Tables
CREATE TABLE IF NOT EXISTS raw_deed_stream (
    raw_id VARCHAR(64) PRIMARY KEY,
    parcel_id VARCHAR(64) NOT NULL,
    grantor TEXT NOT NULL,
    grantee TEXT NOT NULL,
    sale_date VARCHAR(32) NOT NULL,
    sale_price_raw TEXT,
    deed_type VARCHAR(64) DEFAULT 'Warranty Deed',
    recording_number VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clean_deeds (
    deed_id VARCHAR(64) PRIMARY KEY,
    parcel_id VARCHAR(64) NOT NULL,
    grantor TEXT NOT NULL,
    grantee TEXT NOT NULL,
    sale_date DATE NOT NULL,
    sale_price NUMERIC(15, 2) NOT NULL,
    deed_type VARCHAR(64) NOT NULL,
    recording_number VARCHAR(128),
    is_arms_length BOOLEAN DEFAULT TRUE,
    validated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quarantine_deeds (
    raw_id VARCHAR(64),
    parcel_id VARCHAR(64),
    error_code VARCHAR(32) NOT NULL,
    error_reason TEXT NOT NULL,
    raw_payload JSONB NOT NULL,
    quarantined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_clean_deeds_parcel ON clean_deeds(parcel_id);
CREATE INDEX IF NOT EXISTS idx_clean_deeds_date ON clean_deeds(sale_date);
"""

    def generate_cleaning_pipeline_sql(self) -> str:
        """Generate SQL transformation logic for batch loading."""
        return f"""-- Ingestion Pipeline Transformation
INSERT INTO quarantine_deeds (raw_id, parcel_id, error_code, error_reason, raw_payload)
SELECT
    raw_id,
    parcel_id,
    'MISSING_PARTIES',
    'Grantor or Grantee is empty',
    to_jsonb(r)
FROM raw_deed_stream r
WHERE grantor IS NULL OR TRIM(grantor) = '' OR grantee IS NULL OR TRIM(grantee) = '';

INSERT INTO clean_deeds (deed_id, parcel_id, grantor, grantee, sale_date, sale_price, deed_type, recording_number, is_arms_length)
SELECT
    COALESCE(raw_id, 'DEED-' || md5(random()::text)),
    parcel_id,
    TRIM(grantor),
    TRIM(grantee),
    sale_date::date,
    GREATEST(0.0, REPLACE(REPLACE(sale_price_raw, '$', ''), ',', '')::numeric),
    COALESCE(deed_type, 'Warranty Deed'),
    recording_number,
    (GREATEST(0.0, REPLACE(REPLACE(sale_price_raw, '$', ''), ',', '')::numeric) >= {self.min_arms_length_price})
FROM raw_deed_stream r
WHERE grantor IS NOT NULL AND TRIM(grantor) <> ''
  AND grantee IS NOT NULL AND TRIM(grantee) <> ''
  AND sale_date IS NOT NULL;
"""

    def parse_price(self, raw_val: Any) -> Optional[float]:
        """Sanitize raw price representation to numeric float."""
        if raw_val is None:
            return None
        if isinstance(raw_val, (int, float)):
            return float(raw_val)
        val_str = str(raw_val).strip()
        cleaned = re.sub(r"[^\d.]", "", val_str)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def parse_date(self, raw_date: Optional[str]) -> Optional[date]:
        """Parse various date strings into standard Python date."""
        if not raw_date:
            return None
        raw_str = str(raw_date).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw_str, fmt).date()
            except ValueError:
                continue
        # ISO fallback
        try:
            return date.fromisoformat(raw_str[:10])
        except (ValueError, TypeError):
            return None

    def validate_record(
        self, record: RawDeedRecord | Dict[str, Any]
    ) -> Tuple[Optional[CleanDeedRecord], Optional[QuarantineRecord]]:
        """Validate single raw record into either clean or quarantined record."""
        payload = (
            record.model_dump()
            if isinstance(record, RawDeedRecord)
            else dict(record)
        )
        raw_id = str(payload.get("raw_id") or "")
        parcel_id = str(payload.get("parcel_id") or "").strip()
        grantor = str(payload.get("grantor") or "").strip()
        grantee = str(payload.get("grantee") or "").strip()

        if not parcel_id:
            return None, QuarantineRecord(
                raw_id=raw_id or None,
                parcel_id=None,
                error_code="MISSING_PARCEL_ID",
                error_reason="Parcel ID / APN cannot be blank",
                raw_payload=payload,
            )

        if not grantor or not grantee:
            return None, QuarantineRecord(
                raw_id=raw_id or None,
                parcel_id=parcel_id,
                error_code="MISSING_PARTIES",
                error_reason="Grantor and grantee names are required",
                raw_payload=payload,
            )

        parsed_date = self.parse_date(payload.get("sale_date"))
        if not parsed_date:
            return None, QuarantineRecord(
                raw_id=raw_id or None,
                parcel_id=parcel_id,
                error_code="INVALID_DATE",
                error_reason=f"Cannot parse transfer date: {payload.get('sale_date')}",
                raw_payload=payload,
            )

        price = self.parse_price(payload.get("sale_price_raw"))
        if price is None or price < 0.0:
            return None, QuarantineRecord(
                raw_id=raw_id or None,
                parcel_id=parcel_id,
                error_code="INVALID_PRICE",
                error_reason=f"Invalid sale price value: {payload.get('sale_price_raw')}",
                raw_payload=payload,
            )

        if price > self.max_reasonable_price:
            return None, QuarantineRecord(
                raw_id=raw_id or None,
                parcel_id=parcel_id,
                error_code="OUTLIER_PRICE",
                error_reason=f"Sale price {price} exceeds maximum reasonable ceiling {self.max_reasonable_price}",
                raw_payload=payload,
            )

        deed_type = str(payload.get("deed_type") or "Warranty Deed").strip()
        is_arms_length = (
            price >= self.min_arms_length_price
            and "quitclaim" not in deed_type.lower()
            and grantor.lower() != grantee.lower()
        )

        clean_id = raw_id if raw_id else f"DEED-{parcel_id}-{parsed_date.isoformat()}"
        clean = CleanDeedRecord(
            deed_id=clean_id,
            parcel_id=parcel_id,
            grantor=grantor,
            grantee=grantee,
            sale_date=parsed_date,
            sale_price=price,
            deed_type=deed_type,
            recording_number=payload.get("recording_number"),
            is_arms_length=is_arms_length,
        )
        return clean, None

    def validate_batch(
        self, records: List[RawDeedRecord | Dict[str, Any]]
    ) -> Tuple[List[CleanDeedRecord], List[QuarantineRecord], ValidationBatchResult]:
        """Validate an entire batch of raw deed stream records."""
        clean_list: List[CleanDeedRecord] = []
        quarantine_list: List[QuarantineRecord] = []
        breakdown: Dict[str, int] = {}
        total_vol = 0.0
        arms_length_cnt = 0

        for r in records:
            clean, quar = self.validate_record(r)
            if clean:
                clean_list.append(clean)
                total_vol += clean.sale_price
                if clean.is_arms_length:
                    arms_length_cnt += 1
            elif quar:
                quarantine_list.append(quar)
                breakdown[quar.error_code] = breakdown.get(quar.error_code, 0) + 1

        summary = ValidationBatchResult(
            total_records=len(records),
            clean_records=len(clean_list),
            quarantined_records=len(quarantine_list),
            total_dollar_volume=round(total_vol, 2),
            arms_length_count=arms_length_cnt,
            quarantine_breakdown=breakdown,
        )
        return clean_list, quarantine_list, summary

    def ingest_batch_to_graph(
        self, graph: TemporalPropGraph, clean_deeds: List[CleanDeedRecord]
    ) -> int:
        """Ingest validated clean deed records into TemporalPropGraph."""
        count = 0
        for cd in clean_deeds:
            deed_model = DeedRecord(
                deed_id=cd.deed_id,
                parcel_id=cd.parcel_id,
                grantor=cd.grantor,
                grantee=cd.grantee,
                transfer_date=cd.sale_date,
                sale_price=cd.sale_price,
                document_type=cd.deed_type,
                recording_number=cd.recording_number,
            )
            graph.add_deed(deed_model)
            count += 1
        return count
