"""Comprehensive test suite for propgraph_mcp.types domain models."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

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


class TestEnums:
    """Verify all domain enums have expected members and string serialization."""

    def test_property_type_members(self) -> None:
        assert PropertyType.OFFICE == "office"
        assert PropertyType.RETAIL == "retail"
        assert PropertyType.MULTIFAMILY == "multifamily"
        assert PropertyType.INDUSTRIAL == "industrial"
        assert PropertyType.MIXED_USE == "mixed_use"
        assert PropertyType.HOSPITALITY == "hospitality"

    def test_document_type_members(self) -> None:
        assert DocumentType.WARRANTY_DEED == "Warranty Deed"
        assert DocumentType.SPECIAL_WARRANTY_DEED == "Special Warranty Deed"
        assert DocumentType.QUITCLAIM_DEED == "Quitclaim Deed"
        assert DocumentType.GRANT_DEED == "Grant Deed"
        assert DocumentType.DEED_OF_TRUST == "Deed of Trust"
        assert DocumentType.MORTGAGE == "Mortgage"

    def test_sec_filing_type_members(self) -> None:
        assert SECFilingType.FORM_10K == "10-K"
        assert SECFilingType.FORM_10Q == "10-Q"
        assert SECFilingType.FORM_8K == "8-K"

    def test_scenario_type_members(self) -> None:
        assert ScenarioType.BASE == "Base"
        assert ScenarioType.BULL == "Bull"
        assert ScenarioType.BEAR == "Bear"

    def test_risk_tier_members(self) -> None:
        assert RiskTier.LOW == "low"
        assert RiskTier.MODERATE == "moderate"
        assert RiskTier.HIGH == "high"
        assert RiskTier.CRITICAL == "critical"

    def test_node_type_members(self) -> None:
        assert NodeType.PROPERTY == "property"
        assert NodeType.ENTITY == "entity"
        assert NodeType.DEED == "deed"
        assert NodeType.SEC_FILING == "sec_filing"
        assert NodeType.LENDER == "lender"
        assert NodeType.MUNICIPALITY == "municipality"

    def test_edge_type_members(self) -> None:
        assert EdgeType.OWNS == "owns"
        assert EdgeType.TRANSFERRED_TO == "transferred_to"
        assert EdgeType.FINANCED_BY == "financed_by"
        assert EdgeType.DISCLOSED_IN == "disclosed_in"
        assert EdgeType.LEASES_TO == "leases_to"
        assert EdgeType.ENCUMBERS == "encumbers"


class TestPropertyParcel:
    """Validation and boundary tests for PropertyParcel."""

    def test_valid_parcel_minimal(self) -> None:
        parcel = PropertyParcel(
            apn="APN-001",
            address="100 Pine St",
            city="San Francisco",
            state="CA",
            zip_code="94111",
            square_feet=25000.0,
            year_built=1985,
        )
        assert parcel.apn == "APN-001"
        assert parcel.property_type == PropertyType.OFFICE
        assert parcel.zoning_code == "C-1"
        assert parcel.latitude is None
        assert parcel.longitude is None

    def test_valid_parcel_full(self) -> None:
        parcel = PropertyParcel(
            apn="APN-002",
            address="200 Broadway",
            city="New York",
            state="NY",
            zip_code="10038",
            property_type=PropertyType.MIXED_USE,
            square_feet=150000.0,
            year_built=2020,
            zoning_code="C6-4",
            latitude=40.7115,
            longitude=-74.0071,
        )
        assert parcel.property_type == PropertyType.MIXED_USE
        assert parcel.latitude == 40.7115
        assert parcel.longitude == -74.0071

    def test_invalid_square_feet_zero_or_negative(self) -> None:
        with pytest.raises(ValidationError):
            PropertyParcel(
                apn="APN-ERR",
                address="1 Main St",
                city="Austin",
                state="TX",
                zip_code="78701",
                square_feet=0.0,
                year_built=2000,
            )

    def test_invalid_year_built(self) -> None:
        with pytest.raises(ValidationError):
            PropertyParcel(
                apn="APN-ERR",
                address="1 Main St",
                city="Austin",
                state="TX",
                zip_code="78701",
                square_feet=1000.0,
                year_built=1400,
            )

    def test_invalid_latitude_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PropertyParcel(
                apn="APN-ERR",
                address="1 Main St",
                city="Austin",
                state="TX",
                zip_code="78701",
                square_feet=1000.0,
                year_built=2000,
                latitude=95.0,
            )

    def test_invalid_longitude_bounds(self) -> None:
        with pytest.raises(ValidationError):
            PropertyParcel(
                apn="APN-ERR",
                address="1 Main St",
                city="Austin",
                state="TX",
                zip_code="78701",
                square_feet=1000.0,
                year_built=2000,
                longitude=-185.0,
            )

    def test_serialization_roundtrip(self) -> None:
        parcel = PropertyParcel(
            apn="APN-ROUNDTRIP",
            address="500 Howard St",
            city="San Francisco",
            state="CA",
            zip_code="94105",
            square_feet=50000.0,
            year_built=2015,
            latitude=37.789,
            longitude=-122.398,
        )
        data = parcel.model_dump()
        reconstituted = PropertyParcel.model_validate(data)
        assert reconstituted == parcel


class TestDeedRecord:
    """Validation and boundary tests for DeedRecord."""

    def test_valid_deed(self) -> None:
        deed = DeedRecord(
            deed_id="D-101",
            parcel_id="APN-001",
            grantor="Seller LLC",
            grantee="Buyer Corp",
            transfer_date=date(2023, 6, 1),
            sale_price=12000000.0,
        )
        assert deed.document_type == "Warranty Deed"
        assert deed.sale_price == 12000000.0

    def test_negative_sale_price_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DeedRecord(
                deed_id="D-ERR",
                parcel_id="APN-001",
                grantor="Seller LLC",
                grantee="Buyer Corp",
                transfer_date=date(2023, 6, 1),
                sale_price=-500.0,
            )

    def test_zero_sale_price_permitted(self) -> None:
        deed = DeedRecord(
            deed_id="D-QUITCLAIM",
            parcel_id="APN-001",
            grantor="Trustee A",
            grantee="Trustee B",
            transfer_date=date(2023, 1, 1),
            sale_price=0.0,
            document_type=DocumentType.QUITCLAIM_DEED.value,
        )
        assert deed.sale_price == 0.0


class TestSECFilingRecord:
    """Validation tests for SEC EDGAR filing model."""

    def test_sec_filing_defaults(self) -> None:
        filing = SECFilingRecord(
            accession_number="0001-23-000456",
            cik="0001234567",
            company_name="Realty Trust Inc",
            filing_date=date(2023, 12, 31),
        )
        assert filing.filing_type == "10-K"
        assert filing.properties_mentioned == []
        assert filing.lease_obligations == {}
        assert filing.raw_excerpt is None

    def test_sec_filing_full(self) -> None:
        filing = SECFilingRecord(
            accession_number="0001-23-000456",
            cik="0001234567",
            company_name="Realty Trust Inc",
            filing_type=SECFilingType.FORM_10Q.value,
            filing_date=date(2023, 9, 30),
            period_end=date(2023, 9, 30),
            properties_mentioned=["742 Market St", "500 Howard St"],
            lease_obligations={"2024": 1500000.0, "2025": 1550000.0},
            raw_excerpt="Item 2. Properties: Tenant leased 45,000 RSF under 10-year term.",
        )
        assert len(filing.properties_mentioned) == 2
        assert filing.lease_obligations["2024"] == 1500000.0


class TestGraphEntities:
    """Validation tests for GraphNode and GraphEdge."""

    def test_graph_node_temporal_validity(self) -> None:
        node = GraphNode(
            node_id="prop:1",
            node_type=NodeType.PROPERTY,
            label="Parcel 1",
            valid_from=datetime(2020, 1, 1, 0, 0),
            valid_to=datetime(2025, 1, 1, 0, 0),
        )
        assert node.node_id == "prop:1"

    def test_graph_node_invalid_temporal_order(self) -> None:
        with pytest.raises(ValidationError, match="valid_from must be before or equal to valid_to"):
            GraphNode(
                node_id="prop:1",
                node_type=NodeType.PROPERTY,
                label="Parcel 1",
                valid_from=datetime(2025, 1, 1, 0, 0),
                valid_to=datetime(2020, 1, 1, 0, 0),
            )

    def test_graph_edge_creation(self) -> None:
        edge = GraphEdge(
            source_id="entity:seller",
            target_id="deed:101",
            edge_type=EdgeType.TRANSFERRED_TO,
            effective_date=date(2023, 5, 1),
        )
        assert edge.edge_type == EdgeType.TRANSFERRED_TO
        assert edge.source_id == "entity:seller"


class TestDCFScenario:
    """Validation and boundary tests for DCFScenario parameters."""

    def test_default_scenario(self) -> None:
        scenario = DCFScenario()
        assert scenario.scenario_name == "Base"
        assert scenario.discount_rate == 0.08
        assert scenario.exit_cap_rate == 0.065
        assert scenario.holding_period_years == 5
        assert scenario.rent_growth_rate == 0.03
        assert scenario.expense_growth_rate == 0.025
        assert scenario.vacancy_rate == 0.05

    def test_invalid_discount_rate(self) -> None:
        with pytest.raises(ValidationError):
            DCFScenario(discount_rate=1.5)

    def test_invalid_exit_cap_rate_zero_or_negative(self) -> None:
        with pytest.raises(ValidationError):
            DCFScenario(exit_cap_rate=0.0)

    def test_invalid_holding_period(self) -> None:
        with pytest.raises(ValidationError):
            DCFScenario(holding_period_years=0)


class TestGeospatialRiskMetrics:
    """Validation tests for GeospatialRiskMetrics and risk tier derivation."""

    def test_risk_metrics_defaults(self) -> None:
        metrics = GeospatialRiskMetrics(parcel_id="APN-001")
        assert metrics.composite_risk_score == 0.0
        assert metrics.risk_tier == RiskTier.LOW

    def test_risk_tier_classification(self) -> None:
        low = GeospatialRiskMetrics(parcel_id="P1", composite_risk_score=15.0)
        mod = GeospatialRiskMetrics(parcel_id="P2", composite_risk_score=35.0)
        high = GeospatialRiskMetrics(parcel_id="P3", composite_risk_score=60.0)
        crit = GeospatialRiskMetrics(parcel_id="P4", composite_risk_score=85.0)

        assert low.risk_tier == RiskTier.LOW
        assert mod.risk_tier == RiskTier.MODERATE
        assert high.risk_tier == RiskTier.HIGH
        assert crit.risk_tier == RiskTier.CRITICAL

    def test_invalid_score_above_100(self) -> None:
        with pytest.raises(ValidationError):
            GeospatialRiskMetrics(parcel_id="P1", flood_hazard_score=105.0)


class TestUnderwritingSummary:
    """Validation test for comprehensive UnderwritingSummary assembly."""

    def test_summary_assembly(self) -> None:
        parcel = PropertyParcel(
            apn="APN-SUM-1",
            address="100 Main St",
            city="Seattle",
            state="WA",
            zip_code="98101",
            square_feet=40000.0,
            year_built=2010,
        )
        risk = GeospatialRiskMetrics(parcel_id=parcel.apn, composite_risk_score=20.0)
        cf = [
            CashFlowYear(
                year=1,
                gross_revenue=1000000.0,
                operating_expenses=400000.0,
                net_operating_income=600000.0,
                debt_service=250000.0,
                net_cash_flow=350000.0,
            )
        ]
        val = ValuationOutput(
            property_id=parcel.apn,
            scenario_name="Base",
            purchase_price=8000000.0,
            npv=8500000.0,
            irr=0.12,
            terminal_value=9000000.0,
            cash_flows=cf,
            total_net_cash_flow=350000.0,
        )
        summary = UnderwritingSummary(
            property_id=parcel.apn,
            parcel=parcel,
            scenarios={"Base": val},
            risk_metrics=risk,
            related_entities_count=3,
            recommendation="Favorable acquisition candidate.",
        )
        assert summary.property_id == "APN-SUM-1"
        assert summary.risk_metrics.risk_tier == RiskTier.LOW
        assert summary.scenarios["Base"].irr == 0.12

        # Roundtrip JSON serialization check
        json_data = summary.model_dump_json()
        assert "APN-SUM-1" in json_data
        reloaded = UnderwritingSummary.model_validate_json(json_data)
        assert reloaded.property_id == summary.property_id
