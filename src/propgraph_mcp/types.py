"""Core data models and types for PropGraph MCP."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PropertyType(str, Enum):
    """Commercial real estate property classification."""
    OFFICE = "office"
    RETAIL = "retail"
    MULTIFAMILY = "multifamily"
    INDUSTRIAL = "industrial"
    MIXED_USE = "mixed_use"
    HOSPITALITY = "hospitality"


class PropertyParcel(BaseModel):
    """Municipal parcel record with architectural & zoning attributes."""
    apn: str = Field(..., description="Assessor Parcel Number")
    address: str
    city: str
    state: str
    zip_code: str
    property_type: PropertyType = PropertyType.OFFICE
    square_feet: float = Field(gt=0)
    year_built: int
    zoning_code: str = "C-1"
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class DeedRecord(BaseModel):
    """Municipal deed transfer record representing ownership transition."""
    deed_id: str
    parcel_id: str
    grantor: str = Field(..., description="Seller or transferring entity")
    grantee: str = Field(..., description="Buyer or receiving entity")
    transfer_date: date
    sale_price: float = Field(ge=0.0)
    document_type: str = "Warranty Deed"
    recording_number: Optional[str] = None


class SECFilingRecord(BaseModel):
    """SEC EDGAR filing disclosure relevant to commercial property holding."""
    accession_number: str
    cik: str
    company_name: str
    filing_type: str = "10-K"
    filing_date: date
    period_end: Optional[date] = None
    properties_mentioned: List[str] = Field(default_factory=list)
    lease_obligations: Dict[str, float] = Field(default_factory=dict)
    raw_excerpt: Optional[str] = None


class NodeType(str, Enum):
    PROPERTY = "property"
    ENTITY = "entity"
    DEED = "deed"
    SEC_FILING = "sec_filing"
    LENDER = "lender"


class GraphNode(BaseModel):
    """Node in the temporal knowledge graph."""
    node_id: str
    node_type: NodeType
    label: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None


class EdgeType(str, Enum):
    OWNS = "owns"
    TRANSFERRED_TO = "transferred_to"
    FINANCED_BY = "financed_by"
    DISCLOSED_IN = "disclosed_in"
    LEASES_TO = "leases_to"


class GraphEdge(BaseModel):
    """Directed temporal relationship between entities."""
    source_id: str
    target_id: str
    edge_type: EdgeType
    attributes: Dict[str, Any] = Field(default_factory=dict)
    effective_date: Optional[date] = None


class DCFScenario(BaseModel):
    """Assumptions for multi-scenario discounted cash flow underwriting."""
    scenario_name: str = "Base"
    discount_rate: float = Field(0.08, ge=0.0, le=1.0)
    exit_cap_rate: float = Field(0.065, ge=0.01, le=1.0)
    holding_period_years: int = Field(5, ge=1, le=30)
    rent_growth_rate: float = Field(0.03, ge=-0.2, le=0.5)
    expense_growth_rate: float = Field(0.025, ge=-0.1, le=0.5)
    vacancy_rate: float = Field(0.05, ge=0.0, le=1.0)


class CashFlowYear(BaseModel):
    """Annual underwriting cash flow snapshot."""
    year: int
    gross_revenue: float
    operating_expenses: float
    net_operating_income: float
    debt_service: float = 0.0
    net_cash_flow: float


class ValuationOutput(BaseModel):
    """DCF Valuation summary results."""
    property_id: str
    scenario_name: str
    purchase_price: float
    npv: float
    irr: float
    terminal_value: float
    cash_flows: List[CashFlowYear]
    total_net_cash_flow: float


class GeospatialRiskMetrics(BaseModel):
    """Geospatial and regulatory risk scores scaled [0, 100]."""
    parcel_id: str
    flood_hazard_score: float = Field(0.0, ge=0.0, le=100.0)
    seismic_risk_score: float = Field(0.0, ge=0.0, le=100.0)
    zoning_compliance_score: float = Field(100.0, ge=0.0, le=100.0)
    environmental_contamination_risk: float = Field(0.0, ge=0.0, le=100.0)
    composite_risk_score: float = Field(0.0, ge=0.0, le=100.0)


class UnderwritingSummary(BaseModel):
    """End-to-end CRE underwriting report synthesized by the swarm."""
    property_id: str
    parcel: PropertyParcel
    scenarios: Dict[str, ValuationOutput]
    risk_metrics: GeospatialRiskMetrics
    related_entities_count: int
    recommendation: str
