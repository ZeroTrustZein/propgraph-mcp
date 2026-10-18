"""SEC EDGAR corporate disclosure pipeline for CRE holdings and lease commitments."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.types import EdgeType, GraphEdge, GraphNode, NodeType, SECFilingRecord, SECFilingType


class LeaseCommitmentSchedule(BaseModel):
    """Future minimum lease payment schedule extracted from 10-K disclosures."""

    tenant_name: str
    cik: Optional[str] = None
    fiscal_year: int
    year_1: float = Field(0.0, ge=0.0)
    year_2: float = Field(0.0, ge=0.0)
    year_3: float = Field(0.0, ge=0.0)
    year_4: float = Field(0.0, ge=0.0)
    year_5: float = Field(0.0, ge=0.0)
    thereafter: float = Field(0.0, ge=0.0)

    @property
    def total_commitment(self) -> float:
        """Total undiscounted contractual lease obligations."""
        return (
            self.year_1
            + self.year_2
            + self.year_3
            + self.year_4
            + self.year_5
            + self.thereafter
        )


class ParsedSECFiling(BaseModel):
    """Structured extraction of an SEC EDGAR filing."""

    accession_number: str
    cik: str
    company_name: str
    filing_type: str = SECFilingType.FORM_10K.value
    filing_date: date
    properties_identified: List[str] = Field(default_factory=list)
    lease_schedules: List[LeaseCommitmentSchedule] = Field(default_factory=list)
    raw_excerpts: List[str] = Field(default_factory=list)


class SECEdgarPipeline:
    """Parses, extracts, and attaches SEC corporate filings and lease schedules to property graphs."""

    @staticmethod
    def extract_apns_from_text(text: str) -> List[str]:
        """Extract Assessor Parcel Numbers (APNs) or parcel identifiers from text."""
        # Patterns like APN 123-456-78, APN-102-55, Parcel 999-00-11
        pattern = r"\b(?:APN|Parcel|APN#|PIN)[\s:-]*([A-Z0-9]{2,5}-[A-Z0-9]{2,5}(?:-[A-Z0-9]{2,5})?)\b"
        matches = re.findall(pattern, text, re.IGNORECASE)
        # Also direct matches like APN-102-55
        raw_direct = re.findall(r"\bAPN-[0-9A-Z]+-[0-9A-Z]+(?:-[0-9A-Z]+)?\b", text)
        all_apns = set(raw_direct)
        for m in matches:
            all_apns.add(f"APN-{m}" if not m.startswith("APN-") else m)
        return sorted(all_apns)

    @staticmethod
    def extract_lease_commitments(
        text: str, tenant_name: str, fiscal_year: int = 2026
    ) -> Optional[LeaseCommitmentSchedule]:
        """Extract multi-year lease commitments from 10-K Note disclosures."""
        # Search for tables or patterns containing year commitments
        # e.g. "Year 1: $1,200,000", "2026: 1200000"
        commitments: Dict[str, float] = {}

        patterns = [
            (r"(?:Year\s*1|First\s*year|2026)[\s:$]+([\d,]+(?:\.\d+)?)", "year_1"),
            (r"(?:Year\s*2|Second\s*year|2027)[\s:$]+([\d,]+(?:\.\d+)?)", "year_2"),
            (r"(?:Year\s*3|Third\s*year|2028)[\s:$]+([\d,]+(?:\.\d+)?)", "year_3"),
            (r"(?:Year\s*4|Fourth\s*year|2029)[\s:$]+([\d,]+(?:\.\d+)?)", "year_4"),
            (r"(?:Year\s*5|Fifth\s*year|2030)[\s:$]+([\d,]+(?:\.\d+)?)", "year_5"),
            (r"(?:Thereafter|Later\s*years)[\s:$]+([\d,]+(?:\.\d+)?)", "thereafter"),
        ]

        found_any = False
        for regex, field in patterns:
            match = re.search(regex, text, re.IGNORECASE)
            if match:
                val_str = match.group(1).replace(",", "")
                try:
                    commitments[field] = float(val_str)
                    found_any = True
                except ValueError:
                    commitments[field] = 0.0
            else:
                commitments[field] = 0.0

        if not found_any:
            return None

        return LeaseCommitmentSchedule(
            tenant_name=tenant_name,
            fiscal_year=fiscal_year,
            year_1=commitments.get("year_1", 0.0),
            year_2=commitments.get("year_2", 0.0),
            year_3=commitments.get("year_3", 0.0),
            year_4=commitments.get("year_4", 0.0),
            year_5=commitments.get("year_5", 0.0),
            thereafter=commitments.get("thereafter", 0.0),
        )

    def parse_filing(
        self,
        accession_number: str,
        cik: str,
        company_name: str,
        filing_type: str,
        filing_date: date,
        raw_text: str,
    ) -> ParsedSECFiling:
        """Parse raw filing text into a structured ParsedSECFiling."""
        apns = self.extract_apns_from_text(raw_text)
        schedules: List[LeaseCommitmentSchedule] = []

        sched = self.extract_lease_commitments(
            raw_text, tenant_name=company_name, fiscal_year=filing_date.year
        )
        if sched:
            sched.cik = cik
            schedules.append(sched)

        # Excerpts around property mentions
        excerpts: List[str] = []
        for apn in apns:
            pos = raw_text.find(apn)
            if pos != -1:
                start = max(0, pos - 100)
                end = min(len(raw_text), pos + 150)
                excerpts.append(raw_text[start:end].strip())

        return ParsedSECFiling(
            accession_number=accession_number,
            cik=cik,
            company_name=company_name,
            filing_type=filing_type,
            filing_date=filing_date,
            properties_identified=apns,
            lease_schedules=schedules,
            raw_excerpts=excerpts,
        )

    def attach_to_graph(
        self, graph: TemporalPropGraph, filing: ParsedSECFiling
    ) -> Dict[str, Any]:
        """Link parsed SEC filing and lease schedules to property graph."""
        # Convert to SECFilingRecord
        lease_dict: Dict[str, float] = {}
        if filing.lease_schedules:
            primary_sched = filing.lease_schedules[0]
            lease_dict = {
                "year_1": primary_sched.year_1,
                "year_2": primary_sched.year_2,
                "year_3": primary_sched.year_3,
                "total_commitment": primary_sched.total_commitment,
            }

        rec = SECFilingRecord(
            accession_number=filing.accession_number,
            cik=filing.cik,
            company_name=filing.company_name,
            filing_type=filing.filing_type,
            filing_date=filing.filing_date,
            properties_mentioned=filing.properties_identified,
            lease_obligations=lease_dict,
            raw_excerpt="\n---\n".join(filing.raw_excerpts) if filing.raw_excerpts else None,
        )
        graph.add_sec_filing(rec)

        # Also add direct LEASES_TO edges from tenant entity to properties if commitments exist
        entity_id = f"entity:{filing.company_name.lower().replace(' ', '_')}"
        leases_added = 0
        for apn in filing.properties_identified:
            if filing.lease_schedules:
                sched = filing.lease_schedules[0]
                graph.add_edge(
                    GraphEdge(
                        source_id=entity_id,
                        target_id=apn,
                        edge_type=EdgeType.LEASES_TO,
                        effective_date=filing.filing_date,
                        attributes={
                            "annual_rent_yr1": sched.year_1,
                            "total_commitment": sched.total_commitment,
                        },
                    )
                )
                leases_added += 1

        return {
            "accession_number": filing.accession_number,
            "company_name": filing.company_name,
            "properties_linked": len(filing.properties_identified),
            "lease_edges_added": leases_added,
        }

    def evaluate_tenant_concentration(
        self,
        property_revenue: float,
        tenant_commitments: List[LeaseCommitmentSchedule],
    ) -> Dict[str, Any]:
        """Compute tenant concentration ratio and flag underwriting exposure."""
        if property_revenue <= 0.0:
            return {"error": "Property gross revenue must be positive"}

        tenants: List[Dict[str, Any]] = []
        total_tenant_rent = 0.0

        for sched in tenant_commitments:
            yr1_rent = sched.year_1
            share = yr1_rent / property_revenue
            tenants.append(
                {
                    "tenant_name": sched.tenant_name,
                    "annual_rent": yr1_rent,
                    "revenue_share": round(share, 4),
                    "total_obligation": sched.total_commitment,
                    "is_single_tenant_risk": share >= 0.30,
                }
            )
            total_tenant_rent += yr1_rent

        tenants.sort(key=lambda x: x["revenue_share"], reverse=True)
        top_share = tenants[0]["revenue_share"] if tenants else 0.0

        # High risk if top tenant > 40% or top 3 > 75%
        top_3_share = sum(t["revenue_share"] for t in tenants[:3])
        concentration_risk = "low"
        if top_share >= 0.50:
            concentration_risk = "critical"
        elif top_share >= 0.30 or top_3_share >= 0.70:
            concentration_risk = "high"
        elif top_share >= 0.15:
            concentration_risk = "moderate"

        return {
            "property_annual_revenue": property_revenue,
            "total_contracted_rent": total_tenant_rent,
            "top_tenant_share": round(top_share, 4),
            "top_3_tenants_share": round(top_3_share, 4),
            "concentration_risk": concentration_risk,
            "tenants": tenants,
        }
