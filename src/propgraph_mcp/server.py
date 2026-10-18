"""Model Context Protocol (MCP) server for PropGraph CRE Underwriting Swarm."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

from mcp.server import MCPServer

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.subsystems import (
    DeedStreamValidator,
    EncumbranceAnalyzer,
    EntityResolver,
    SECEdgarPipeline,
    SpatialContiguityEngine,
)
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
    deed_validator = DeedStreamValidator()
    sec_pipeline = SECEdgarPipeline()
    entity_resolver = EntityResolver()
    encumbrance_analyzer = EncumbranceAnalyzer()
    spatial_engine = SpatialContiguityEngine()

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

    @server.tool()
    def validate_deed_stream(
        records: List[Dict[str, Any]],
        ingest_clean: bool = True,
    ) -> Dict[str, Any]:
        """Validate a batch of raw municipal deed records and optionally ingest clean records."""
        clean_list, quar_list, summary = deed_validator.validate_batch(records)
        ingested_count = 0
        if ingest_clean and clean_list:
            ingested_count = deed_validator.ingest_batch_to_graph(graph, clean_list)
        return {
            "summary": summary.model_dump(),
            "ingested_into_graph": ingested_count,
            "quarantined_samples": [q.model_dump() for q in quar_list[:5]],
        }

    @server.tool()
    def parse_sec_disclosures(
        accession_number: str,
        cik: str,
        company_name: str,
        filing_type: str,
        filing_date: str,
        raw_text: str,
        attach_to_knowledge_graph: bool = True,
    ) -> Dict[str, Any]:
        """Parse raw SEC EDGAR text for property holdings, lease schedules, and link to graph."""
        parsed = sec_pipeline.parse_filing(
            accession_number=accession_number,
            cik=cik,
            company_name=company_name,
            filing_type=filing_type,
            filing_date=date.fromisoformat(filing_date),
            raw_text=raw_text,
        )
        graph_link = None
        if attach_to_knowledge_graph:
            graph_link = sec_pipeline.attach_to_graph(graph, parsed)

        return {
            "parsed_filing": parsed.model_dump(),
            "graph_attachment": graph_link,
        }

    @server.tool()
    def resolve_entity_network(
        entity_name: str,
        auto_merge_duplicates: bool = False,
    ) -> Dict[str, Any]:
        """Disambiguate corporate aliases and trace beneficial ownership in property graph."""
        duplicates = entity_resolver.find_duplicate_entities(graph)
        merged_count = 0
        if auto_merge_duplicates:
            for d in duplicates:
                success = entity_resolver.merge_entities(
                    graph, d["entity_id_1"], d["entity_id_2"]
                )
                if success:
                    merged_count += 1

        norm_name = TemporalPropGraph.normalize_entity_name(entity_name)
        entity_id = f"entity:{norm_name.replace(' ', '_')}"
        ubos = entity_resolver.trace_ultimate_beneficial_owners(graph, entity_id)
        portfolio = graph.get_entity_portfolio(entity_name)

        return {
            "entity_name": entity_name,
            "entity_id": entity_id,
            "duplicate_candidates_found": len(duplicates),
            "merged_count": merged_count,
            "beneficial_owners": ubos,
            "portfolio_assets": portfolio,
        }

    @server.tool()
    def analyze_encumbrance_waterfall(
        apn: str,
        property_valuation: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluate lien priority ranking, cumulative LTV, and cross-collateralized debts."""
        waterfall = encumbrance_analyzer.analyze_parcel_encumbrance_waterfall(
            graph, apn, property_valuation=property_valuation
        )
        cross_collateral = encumbrance_analyzer.detect_cross_collateralization(graph)
        return {
            "parcel_waterfall": waterfall,
            "system_cross_collateralized_loans": cross_collateral,
        }

    @server.tool()
    def analyze_spatial_assemblage(
        max_distance_meters: float = 200.0,
    ) -> Dict[str, Any]:
        """Infer parcel spatial adjacency and find contiguous assemblage opportunities."""
        adj_inferred = spatial_engine.infer_spatial_adjacencies(
            graph, max_distance_meters=max_distance_meters
        )
        assemblages = spatial_engine.find_assemblage_clusters(
            graph, max_distance_meters=max_distance_meters
        )
        return {
            "adjacencies_inferred": adj_inferred,
            "assemblages_found": assemblages,
        }

    @server.tool()
    def get_chain_of_title(apn: str) -> Dict[str, Any]:
        """Audit chain of title for breaks in ownership or quitclaim deed flags."""
        chain = graph.get_chain_of_title(apn)
        has_break = any(record.get("is_break_in_title", False) for record in chain)
        quitclaims = [
            record for record in chain if "Quitclaim" in record.get("document_type", "")
        ]
        return {
            "apn": apn,
            "chain_length": len(chain),
            "has_break_in_title": has_break,
            "quitclaim_count": len(quitclaims),
            "chain_records": chain,
        }

    @server.tool()
    def evaluate_zoning_capacity(
        parcel_id: str,
        lot_size_sqft: float,
        building_footprint_sqft: float,
        total_building_sqft: float,
        stories: int,
        building_height_ft: float,
        zoning_code: str = "C-1",
        parking_spaces: int = 50,
    ) -> Dict[str, Any]:
        """Evaluate zoning capacity, FAR utilization, and variance requirements."""
        return risk_engine.evaluate_zoning_capacity(
            parcel_id=parcel_id,
            lot_size_sqft=lot_size_sqft,
            building_footprint_sqft=building_footprint_sqft,
            total_building_sqft=total_building_sqft,
            stories=stories,
            building_height_ft=building_height_ft,
            zoning_code=zoning_code,
            parking_spaces=parking_spaces,
        )

    @server.tool()
    def project_climate_risk(
        apn: str,
        horizon_year: int = 2050,
        rcp_scenario: str = "RCP8.5",
    ) -> Dict[str, Any]:
        """Project multi-decade climate and physical risk multipliers."""
        return risk_engine.project_climate_risk(
            parcel_id=apn,
            horizon_year=horizon_year,
            rcp_scenario=rcp_scenario,
        )

    @server.resource("graph://summary")
    def graph_topology_summary() -> str:
        """Read-only resource returning global graph topology and density metrics."""
        return json.dumps(
            {
                "total_nodes": graph.node_count,
                "total_edges": graph.edge_count,
                "is_multigraph": True,
            },
            indent=2,
        )

    @server.resource("property://{apn}/timeline")
    def property_timeline_resource(apn: str) -> str:
        """Read-only resource returning chronological ownership timeline for an APN."""
        timeline = graph.get_ownership_timeline(apn)
        return json.dumps({"apn": apn, "timeline": timeline}, indent=2, default=str)

    @server.resource("property://{apn}/encumbrances")
    def property_encumbrances_resource(apn: str) -> str:
        """Read-only resource returning debt and lien waterfall for an APN."""
        waterfall = encumbrance_analyzer.analyze_parcel_encumbrance_waterfall(graph, apn)
        return json.dumps({"apn": apn, "waterfall": waterfall}, indent=2, default=str)

    @server.resource("property://{apn}/risk")
    def property_risk_resource(apn: str) -> str:
        """Read-only resource returning forward climate and geospatial risk projections."""
        climate = risk_engine.project_climate_risk(apn)
        return json.dumps({"apn": apn, "risk_projections": climate}, indent=2, default=str)

    @server.prompt("underwrite-property")
    def prompt_underwrite_property(apn: str) -> str:
        """Prompt template for LLM autonomous underwriting evaluation."""
        return (
            f"You are a Senior CRE Underwriter evaluating parcel {apn}.\n"
            f"1. Query the property graph for {apn} using `query_property_graph`.\n"
            f"2. Audit chain-of-title integrity with `get_chain_of_title`.\n"
            f"3. Run DCF valuation scenarios with `calculate_dcf_valuation`.\n"
            f"4. Assess geospatial risk and zoning with `assess_geospatial_risk`.\n"
            f"5. Check debt and lien waterfall with `analyze_encumbrance_waterfall`.\n"
            f"Deliver an institutional investment committee memo with recommendation."
        )

    @server.prompt("audit-chain-of-title")
    def prompt_audit_title(apn: str) -> str:
        """Prompt template for legal title examination and deed continuity check."""
        return (
            f"Analyze the title history for parcel {apn}.\n"
            f"Use `get_chain_of_title` to verify grantor-grantee lineage.\n"
            f"Identify any quitclaim deeds, gaps in ownership dates, or missing releases."
        )

    @server.prompt("screen-encumbrances")
    def prompt_screen_encumbrances(apn: str) -> str:
        """Prompt template for debt waterfall and distressed lien assessment."""
        return (
            f"Examine all recorded mortgages, deeds of trust, and liens on parcel {apn}.\n"
            f"Use `analyze_encumbrance_waterfall` to compute senior and cumulative LTV.\n"
            f"Flag any subordinated debt or cross-collateralization."
        )

    return server
