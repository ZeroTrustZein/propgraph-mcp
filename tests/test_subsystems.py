"""Unit and integration tests for PropGraph MCP subsystems."""

from __future__ import annotations

from datetime import date

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.server import create_mcp_server
from propgraph_mcp.subsystems.encumbrance import (
    LIEN_SENIORITY_RANKS,
    EncumbranceAnalyzer,
)
from propgraph_mcp.subsystems.entity_resolution import (
    EntityResolver,
    character_ngram_similarity,
    composite_entity_similarity,
    token_jaccard_similarity,
)
from propgraph_mcp.subsystems.sec_pipeline import (
    LeaseCommitmentSchedule,
    SECEdgarPipeline,
)
from propgraph_mcp.subsystems.spatial import (
    SpatialContiguityEngine,
    haversine_distance_feet,
    haversine_distance_meters,
)
from propgraph_mcp.subsystems.stream_validator import (
    DeedStreamValidator,
    RawDeedRecord,
)
from propgraph_mcp.types import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    PropertyParcel,
    PropertyType,
)


class TestStreamValidatorSubsystem:
    """Tests for DeedStreamValidator and municipal stream processing."""

    def test_schema_and_pipeline_sql_generation(self) -> None:
        validator = DeedStreamValidator(min_arms_length_price=1000.0)
        ddl = validator.generate_schema_ddl()
        assert "CREATE TABLE IF NOT EXISTS raw_deed_stream" in ddl
        assert "CREATE TABLE IF NOT EXISTS clean_deeds" in ddl
        assert "CREATE TABLE IF NOT EXISTS quarantine_deeds" in ddl

        sql = validator.generate_cleaning_pipeline_sql()
        assert "INSERT INTO quarantine_deeds" in sql
        assert "INSERT INTO clean_deeds" in sql
        assert "is_arms_length" in sql

    def test_validate_record_clean_and_arms_length(self) -> None:
        validator = DeedStreamValidator()
        raw = RawDeedRecord(
            raw_id="RAW-001",
            parcel_id="APN-100-200",
            grantor="Apex Property Holdings LLC",
            grantee="Beacon Commercial Capital Corp",
            sale_date="2026-05-15",
            sale_price_raw="$12,500,000.00",
            deed_type="Warranty Deed",
            recording_number="REC-2026-9876",
        )
        clean, quar = validator.validate_record(raw)
        assert quar is None
        assert clean is not None
        assert clean.deed_id == "RAW-001"
        assert clean.parcel_id == "APN-100-200"
        assert clean.sale_price == 12_500_000.0
        assert clean.sale_date == date(2026, 5, 15)
        assert clean.is_arms_length is True

    def test_validate_record_non_arms_length_quitclaim(self) -> None:
        validator = DeedStreamValidator()
        raw = {
            "raw_id": "RAW-002",
            "parcel_id": "APN-100-201",
            "grantor=": "Smith Family Trust",
            "grantor": "Smith Family Trust",
            "grantee": "Smith Holdings LLC",
            "sale_date": "06/01/2026",
            "sale_price_raw": 10.0,
            "deed_type": "Quitclaim Deed",
        }
        clean, quar = validator.validate_record(raw)
        assert quar is None
        assert clean is not None
        assert clean.sale_price == 10.0
        assert clean.sale_date == date(2026, 6, 1)
        assert clean.is_arms_length is False

    def test_validate_record_quarantine_reasons(self) -> None:
        validator = DeedStreamValidator(max_reasonable_price=100_000_000.0)

        # Missing parcel
        _, q1 = validator.validate_record({"parcel_id": "", "grantor": "A", "grantee": "B"})
        assert q1 is not None and q1.error_code == "MISSING_PARCEL_ID"

        # Missing parties
        _, q2 = validator.validate_record({"parcel_id": "P-1", "grantor": "", "grantee": "B"})
        assert q2 is not None and q2.error_code == "MISSING_PARTIES"

        # Invalid date
        _, q3 = validator.validate_record(
            {"parcel_id": "P-1", "grantor": "A", "grantee": "B", "sale_date": "not-a-date"}
        )
        assert q3 is not None and q3.error_code == "INVALID_DATE"

        # Invalid price
        _, q4 = validator.validate_record(
            {
                "parcel_id": "P-1",
                "grantor": "A",
                "grantee": "B",
                "sale_date": "2026-01-01",
                "sale_price_raw": "invalid",
            }
        )
        assert q4 is not None and q4.error_code == "INVALID_PRICE"

        # Outlier price
        _, q5 = validator.validate_record(
            {
                "parcel_id": "P-1",
                "grantor": "A",
                "grantee": "B",
                "sale_date": "2026-01-01",
                "sale_price_raw": 200_000_000.0,
            }
        )
        assert q5 is not None and q5.error_code == "OUTLIER_PRICE"

    def test_validate_batch_and_graph_ingestion(self) -> None:
        validator = DeedStreamValidator()
        records = [
            {
                "raw_id": "D-1",
                "parcel_id": "APN-999-01",
                "grantor": "Alpha LLC",
                "grantee": "Beta Corp",
                "sale_date": "2025-01-10",
                "sale_price_raw": 5_000_000,
            },
            {
                "raw_id": "D-2",
                "parcel_id": "APN-999-02",
                "grantor": "Beta Corp",
                "grantee": "Gamma REIT",
                "sale_date": "2026-02-15",
                "sale_price_raw": 7_500_000,
            },
            {
                "raw_id": "D-BAD",
                "parcel_id": "APN-999-03",
                "grantor": "",
                "grantee": "No Grantor",
                "sale_date": "2026-03-01",
                "sale_price_raw": 1_000_000,
            },
        ]
        clean_list, quar_list, summary = validator.validate_batch(records)
        assert summary.total_records == 3
        assert summary.clean_records == 2
        assert summary.quarantined_records == 1
        assert summary.total_dollar_volume == 12_500_000.0
        assert summary.arms_length_count == 2
        assert summary.quarantine_breakdown["MISSING_PARTIES"] == 1

        # Ingest to graph
        graph = TemporalPropGraph()
        count = validator.ingest_batch_to_graph(graph, clean_list)
        assert count == 2
        assert graph.node_count >= 4  # 2 deeds + entities


class TestSECEdgarPipelineSubsystem:
    """Tests for SECEdgarPipeline parsing and lease analysis."""

    def test_apn_extraction_from_text(self) -> None:
        text = """
        Item 2. Properties.
        The registrant owns parcel APN 102-45-678 located in Dallas, TX.
        Additionally, lease commitments apply to APN-880-990-01 in Austin, TX
        and Parcel 777-12-34 under a ground lease.
        """
        apns = SECEdgarPipeline.extract_apns_from_text(text)
        assert "APN-880-990-01" in apns
        assert any("102-45-678" in apn for apn in apns)
        assert any("777-12-34" in apn for apn in apns)

    def test_lease_commitment_extraction(self) -> None:
        filing_text = """
        NOTE 8 — LEASES
        Future minimum lease payments under non-cancelable operating leases as of Dec 31:
        Year 1: $1,500,000
        Year 2: $1,550,000
        Year 3: $1,600,000
        Year 4: $1,650,000
        Year 5: $1,700,000
        Thereafter: $4,500,000
        """
        sched = SECEdgarPipeline.extract_lease_commitments(
            filing_text, tenant_name="Acme Logistics Inc", fiscal_year=2026
        )
        assert sched is not None
        assert sched.year_1 == 1_500_000.0
        assert sched.year_2 == 1_550_000.0
        assert sched.year_3 == 1_600_000.0
        assert sched.year_5 == 1_700_000.0
        assert sched.thereafter == 4_500_000.0
        assert sched.total_commitment == 12_500_000.0

    def test_parse_and_attach_to_graph(self) -> None:
        pipeline = SECEdgarPipeline()
        raw = """
        FORM 10-K ANNUAL REPORT
        Properties disclosed include facility APN-333-444-55.
        Operating lease future commitments:
        Year 1: $2,000,000
        Year 2: $2,100,000
        Year 3: $2,200,000
        Thereafter: $10,000,000
        """
        parsed = pipeline.parse_filing(
            accession_number="0001193125-26-000100",
            cik="0001234567",
            company_name="Global Warehousing REIT",
            filing_type="10-K",
            filing_date=date(2026, 2, 28),
            raw_text=raw,
        )
        assert "APN-333-444-55" in parsed.properties_identified
        assert len(parsed.lease_schedules) == 1

        graph = TemporalPropGraph()
        result = pipeline.attach_to_graph(graph, parsed)
        assert result["accession_number"] == "0001193125-26-000100"
        assert result["properties_linked"] == 1
        assert result["lease_edges_added"] == 1

    def test_evaluate_tenant_concentration(self) -> None:
        pipeline = SECEdgarPipeline()
        t1 = LeaseCommitmentSchedule(
            tenant_name="MegaAnchor Corp",
            fiscal_year=2026,
            year_1=1_800_000.0,
            thereafter=5_000_000.0,
        )
        t2 = LeaseCommitmentSchedule(
            tenant_name="SubTenant LLC",
            fiscal_year=2026,
            year_1=400_000.0,
        )

        res = pipeline.evaluate_tenant_concentration(
            property_revenue=3_000_000.0, tenant_commitments=[t1, t2]
        )
        assert res["property_annual_revenue"] == 3_000_000.0
        assert res["top_tenant_share"] == 0.60
        assert res["concentration_risk"] == "critical"
        assert res["tenants"][0]["is_single_tenant_risk"] is True


class TestEntityResolutionSubsystem:
    """Tests for EntityResolver and beneficial ownership tracing."""

    def test_string_similarity_helpers(self) -> None:
        assert (
            token_jaccard_similarity("Apex Capital Partners", "Apex Capital Partners LLC") >= 0.75
        )
        assert character_ngram_similarity("Blackstone", "Blackstone Group") >= 0.60
        assert composite_entity_similarity("Prologis Trust Inc", "Prologis Trust REIT") >= 0.80

    def test_find_duplicate_entities_and_merge(self) -> None:
        resolver = EntityResolver(similarity_threshold=0.80)
        graph = TemporalPropGraph()

        # Add two near-identical entity nodes
        e1 = GraphNode(
            node_id="entity:starwood_capital_llc",
            node_type=NodeType.ENTITY,
            label="Starwood Capital, LLC",
            attributes={"cik": "000999888", "headquarters": "Miami, FL"},
        )
        e2 = GraphNode(
            node_id="entity:starwood_capital_inc",
            node_type=NodeType.ENTITY,
            label="Starwood Capital Inc.",
            attributes={"cik": "000999888", "phone": "555-0199"},
        )
        p1 = GraphNode(
            node_id="APN-001",
            node_type=NodeType.PROPERTY,
            label="Office Tower",
        )
        graph.add_node(e1)
        graph.add_node(e2)
        graph.add_node(p1)

        # e2 owns p1
        graph.add_edge(
            GraphEdge(
                source_id="entity:starwood_capital_inc",
                target_id="APN-001",
                edge_type=EdgeType.OWNS,
                effective_date=date(2026, 1, 1),
            )
        )

        dups = resolver.find_duplicate_entities(graph)
        assert len(dups) >= 1
        assert dups[0]["match_reason"] == "MATCHING_CIK"

        # Merge e2 into e1
        merged = resolver.merge_entities(
            graph, "entity:starwood_capital_llc", "entity:starwood_capital_inc"
        )
        assert merged is True
        assert not graph.graph.has_node("entity:starwood_capital_inc")
        assert graph.graph.has_node("entity:starwood_capital_llc")

        # Verify e1 now owns APN-001
        out_edges = list(graph.graph.out_edges("entity:starwood_capital_llc", data=True))
        assert any(
            target == "APN-001" and d.get("edge_type") == EdgeType.OWNS.value
            for _, target, d in out_edges
        )

        # Verify merged attributes
        attrs = graph.graph.nodes["entity:starwood_capital_llc"]["attributes"]
        assert attrs.get("phone") == "555-0199"
        assert "Starwood Capital Inc." in attrs.get("aliases", [])

    def test_trace_ultimate_beneficial_owners(self) -> None:
        resolver = EntityResolver()
        graph = TemporalPropGraph()

        # Chain: Operating LLC -> HoldCo Corp -> Parent Asset Manager
        n1 = GraphNode(node_id="ent:op_co", node_type=NodeType.ENTITY, label="OpCo LLC")
        n2 = GraphNode(node_id="ent:hold_co", node_type=NodeType.ENTITY, label="HoldCo Corp")
        n3 = GraphNode(
            node_id="ent:parent",
            node_type=NodeType.ENTITY,
            label="Global Asset Management",
            attributes={"cik": "000111222"},
        )
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)

        # n2 owns n1, n3 owns n2
        graph.add_edge(
            GraphEdge(source_id="ent:hold_co", target_id="ent:op_co", edge_type=EdgeType.OWNS)
        )
        graph.add_edge(
            GraphEdge(source_id="ent:parent", target_id="ent:hold_co", edge_type=EdgeType.OWNS)
        )

        ubos = resolver.trace_ultimate_beneficial_owners(graph, "ent:op_co")
        assert len(ubos) == 2
        assert ubos[0]["entity_id"] == "ent:hold_co"
        assert ubos[1]["entity_id"] == "ent:parent"
        assert ubos[1]["is_terminal_parent"] is True
        assert ubos[1]["cik"] == "000111222"


class TestEncumbranceSubsystem:
    """Tests for EncumbranceAnalyzer, priority ranking, and waterfall."""

    def test_lien_seniority_ranks(self) -> None:
        analyzer = EncumbranceAnalyzer()
        assert analyzer.get_lien_seniority("Tax Lien") == 1
        assert analyzer.get_lien_seniority("Mechanics Lien") == 2
        assert analyzer.get_lien_seniority("First Mortgage") == 3
        assert analyzer.get_lien_seniority("Mezzanine Debt") == 4
        assert analyzer.get_lien_seniority("UCC Filing") == 5
        assert analyzer.get_lien_seniority("Easement") == 7
        assert analyzer.get_lien_seniority("Unknown Encumbrance") == 99
        assert LIEN_SENIORITY_RANKS["tax_lien"] == 1

    def test_parcel_waterfall_and_recovery(self) -> None:
        analyzer = EncumbranceAnalyzer()
        graph = TemporalPropGraph()
        apn = "APN-WATERFALL-01"

        graph.add_node(
            GraphNode(node_id=apn, node_type=NodeType.PROPERTY, label="Commercial Complex")
        )
        graph.add_node(
            GraphNode(
                node_id="lender:city_tax", node_type=NodeType.LENDER, label="County Tax Collector"
            )
        )
        graph.add_node(
            GraphNode(
                node_id="lender:first_bank", node_type=NodeType.LENDER, label="First National Bank"
            )
        )
        graph.add_node(
            GraphNode(
                node_id="lender:mezz_cap", node_type=NodeType.LENDER, label="Mezz Capital LLC"
            )
        )

        # Add encumbrances:
        # 1. Tax lien: $200,000
        graph.add_edge(
            GraphEdge(
                source_id="lender:city_tax",
                target_id=apn,
                edge_type=EdgeType.ENCUMBERS,
                attributes={"instrument": "tax_lien", "amount": 200_000.0},
                effective_date=date(2026, 1, 10),
            )
        )
        # 2. Senior mortgage: $7,000,000
        graph.add_edge(
            GraphEdge(
                source_id="lender:first_bank",
                target_id=apn,
                edge_type=EdgeType.ENCUMBERS,
                attributes={"instrument": "first_mortgage", "amount": 7_000_000.0},
                effective_date=date(2024, 6, 1),
            )
        )
        # 3. Mezzanine debt: $3,000,000
        graph.add_edge(
            GraphEdge(
                source_id="lender:mezz_cap",
                target_id=apn,
                edge_type=EdgeType.ENCUMBERS,
                attributes={"instrument": "mezzanine_debt", "amount": 3_000_000.0},
                effective_date=date(2025, 2, 1),
            )
        )

        # Property valued at $9,000,000 (total debt is $10.2M -> underwater)
        res = analyzer.analyze_parcel_encumbrance_waterfall(
            graph, apn, property_valuation=9_000_000.0
        )
        assert res["total_debt"] == 10_200_000.0
        assert res["has_senior_tax_lien"] is True
        assert res["overall_ltv"] == round(10_200_000.0 / 9_000_000.0, 4)
        assert res["remaining_equity"] == 0.0

        waterfall = res["waterfall"]
        assert len(waterfall) == 3
        # First tranche: Tax lien (100% covered)
        assert waterfall[0]["instrument"] == "tax_lien"
        assert waterfall[0]["recovery_percentage"] == 1.0

        # Second tranche: First mortgage (100% covered, cumulative $7.2M <= $9M)
        assert waterfall[1]["instrument"] == "first_mortgage"
        assert waterfall[1]["recovery_percentage"] == 1.0

        # Third tranche: Mezzanine debt ($1.8M remaining of $3.0M -> 60% recovery)
        assert waterfall[2]["instrument"] == "mezzanine_debt"
        assert waterfall[2]["recovery_percentage"] == 0.60

    def test_detect_cross_collateralization(self) -> None:
        analyzer = EncumbranceAnalyzer()
        graph = TemporalPropGraph()

        p1 = "APN-CROSS-01"
        p2 = "APN-CROSS-02"
        lender = "lender:mega_credit_corp"

        graph.add_node(GraphNode(node_id=p1, node_type=NodeType.PROPERTY, label="Site A"))
        graph.add_node(GraphNode(node_id=p2, node_type=NodeType.PROPERTY, label="Site B"))
        graph.add_node(
            GraphNode(node_id=lender, node_type=NodeType.LENDER, label="Mega Credit Corp")
        )

        # Blanket loan of $15M encumbering both parcels
        graph.add_edge(
            GraphEdge(
                source_id=lender,
                target_id=p1,
                edge_type=EdgeType.ENCUMBERS,
                attributes={"amount": 15_000_000.0, "instrument": "blanket_mortgage"},
            )
        )
        graph.add_edge(
            GraphEdge(
                source_id=lender,
                target_id=p2,
                edge_type=EdgeType.ENCUMBERS,
                attributes={"amount": 15_000_000.0, "instrument": "blanket_mortgage"},
            )
        )

        cross = analyzer.detect_cross_collateralization(graph)
        assert len(cross) == 1
        assert cross[0]["lender_id"] == lender
        assert cross[0]["parcel_count"] == 2
        assert set(cross[0]["parcels"]) == {p1, p2}


class TestSpatialContiguitySubsystem:
    """Tests for SpatialContiguityEngine and assemblage analysis."""

    def test_haversine_distances(self) -> None:
        # Distance between downtown Chicago (41.881832, -87.623177) and nearby point (~111 meters)
        d_meters = haversine_distance_meters(41.881832, -87.623177, 41.882832, -87.623177)
        assert 100.0 < d_meters < 125.0

        d_feet = haversine_distance_feet(41.881832, -87.623177, 41.882832, -87.623177)
        assert abs(d_feet - (d_meters * 3.28084)) < 0.01

    def test_portfolio_bounding_box(self) -> None:
        p1 = PropertyParcel(
            apn="P1",
            address="100 Main St",
            city="Chicago",
            state="IL",
            zip_code="60601",
            property_type=PropertyType.OFFICE,
            square_feet=50000,
            year_built=2015,
            zoning_code="C3",
            latitude=41.880,
            longitude=-87.630,
        )
        p2 = PropertyParcel(
            apn="P2",
            address="200 Main St",
            city="Chicago",
            state="IL",
            zip_code="60601",
            property_type=PropertyType.OFFICE,
            square_feet=45000,
            year_built=2018,
            zoning_code="C3",
            latitude=41.885,
            longitude=-87.625,
        )
        bbox = SpatialContiguityEngine.calculate_bounding_box([p1, p2])
        assert bbox["total_geocoded_parcels"] == 2
        assert bbox["min_latitude"] == 41.880
        assert bbox["max_latitude"] == 41.885
        assert bbox["centroid"]["latitude"] == 41.8825

    def test_infer_spatial_adjacencies_and_assemblage_clusters(self) -> None:
        engine = SpatialContiguityEngine(default_adjacency_threshold_meters=200.0)
        graph = TemporalPropGraph()

        # Two neighboring parcels owned by the same entity
        owner_id = "entity:harbor_holdings_llc"
        graph.add_node(
            GraphNode(node_id=owner_id, node_type=NodeType.ENTITY, label="Harbor Holdings LLC")
        )

        p1_data = PropertyParcel(
            apn="APN-NEIGHBOR-1",
            address="101 Harbor Way",
            city="Seattle",
            state="WA",
            zip_code="98101",
            property_type=PropertyType.INDUSTRIAL,
            square_feet=60000,
            year_built=2010,
            zoning_code="M2",
            latitude=47.6050,
            longitude=-122.3350,
        )
        p2_data = PropertyParcel(
            apn="APN-NEIGHBOR-2",
            address="103 Harbor Way",
            city="Seattle",
            state="WA",
            zip_code="98101",
            property_type=PropertyType.INDUSTRIAL,
            square_feet=70000,
            year_built=2012,
            zoning_code="M2",
            latitude=47.6055,  # ~55m away
            longitude=-122.3350,
        )
        graph.add_property(p1_data)
        graph.add_property(p2_data)

        # Connect owner to both
        graph.add_edge(
            GraphEdge(source_id=owner_id, target_id="APN-NEIGHBOR-1", edge_type=EdgeType.OWNS)
        )
        graph.add_edge(
            GraphEdge(source_id=owner_id, target_id="APN-NEIGHBOR-2", edge_type=EdgeType.OWNS)
        )

        inferred = engine.infer_spatial_adjacencies(graph, max_distance_meters=150.0)
        assert inferred == 1

        assemblages = engine.find_assemblage_clusters(graph, max_distance_meters=150.0)
        assert len(assemblages) == 1
        cluster = assemblages[0]
        assert cluster["owner_entity"] == owner_id
        assert cluster["parcel_count"] == 2
        assert cluster["combined_square_feet"] == 130000
        assert cluster["estimated_density_uplift"] == 130000 * 0.15


class TestMCPServerSubsystemTools:
    """Tests verifying MCPServer integration tools for subsystems."""

    def test_mcp_server_subsystem_tools_registered(self) -> None:
        import asyncio

        server = create_mcp_server()
        assert server.name == "propgraph-mcp"
        tools = asyncio.run(server.list_tools())
        tool_names = [t.name for t in tools]
        assert "validate_deed_stream" in tool_names
        assert "parse_sec_disclosures" in tool_names
        assert "resolve_entity_network" in tool_names
        assert "analyze_encumbrance_waterfall" in tool_names
        assert "analyze_spatial_assemblage" in tool_names

    def test_mcp_server_validate_deed_stream_invocation(self) -> None:
        import asyncio

        server = create_mcp_server()
        res = asyncio.run(
            server.call_tool(
                "validate_deed_stream",
                {
                    "records": [
                        {
                            "raw_id": "D-01",
                            "parcel_id": "APN-111-222",
                            "grantor": "Alpha LLC",
                            "grantee": "Beta Corp",
                            "sale_date": "2026-04-01",
                            "sale_price_raw": 5000000,
                        }
                    ],
                    "ingest_clean": True,
                },
            )
        )
        assert res.is_error is False
        assert "summary" in res.structured_content["result"]
        assert res.structured_content["result"]["ingested_into_graph"] == 1

    def test_mcp_server_analyze_spatial_assemblage_invocation(self) -> None:
        import asyncio

        server = create_mcp_server()
        res = asyncio.run(
            server.call_tool(
                "analyze_spatial_assemblage",
                {"max_distance_meters": 300.0},
            )
        )
        assert res.is_error is False
        assert "adjacencies_inferred" in res.structured_content["result"]
        assert "assemblages_found" in res.structured_content["result"]
