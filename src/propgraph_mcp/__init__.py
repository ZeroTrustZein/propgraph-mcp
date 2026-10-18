"""PropGraph MCP: Autonomous CRE underwriting swarm using temporal Graph-RAG over municipal deed streams and SEC filings."""

from __future__ import annotations

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.subsystems import (
    CleanDeedRecord,
    DeedStreamValidator,
    EncumbranceAnalyzer,
    EntityResolver,
    LeaseCommitmentSchedule,
    ParsedSECFiling,
    QuarantineRecord,
    RawDeedRecord,
    SECEdgarPipeline,
    SpatialContiguityEngine,
    ValidationBatchResult,
)
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
    "CleanDeedRecord",
    "DCFScenario",
    "DCFValuationEngine",
    "DeedRecord",
    "DeedStreamValidator",
    "DocumentType",
    "EdgeType",
    "EncumbranceAnalyzer",
    "EntityResolver",
    "GeospatialRiskMetrics",
    "GeospatialRiskEngine",
    "GraphEdge",
    "GraphNode",
    "LeaseCommitmentSchedule",
    "NodeType",
    "ParsedSECFiling",
    "PropertyParcel",
    "PropertyType",
    "QuarantineRecord",
    "RawDeedRecord",
    "RiskTier",
    "SECEdgarPipeline",
    "SECFilingRecord",
    "SECFilingType",
    "ScenarioType",
    "SpatialContiguityEngine",
    "TemporalPropGraph",
    "UnderwritingSummary",
    "ValidationBatchResult",
    "ValuationOutput",
    "calculate_irr",
]
