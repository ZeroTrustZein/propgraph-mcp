"""Comprehensive test suite for PropGraph MCPServer interface."""

from __future__ import annotations

import asyncio
import json

import pytest

from propgraph_mcp.server import create_mcp_server


@pytest.fixture
def mcp_server():
    """Create fresh MCPServer instance for testing."""
    return create_mcp_server()


def test_mcp_server_tools_registered(mcp_server) -> None:
    """Verify all 14 MCP underwriting and risk tools are registered."""

    async def _test():
        tools = await mcp_server.list_tools()
        tool_names = {t.name for t in tools}

        expected_tools = {
            "query_property_graph",
            "ingest_deed_record",
            "ingest_sec_filing",
            "calculate_dcf_valuation",
            "assess_geospatial_risk",
            "run_underwriting_pipeline",
            "validate_deed_stream",
            "parse_sec_disclosures",
            "resolve_entity_network",
            "analyze_encumbrance_waterfall",
            "analyze_spatial_assemblage",
            "get_chain_of_title",
            "evaluate_zoning_capacity",
            "project_climate_risk",
        }
        assert expected_tools.issubset(tool_names)

    asyncio.run(_test())


def test_mcp_tool_query_property_graph(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool("query_property_graph", {"apn": "APN-MCP-1"})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["apn"] == "APN-MCP-1"
        assert "ownership_timeline" in data
        assert "connected_entities" in data

    asyncio.run(_test())


def test_mcp_tool_ingest_deed(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool(
            "ingest_deed_record",
            {
                "deed_id": "DEED-MCP-10",
                "parcel_id": "APN-MCP-10",
                "grantor": "Oak Holdings LLC",
                "grantee": "Pine Real Estate Trust",
                "transfer_date": "2023-01-15",
                "sale_price": 4_500_000.0,
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["status"] == "ingested"
        assert data["deed_id"] == "DEED-MCP-10"

    asyncio.run(_test())


def test_mcp_tool_calculate_dcf(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool(
            "calculate_dcf_valuation",
            {
                "property_id": "APN-VAL-1",
                "gross_revenue": 1_000_000.0,
                "operating_expenses": 350_000.0,
                "purchase_price": 8_000_000.0,
                "scenario": "Base",
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["property_id"] == "APN-VAL-1"
        assert data["npv"] is not None
        assert data["irr"] is not None

    asyncio.run(_test())


def test_mcp_tool_assess_risk(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool(
            "assess_geospatial_risk",
            {
                "apn": "APN-RSK-1",
                "address": "400 Market St",
                "city": "San Francisco",
                "state": "CA",
                "zip_code": "94105",
                "property_type": "office",
                "square_feet": 75_000.0,
                "year_built": 2005,
                "flood_zone": "X",
                "seismic_zone": 4,
                "has_brownfield_proximity": False,
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["parcel_id"] == "APN-RSK-1"
        assert data["composite_risk_score"] > 0

    asyncio.run(_test())


def test_mcp_tool_run_underwriting_pipeline(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool(
            "run_underwriting_pipeline",
            {
                "apn": "APN-UW-1",
                "address": "500 Pine St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98101",
                "property_type": "multifamily",
                "square_feet": 60_000.0,
                "year_built": 2018,
                "purchase_price": 12_000_000.0,
                "gross_revenue": 1_500_000.0,
                "operating_expenses": 450_000.0,
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["property_id"] == "APN-UW-1"
        assert "Base" in data["scenarios"]
        assert "recommendation" in data

    asyncio.run(_test())


def test_mcp_tool_validate_deed_stream(mcp_server) -> None:
    async def _test():
        records = [
            {
                "raw_id": "R1",
                "parcel_id": "APN-VALSTREAM-1",
                "grantor": "Grantor Corp",
                "grantee": "Grantee LP",
                "sale_date": "2024-03-01",
                "sale_price_raw": 3_000_000.0,
            }
        ]
        res = await mcp_server.call_tool("validate_deed_stream", {"records": records})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["summary"]["total_records"] == 1
        assert data["ingested_into_graph"] == 1

    asyncio.run(_test())


def test_mcp_tool_get_chain_of_title(mcp_server) -> None:
    async def _test():
        await mcp_server.call_tool(
            "ingest_deed_record",
            {
                "deed_id": "DEED-COT-1",
                "parcel_id": "APN-COT-1",
                "grantor": "Original Owner LLC",
                "grantee": "Current Owner Inc",
                "transfer_date": "2022-04-10",
                "sale_price": 5_000_000.0,
            },
        )
        res = await mcp_server.call_tool("get_chain_of_title", {"apn": "APN-COT-1"})
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["apn"] == "APN-COT-1"
        assert "chain_audit" in data
        assert "timeline" in data

    asyncio.run(_test())


def test_mcp_tool_evaluate_zoning(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool(
            "evaluate_zoning_capacity",
            {
                "parcel_id": "APN-ZONE-1",
                "lot_size_sqft": 40_000.0,
                "building_footprint_sqft": 15_000.0,
                "total_building_sqft": 60_000.0,
                "stories": 4,
                "building_height_ft": 55.0,
                "zoning_code": "C-1",
                "parking_spaces": 120,
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["parcel_id"] == "APN-ZONE-1"
        assert "variance_required" in data

    asyncio.run(_test())


def test_mcp_tool_climate_risk(mcp_server) -> None:
    async def _test():
        res = await mcp_server.call_tool(
            "project_climate_risk",
            {
                "apn": "APN-CLIM-1",
                "horizon_year": 2040,
                "rcp_scenario": "RCP4.5",
            },
        )
        assert not res.is_error
        data = res.structured_content["result"]
        assert data["parcel_id"] == "APN-CLIM-1"
        assert data["horizon_year"] == 2040

    asyncio.run(_test())


def test_mcp_resources_and_templates(mcp_server) -> None:
    """Verify static resources and parameterized resource templates."""

    async def _test():
        resources = await mcp_server.list_resources()
        resource_uris = {r.uri for r in resources}
        assert "graph://summary" in resource_uris

        templates = await mcp_server.list_resource_templates()
        template_uris = {t.uri_template for t in templates}
        assert "property://{apn}/timeline" in template_uris
        assert "property://{apn}/encumbrances" in template_uris
        assert "property://{apn}/risk" in template_uris

    asyncio.run(_test())


def test_mcp_read_resources(mcp_server) -> None:
    """Verify reading resources via URI."""

    async def _test():
        summary_res = await mcp_server.read_resource("graph://summary")
        assert len(summary_res) == 1
        summary_data = json.loads(summary_res[0].content)
        assert "total_nodes" in summary_data

        timeline_res = await mcp_server.read_resource("property://APN-TEST-RES/timeline")
        assert len(timeline_res) == 1
        timeline_data = json.loads(timeline_res[0].content)
        assert timeline_data["apn"] == "APN-TEST-RES"

        enc_res = await mcp_server.read_resource("property://APN-TEST-RES/encumbrances")
        assert len(enc_res) == 1
        enc_data = json.loads(enc_res[0].content)
        assert enc_data["apn"] == "APN-TEST-RES"

    asyncio.run(_test())


def test_mcp_prompts(mcp_server) -> None:
    """Verify prompt templates generation for LLM swarm."""

    async def _test():
        prompts = await mcp_server.list_prompts()
        prompt_names = {p.name for p in prompts}
        assert "underwrite-property" in prompt_names
        assert "audit-chain-of-title" in prompt_names
        assert "screen-encumbrances" in prompt_names

        p = await mcp_server.get_prompt("underwrite-property", {"apn": "APN-MEMO-1"})
        assert len(p.messages) >= 1
        assert "APN-MEMO-1" in p.messages[0].content.text

    asyncio.run(_test())
