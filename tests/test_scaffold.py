"""Scaffolding and integration test suite for PropGraph MCP."""

from __future__ import annotations

from click.testing import CliRunner

import propgraph_mcp
from propgraph_mcp import __version__, cli
from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.server import create_mcp_server
from propgraph_mcp.types import (
    DeedRecord,
    PropertyParcel,
    SECFilingRecord,
)
from propgraph_mcp.valuation import DCFValuationEngine, calculate_irr


def test_package_metadata() -> None:
    """Verify package version and module availability."""
    assert __version__ == "0.1.0"
    assert propgraph_mcp.__version__ == "0.1.0"
    assert cli is not None


def test_cli_help(cli_runner: CliRunner) -> None:
    """Verify CLI root command help string."""
    result = cli_runner.invoke(cli.cli, ["--help"])
    assert result.exit_code == 0
    assert "PropGraph MCP" in result.output
    assert "info" in result.output
    assert "serve" in result.output
    assert "underwrite" in result.output


def test_cli_info(cli_runner: CliRunner) -> None:
    """Verify info subcommand displays subsystem status."""
    result = cli_runner.invoke(cli.cli, ["info"])
    assert result.exit_code == 0
    assert "PropGraph MCP" in result.output
    assert "v0.1.0" in result.output
    assert "Temporal Graph-RAG" in result.output
    assert "Multi-Scenario DCF" in result.output


def test_cli_underwrite(cli_runner: CliRunner) -> None:
    """Verify underwrite CLI command runs multi-scenario DCF."""
    result = cli_runner.invoke(
        cli.cli,
        [
            "underwrite",
            "--apn",
            "APN-TEST-1",
            "--price",
            "5000000",
            "--revenue",
            "600000",
            "--expenses",
            "200000",
        ],
    )
    assert result.exit_code == 0
    assert "CRE DCF Underwriting Results: APN-TEST-1" in result.output
    assert "Base" in result.output
    assert "Bull" in result.output
    assert "Bear" in result.output


def test_irr_calculation() -> None:
    """Verify numerical IRR convergence with known series."""
    # -100 initial, +60 year 1, +60 year 2 -> ~13.06%
    cfs = [-100.0, 60.0, 60.0]
    irr = calculate_irr(cfs)
    assert 0.12 <= irr <= 0.14


def test_graph_lineage_and_timeline(
    sample_parcel: PropertyParcel,
    sample_deed: DeedRecord,
    sample_sec_filing: SECFilingRecord,
) -> None:
    """Verify graph creation, node linking, and ownership timeline query."""
    graph = TemporalPropGraph()
    graph.add_property(sample_parcel)
    assert graph.node_count == 1

    graph.add_deed(sample_deed)
    assert graph.node_count >= 4  # property, deed, grantor, grantee
    assert graph.edge_count >= 3

    graph.add_sec_filing(sample_sec_filing)
    assert graph.node_count >= 5

    timeline = graph.get_ownership_timeline(sample_parcel.apn)
    assert len(timeline) == 1
    assert timeline[0]["owner_name"] == sample_deed.grantee
    assert timeline[0]["sale_price"] == sample_deed.sale_price

    related = graph.get_related_entities(sample_parcel.apn, depth=2)
    assert len(related) > 0


def test_dcf_valuation_engine() -> None:
    """Verify multi-scenario DCF engine output integrity."""
    engine = DCFValuationEngine()
    results = engine.run_all_scenarios(
        property_id="PROP-100",
        initial_gross_revenue=1_000_000.0,
        initial_operating_expenses=350_000.0,
        purchase_price=8_000_000.0,
    )

    assert "Base" in results
    assert "Bull" in results
    assert "Bear" in results

    base = results["Base"]
    assert base.property_id == "PROP-100"
    assert len(base.cash_flows) == 5
    assert base.terminal_value > 0
    assert base.irr != 0.0

    # Bull should have higher NPV than Bear
    assert results["Bull"].npv > results["Bear"].npv


def test_geospatial_risk_engine(sample_parcel: PropertyParcel) -> None:
    """Verify environmental, seismic, and zoning risk metrics calculation."""
    risk_engine = GeospatialRiskEngine()
    metrics = risk_engine.assess_parcel_risk(
        parcel=sample_parcel,
        flood_zone="AE",
        seismic_zone=4,
        has_brownfield_proximity=True,
    )

    assert metrics.parcel_id == sample_parcel.apn
    assert metrics.flood_hazard_score == 85.0
    assert metrics.seismic_risk_score == 80.0
    assert metrics.environmental_contamination_risk == 80.0
    assert metrics.composite_risk_score > 50.0


def test_mcp_server_initialization() -> None:
    """Verify MCP Server factory registers tools and sets name."""
    server = create_mcp_server("test-propgraph")
    assert server.name == "test-propgraph"
