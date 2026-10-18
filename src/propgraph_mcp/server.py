"""Model Context Protocol (MCP) server for PropGraph CRE Underwriting Swarm."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from mcp.server import MCPServer

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.types import (
    DCFScenario,
    DeedRecord,
    PropertyParcel,
    PropertyType,
    SECFilingRecord,
    UnderwritingSummary,
)
from propgraph_mcp.valuation import DCFValuationEngine


def create_mcp_server(name: str = "propgraph-mcp") -> MCPServer:
    """Factory creating and configuring the PropGraph MCPServer."""
    server = MCPServer(name)
    graph = TemporalPropGraph()
    valuation_engine = DCFValuationEngine()
    risk_engine = GeospatialRiskEngine()

    @server.tool()
    def query_property_graph(apn: str, depth: int = 2) -> Dict[str, Any]:
        """Query knowledge graph neighborhood around a property APN."""
        timeline = graph.get_ownership_timeline(apn)
        related = graph.get_related_entities(apn, depth=depth)
        return {
            "apn": apn,
            "ownership_timeline": timeline,
            "connected_entities": related,
            "total_graph_nodes": graph.node_count,
            "total_graph_edges": graph.edge_count,
        }

    @server.tool()
    def ingest_deed_record(
        deed_id: str,
        parcel_id: str,
        grantor: str,
        grantee: str,
        transfer_date: str,
        sale_price: float,
        document_type: str = "Warranty Deed",
    ) -> Dict[str, Any]:
        """Ingest a municipal deed record and attach it to the temporal knowledge graph."""
        deed = DeedRecord(
            deed_id=deed_id,
            parcel_id=parcel_id,
            grantor=grantor,
            grantee=grantee,
            transfer_date=date.fromisoformat(transfer_date),
            sale_price=sale_price,
            document_type=document_type,
        )
        graph.add_deed(deed)
        return {
            "status": "ingested",
            "deed_id": deed_id,
            "parcel_id": parcel_id,
            "nodes": graph.node_count,
            "edges": graph.edge_count,
        }

    @server.tool()
    def ingest_sec_filing(
        accession_number: str,
        cik: str,
        company_name: str,
        filing_type: str,
        filing_date: str,
        properties_mentioned: List[str],
    ) -> Dict[str, Any]:
        """Ingest an SEC EDGAR disclosure and link to commercial real estate assets."""
        filing = SECFilingRecord(
            accession_number=accession_number,
            cik=cik,
            company_name=company_name,
            filing_type=filing_type,
            filing_date=date.fromisoformat(filing_date),
            properties_mentioned=properties_mentioned,
        )
        graph.add_sec_filing(filing)
        return {
            "status": "ingested",
            "accession_number": accession_number,
            "company_name": company_name,
            "linked_properties": properties_mentioned,
        }

    @server.tool()
    def calculate_dcf_valuation(
        property_id: str,
        gross_revenue: float,
        operating_expenses: float,
        purchase_price: float,
        discount_rate: float = 0.08,
        exit_cap_rate: float = 0.065,
        holding_years: int = 5,
        rent_growth_rate: float = 0.03,
        expense_growth_rate: float = 0.025,
        vacancy_rate: float = 0.05,
    ) -> Dict[str, Any]:
        """Run discounted cash flow (DCF) underwriting scenario."""
        scenario = DCFScenario(
            scenario_name="Custom",
            discount_rate=discount_rate,
            exit_cap_rate=exit_cap_rate,
            holding_period_years=holding_years,
            rent_growth_rate=rent_growth_rate,
            expense_growth_rate=expense_growth_rate,
            vacancy_rate=vacancy_rate,
        )
        output = valuation_engine.run_scenario(
            property_id=property_id,
            initial_gross_revenue=gross_revenue,
            initial_operating_expenses=operating_expenses,
            purchase_price=purchase_price,
            scenario=scenario,
        )
        return output.model_dump()

    @server.tool()
    def assess_geospatial_risk(
        apn: str,
        address: str,
        city: str,
        state: str,
        zip_code: str,
        square_feet: float,
        year_built: int,
        property_type: str = "office",
        zoning_code: str = "C-1",
        flood_zone: Optional[str] = None,
        seismic_zone: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Evaluate climate, seismic, and zoning compliance risks for a CRE parcel."""
        parcel = PropertyParcel(
            apn=apn,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            property_type=PropertyType(property_type.lower()),
            square_feet=square_feet,
            year_built=year_built,
            zoning_code=zoning_code,
        )
        metrics = risk_engine.assess_parcel_risk(
            parcel=parcel,
            flood_zone=flood_zone,
            seismic_zone=seismic_zone,
        )
        return metrics.model_dump()

    @server.tool()
    def run_underwriting_pipeline(
        apn: str,
        address: str,
        city: str,
        state: str,
        zip_code: str,
        square_feet: float,
        year_built: int,
        purchase_price: float,
        gross_revenue: float,
        operating_expenses: float,
        property_type: str = "office",
        zoning_code: str = "C-1",
    ) -> Dict[str, Any]:
        """Run full autonomous underwriting pipeline combining Graph-RAG, DCF scenarios, and risk metrics."""
        parcel = PropertyParcel(
            apn=apn,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            property_type=PropertyType(property_type.lower()),
            square_feet=square_feet,
            year_built=year_built,
            zoning_code=zoning_code,
        )
        graph.add_property(parcel)

        scenarios = valuation_engine.run_all_scenarios(
            property_id=apn,
            initial_gross_revenue=gross_revenue,
            initial_operating_expenses=operating_expenses,
            purchase_price=purchase_price,
        )

        risk_metrics = risk_engine.assess_parcel_risk(parcel)
        related = graph.get_related_entities(apn)

        # Recommendation logic
        base_irr = scenarios["Base"].irr
        base_npv = scenarios["Base"].npv
        if base_irr >= 0.12 and base_npv > 0 and risk_metrics.composite_risk_score < 40.0:
            rec = "PROCEED: Strong risk-adjusted yield and favorable capitalization."
        elif base_npv > 0 and risk_metrics.composite_risk_score < 60.0:
            rec = "CONDITIONAL: Positive NPV but requires hedging on moderate risk factors."
        else:
            rec = "DECLINE: Underwriting hurdle rates not met under base scenario or elevated composite risk."

        summary = UnderwritingSummary(
            property_id=apn,
            parcel=parcel,
            scenarios=scenarios,
            risk_metrics=risk_metrics,
            related_entities_count=len(related),
            recommendation=rec,
        )
        return summary.model_dump()

    return server
