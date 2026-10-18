"""PropGraph MCP: Autonomous CRE underwriting swarm using temporal Graph-RAG over municipal deed streams and SEC filings."""

from __future__ import annotations

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.types import (
    CashFlowYear,
    DCFScenario,
    DeedRecord,
    DocumentType,
    EdgeType,
    GeospatialRiskMetrics,
    GraphEdge,
    GraphNode,
    NodeType,
    PropertyParcel,
    PropertyType,
    RiskTier,
    ScenarioType,
    SECFilingRecord,
    SECFilingType,
    UnderwritingSummary,
    ValuationOutput,
)
from propgraph_mcp.valuation import DCFValuationEngine, calculate_irr

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "CashFlowYear",
    "DCFScenario",
    "DCFValuationEngine",
    "DeedRecord",
    "DocumentType",
    "EdgeType",
    "GeospatialRiskMetrics",
    "GeospatialRiskEngine",
    "GraphEdge",
    "GraphNode",
    "NodeType",
    "PropertyParcel",
    "PropertyType",
    "RiskTier",
    "SECFilingRecord",
    "SECFilingType",
    "ScenarioType",
    "TemporalPropGraph",
    "UnderwritingSummary",
    "ValuationOutput",
    "calculate_irr",
]
