"""Core data models and types for PropGraph MCP."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class PropertyType(str, Enum):
    """Commercial real estate property classification."""
    OFFICE = "office"
    RETAIL = "retail"
    MULTIFAMILY = "multifamily"
    INDUSTRIAL = "industrial"
    MIXED_USE = "mixed_use"
    HOSPITALITY = "hospitality"


class DocumentType(str, Enum):
    """Common real property recording instruments."""
    WARRANTY_DEED = "Warranty Deed"
    SPECIAL_WARRANTY_DEED = "Special Warranty Deed"
    QUITCLAIM_DEED = "Quitclaim Deed"
    GRANT_DEED = "Grant Deed"
    DEED_OF_TRUST = "Deed of Trust"
    MORTGAGE = "Mortgage"


class EncumbranceType(str, Enum):
    """Common real property encumbrance and lien classifications."""
    FIRST_MORTGAGE = "First Mortgage"
    SECOND_MORTGAGE = "Second Mortgage"
    MEZZANINE_LOAN = "Mezzanine Loan"
    TAX_LIEN = "Tax Lien"
    MECHANICS_LIEN = "Mechanics Lien"
    UCC_FILING = "UCC Filing"
    EASEMENT = "Easement"
    COVENANT = "Covenant"


class SECFilingType(str, Enum):
    """SEC EDGAR corporate filing classifications."""
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_8K = "8-K"


class ScenarioType(str, Enum):
    """DCF financial projection case types."""
    BASE = "Base"
    BULL = "Bull"
    BEAR = "Bear"


class RiskTier(str, Enum):
    """Geospatial and zoning hazard tiering."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class PropertyParcel(BaseModel):
    """Municipal parcel record with architectural & zoning attributes."""
    apn: str = Field(..., min_length=1, description="Assessor Parcel Number")
    address: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=2, max_length=2)
    zip_code: str = Field(..., min_length=5)
    property_type: PropertyType = PropertyType.OFFICE
    square_feet: float = Field(gt=0.0)
    year_built: int = Field(..., ge=1600, le=2200)
    zoning_code: str = "C-1"
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)


class DeedRecord(BaseModel):
    """Municipal deed transfer record representing ownership transition."""
    deed_id: str = Field(..., min_length=1)
    parcel_id: str = Field(..., min_length=1)
    grantor: str = Field(..., min_length=1, description="Seller or transferring entity")
    grantee: str = Field(..., min_length=1, description="Buyer or receiving entity")
    transfer_date: date
    sale_price: float = Field(ge=0.0)
    document_type: str = DocumentType.WARRANTY_DEED.value
    recording_number: Optional[str] = None


class EncumbranceRecord(BaseModel):
    """Real estate lien, mortgage, or deed of trust encumbrance."""
    encumbrance_id: str = Field(..., min_length=1)
    parcel_id: str = Field(..., min_length=1)
    encumbrance_type: EncumbranceType | str
    amount: float = Field(..., ge=0.0)
    lender: str = Field(..., min_length=1)
    recording_date: date
    seniority_rank: int = 1


class SECFilingRecord(BaseModel):
    """SEC EDGAR filing disclosure relevant to commercial property holding."""
    accession_number: str = Field(..., min_length=1)
    cik: str = Field(..., min_length=1)
    company_name: str = Field(..., min_length=1)
    filing_type: str = SECFilingType.FORM_10K.value
    filing_date: date
    period_end: Optional[date] = None
    properties_mentioned: List[str] = Field(default_factory=list)
    lease_obligations: Dict[str, float] = Field(default_factory=dict)
    raw_excerpt: Optional[str] = None


class NodeType(str, Enum):
    """Knowledge graph node classification."""
    PROPERTY = "property"
    ENTITY = "entity"
    DEED = "deed"
    SEC_FILING = "sec_filing"
    LENDER = "lender"
    MUNICIPALITY = "municipality"


class GraphNode(BaseModel):
    """Entity or event vertex in the temporal knowledge multigraph."""
    node_id: str = Field(..., min_length=1)
    node_type: NodeType
    label: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_temporal_bounds(self) -> GraphNode:
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must be before or equal to valid_to")
        return self


class EdgeType(str, Enum):
    """Temporal and structural relationships in property graph."""
    OWNS = "owns"
    TRANSFERRED_TO = "transferred_to"
    FINANCED_BY = "financed_by"
    DISCLOSED_IN = "disclosed_in"
    LEASES_TO = "leases_to"
    ENCUMBERS = "encumbers"


class GraphEdge(BaseModel):
    """Directed edge capturing relational transitions and dates."""
    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    edge_type: EdgeType
    attributes: Dict[str, Any] = Field(default_factory=dict)
    effective_date: Optional[date] = None


class DCFScenario(BaseModel):
    """Discounted Cash Flow modeling scenario parameters."""
    scenario_name: str = ScenarioType.BASE.value
    discount_rate: float = Field(0.08, ge=0.0, le=1.0)
    exit_cap_rate: float = Field(0.065, gt=0.0, le=1.0)
    holding_period_years: int = Field(5, ge=1, le=50)
    rent_growth_rate: float = Field(0.03, ge=-0.5, le=1.0)
    expense_growth_rate: float = Field(0.025, ge=-0.5, le=1.0)
    vacancy_rate: float = Field(0.05, ge=0.0, le=1.0)


class CashFlowYear(BaseModel):
    """Annual underwriting cash flow snapshot."""
    year: int = Field(..., ge=1)
    gross_revenue: float = Field(ge=0.0)
    operating_expenses: float = Field(ge=0.0)
    net_operating_income: float
    debt_service: float = Field(0.0, ge=0.0)
    net_cash_flow: float


class ValuationOutput(BaseModel):
    """DCF Valuation summary results across holding horizon."""
    property_id: str = Field(..., min_length=1)
    scenario_name: str
    purchase_price: float = Field(ge=0.0)
    npv: float
    irr: float
    terminal_value: float = Field(ge=0.0)
    cash_flows: List[CashFlowYear]
    total_net_cash_flow: float


class GeospatialRiskMetrics(BaseModel):
    """Spatial and environmental hazard scores."""
    parcel_id: str = Field(..., min_length=1)
    flood_hazard_score: float = Field(0.0, ge=0.0, le=100.0)
    seismic_risk_score: float = Field(0.0, ge=0.0, le=100.0)
    zoning_compliance_score: float = Field(100.0, ge=0.0, le=100.0)
    environmental_contamination_risk: float = Field(0.0, ge=0.0, le=100.0)
    composite_risk_score: float = Field(0.0, ge=0.0, le=100.0)

    @property
    def zoning_noncompliance_risk(self) -> float:
        """Derived zoning noncompliance risk score."""
        return round(100.0 - self.zoning_compliance_score, 2)

    @property
    def risk_tier(self) -> RiskTier:
        """Derive qualitative risk tier from composite score."""
        if self.composite_risk_score >= 75.0:
            return RiskTier.CRITICAL
        if self.composite_risk_score >= 50.0:
            return RiskTier.HIGH
        if self.composite_risk_score >= 25.0:
            return RiskTier.MODERATE
        return RiskTier.LOW


class UnderwritingSummary(BaseModel):
    """End-to-end CRE underwriting report synthesized by the swarm."""
    property_id: str = Field(..., min_length=1)
    parcel: PropertyParcel
    scenarios: Dict[str, ValuationOutput]
    risk_metrics: GeospatialRiskMetrics
    related_entities_count: int = Field(0, ge=0)
    recommendation: str


__all__ = [
    "CashFlowYear",
    "DCFScenario",
    "DeedRecord",
    "DocumentType",
    "EdgeType",
    "EncumbranceRecord",
    "EncumbranceType",
    "GeospatialRiskMetrics",
    "GraphEdge",
    "GraphNode",
    "NodeType",
    "PropertyParcel",
    "PropertyType",
    "RiskTier",
    "SECFilingRecord",
    "SECFilingType",
    "ScenarioType",
    "UnderwritingSummary",
    "ValuationOutput",
]
