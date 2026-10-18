"""Unit tests for PropGraph MCP core algorithms and primary logic."""

from __future__ import annotations

from datetime import date

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.types import (
    CashFlowYear,
    DeedRecord,
    DocumentType,
    PropertyParcel,
    PropertyType,
    SECFilingRecord,
)
from propgraph_mcp.valuation import DCFValuationEngine, calculate_irr


class TestTemporalPropGraphCore:
    """Core logic and algorithmic tests for TemporalPropGraph."""

    def test_normalize_entity_name(self) -> None:
        """Verify entity name standardizer strips legal suffixes and punctuation."""
        assert (
            TemporalPropGraph.normalize_entity_name("Blackstone Real Estate Partners, L.L.C.")
            == "blackstone real estate partners"
        )
        assert (
            TemporalPropGraph.normalize_entity_name("Pacific Crest Capital Corp.")
            == "pacific crest capital"
        )
        assert (
            TemporalPropGraph.normalize_entity_name("Vanguard Asset Management INC")
            == "vanguard asset management"
        )
        assert (
            TemporalPropGraph.normalize_entity_name("Starwood Property Trust, REIT")
            == "starwood property"
        )

    def test_chain_of_title_valid(self, sample_parcel: PropertyParcel) -> None:
        """Verify unbroken chain of title identification."""
        graph = TemporalPropGraph()
        graph.add_property(sample_parcel)

        # Deed 1: Alpha -> Beta
        deed1 = DeedRecord(
            deed_id="D-01",
            parcel_id=sample_parcel.apn,
            grantor="Alpha Investments LLC",
            grantee="Beta Commercial Partners",
            transfer_date=date(2018, 5, 10),
            sale_price=10_000_000.0,
            document_type=DocumentType.WARRANTY_DEED.value,
        )
        # Deed 2: Beta -> Gamma
        deed2 = DeedRecord(
            deed_id="D-02",
            parcel_id=sample_parcel.apn,
            grantor="Beta Commercial Partners LLC",
            grantee="Gamma Real Estate Trust",
            transfer_date=date(2022, 11, 20),
            sale_price=14_500_000.0,
            document_type=DocumentType.SPECIAL_WARRANTY_DEED.value,
        )
        graph.add_deed(deed1)
        graph.add_deed(deed2)

        result = graph.verify_chain_of_title(sample_parcel.apn)
        assert result["is_valid"] is True
        assert result["deed_count"] == 2
        assert result["current_owner"] == "Gamma Real Estate Trust"
        assert len(result["breaks"]) == 0
        assert result["has_quitclaim"] is False

    def test_chain_of_title_break_detected(self, sample_parcel: PropertyParcel) -> None:
        """Verify detection of gap/break in title sequence."""
        graph = TemporalPropGraph()
        graph.add_property(sample_parcel)

        # Deed 1: Alpha -> Beta
        deed1 = DeedRecord(
            deed_id="D-01",
            parcel_id=sample_parcel.apn,
            grantor="Alpha Holdings",
            grantee="Beta Partners LLC",
            transfer_date=date(2019, 1, 15),
            sale_price=5_000_000.0,
        )
        # Deed 2: Unknown Stranger -> Delta (break: Beta was grantee, but Stranger is grantor)
        deed2 = DeedRecord(
            deed_id="D-02",
            parcel_id=sample_parcel.apn,
            grantor="Unknown Stranger Corp",
            grantee="Delta Capital",
            transfer_date=date(2023, 6, 1),
            sale_price=7_500_000.0,
        )
        graph.add_deed(deed1)
        graph.add_deed(deed2)

        result = graph.verify_chain_of_title(sample_parcel.apn)
        assert result["is_valid"] is False
        assert len(result["breaks"]) == 1
        assert result["breaks"][0]["previous_grantee"] == "Beta Partners LLC"
        assert result["breaks"][0]["current_grantor"] == "Unknown Stranger Corp"

    def test_chain_of_title_quitclaim_warning(self, sample_parcel: PropertyParcel) -> None:
        """Verify warning flag when quitclaim deed is present."""
        graph = TemporalPropGraph()
        graph.add_property(sample_parcel)

        deed = DeedRecord(
            deed_id="D-QC-01",
            parcel_id=sample_parcel.apn,
            grantor="Founder One LLC",
            grantee="Founder Holdings LLC",
            transfer_date=date(2021, 4, 1),
            sale_price=0.0,
            document_type=DocumentType.QUITCLAIM_DEED.value,
        )
        graph.add_deed(deed)

        result = graph.verify_chain_of_title(sample_parcel.apn)
        assert result["has_quitclaim"] is True
        assert len(result["warnings"]) == 1
        assert "Quitclaim Deed" in result["warnings"][0]

    def test_get_ownership_at_date(self, sample_parcel: PropertyParcel) -> None:
        """Verify historical temporal ownership resolution."""
        graph = TemporalPropGraph()
        graph.add_property(sample_parcel)

        deed1 = DeedRecord(
            deed_id="D-2015",
            parcel_id=sample_parcel.apn,
            grantor="First Seller",
            grantee="Owner 2015 LLC",
            transfer_date=date(2015, 6, 1),
            sale_price=4_000_000.0,
        )
        deed2 = DeedRecord(
            deed_id="D-2020",
            parcel_id=sample_parcel.apn,
            grantor="Owner 2015 LLC",
            grantee="Owner 2020 LLC",
            transfer_date=date(2020, 6, 1),
            sale_price=6_000_000.0,
        )
        graph.add_deed(deed1)
        graph.add_deed(deed2)

        # Before any deed
        assert graph.get_ownership_at_date(sample_parcel.apn, date(2014, 1, 1)) is None

        # In 2018 (between deed1 and deed2)
        owner_2018 = graph.get_ownership_at_date(sample_parcel.apn, date(2018, 1, 1))
        assert owner_2018 is not None
        assert owner_2018["owner_name"] == "Owner 2015 LLC"

        # In 2024 (after deed2)
        owner_2024 = graph.get_ownership_at_date(sample_parcel.apn, date(2024, 1, 1))
        assert owner_2024 is not None
        assert owner_2024["owner_name"] == "Owner 2020 LLC"

    def test_entity_portfolio_and_encumbrances(
        self,
        sample_parcel: PropertyParcel,
        sample_deed: DeedRecord,
        sample_sec_filing: SECFilingRecord,
    ) -> None:
        """Verify entity portfolio lookup and financing encumbrance tracking."""
        graph = TemporalPropGraph()
        graph.add_property(sample_parcel)
        graph.add_deed(sample_deed)
        graph.add_sec_filing(sample_sec_filing)

        # Entity portfolio for Pacific Crest
        portfolio = graph.get_entity_portfolio("Pacific Crest Real Estate Trust LLC")
        assert len(portfolio) >= 1
        assert any(item["parcel_id"] == sample_parcel.apn for item in portfolio)

        # Add mortgage financing
        lender_id = graph.add_financing(
            lender_name="JPMorgan Chase Commercial",
            parcel_id=sample_parcel.apn,
            loan_amount=12_000_000.0,
            recording_date=date(2024, 3, 20),
            maturity_date=date(2034, 3, 20),
            loan_type="Senior Mortgage",
        )
        assert "jpmorgan_chase" in lender_id

        encumbrances = graph.get_property_encumbrances(sample_parcel.apn)
        assert len(encumbrances) == 1
        assert encumbrances[0]["loan_amount"] == 12_000_000.0
        assert encumbrances[0]["loan_type"] == "Senior Mortgage"


class TestDCFValuationCore:
    """Core logic and algorithmic tests for DCF Valuation Engine."""

    def test_calculate_irr_convergence_and_edge_cases(self) -> None:
        """Verify numerical stability of IRR across normal and edge cases."""
        # Non-trivial standard cash flows
        cfs = [-1000.0, 300.0, 350.0, 400.0, 500.0]
        irr = calculate_irr(cfs)
        assert 0.15 < irr < 0.25

        # All positive cash flows -> no solution
        assert calculate_irr([100.0, 200.0, 300.0]) == 0.0

        # All negative cash flows -> no solution
        assert calculate_irr([-100.0, -200.0]) == 0.0

        # Empty cash flows
        assert calculate_irr([]) == 0.0

    def test_sensitivity_table(self) -> None:
        """Verify 2D sensitivity table output and monotonicity."""
        engine = DCFValuationEngine()
        table = engine.calculate_sensitivity_table(
            property_id="PROP-SENS-1",
            initial_gross_revenue=1_200_000.0,
            initial_operating_expenses=400_000.0,
            purchase_price=9_000_000.0,
            discount_rates=[0.07, 0.09],
            exit_cap_rates=[0.055, 0.075],
        )

        assert table["property_id"] == "PROP-SENS-1"
        assert "7.0%" in table["npv_matrix"]
        assert "9.0%" in table["npv_matrix"]
        assert "5.5%" in table["npv_matrix"]["7.0%"]

        # Lower discount rate and lower cap rate yield highest NPV
        npv_low_disc_low_cap = table["npv_matrix"]["7.0%"]["5.5%"]
        npv_high_disc_high_cap = table["npv_matrix"]["9.0%"]["7.5%"]
        assert npv_low_disc_low_cap > npv_high_disc_high_cap

    def test_debt_metrics_and_covenants(self) -> None:
        """Verify loan underwriting metrics (LTV, DSCR, Debt Yield)."""
        engine = DCFValuationEngine()
        metrics = engine.calculate_debt_metrics(
            purchase_price=10_000_000.0,
            net_operating_income_y1=800_000.0,
            loan_amount=6_500_000.0,
            annual_debt_service=500_000.0,
        )

        assert metrics["loan_to_value"] == 0.65
        assert metrics["debt_service_coverage_ratio"] == 1.60
        assert metrics["debt_yield"] == 0.1231
        assert metrics["is_covenant_compliant"] is True

        # Non-compliant debt scenario
        bad_metrics = engine.calculate_debt_metrics(
            purchase_price=10_000_000.0,
            net_operating_income_y1=500_000.0,
            loan_amount=8_500_000.0,
            annual_debt_service=450_000.0,
        )
        assert bad_metrics["loan_to_value"] == 0.85
        assert bad_metrics["debt_service_coverage_ratio"] == 1.11
        assert bad_metrics["is_covenant_compliant"] is False

    def test_equity_multiple_and_breakeven_occupancy(self) -> None:
        """Verify equity multiple and breakeven occupancy percentage calculations."""
        engine = DCFValuationEngine()
        cfs = [
            CashFlowYear(
                year=1,
                gross_revenue=1000.0,
                operating_expenses=400.0,
                net_operating_income=600.0,
                debt_service=200.0,
                net_cash_flow=400.0,
            ),
            CashFlowYear(
                year=2,
                gross_revenue=1050.0,
                operating_expenses=410.0,
                net_operating_income=640.0,
                debt_service=200.0,
                net_cash_flow=440.0,
            ),
        ]
        # Purchase $5,000, Loan $3,000 -> Equity $2,000
        # Distributions = 400 + 440 + Terminal Proceeds ($4,000 - $2,500 balance = $1,500) = $2,340
        # Multiple = 2,340 / 2,000 = 1.17
        mult = engine.calculate_equity_multiple(
            purchase_price=5000.0,
            loan_amount=3000.0,
            cash_flows=cfs,
            terminal_value=4000.0,
            remaining_loan_balance=2500.0,
        )
        assert mult == 1.17

        # Breakeven occupancy = (OpEx 400,000 + Debt 300,000) / Gross Rev 1,000,000 = 70%
        be = engine.calculate_breakeven_occupancy(
            gross_revenue=1_000_000.0,
            operating_expenses=400_000.0,
            annual_debt_service=300_000.0,
        )
        assert be == 0.70


class TestGeospatialRiskCore:
    """Core logic and algorithmic tests for GeospatialRiskEngine."""

    def test_evaluate_zoning_capacity_compliant(self, sample_parcel: PropertyParcel) -> None:
        """Verify zoning FAR and height validation for compliant commercial property."""
        engine = GeospatialRiskEngine()
        # Parcel zoning C-3-O, max FAR 9.0, max height 250.0
        result = engine.evaluate_zoning_capacity(
            parcel=sample_parcel,
            proposed_gross_floor_area=180_000.0,
            proposed_height=180.0,
            lot_area_sqft=30_000.0,
        )
        assert result["max_permissible_far"] == 9.0
        assert result["proposed_far"] == 6.0
        assert result["far_compliant"] is True
        assert result["height_compliant"] is True
        assert result["variance_required"] is False
        assert result["entitlement_risk"] == "low"

    def test_evaluate_zoning_capacity_variance_required(self) -> None:
        """Verify detection of zoning violation requiring special variance."""
        residential_parcel = PropertyParcel(
            apn="APN-RES-99",
            address="123 Oak Lane",
            city="Oakland",
            state="CA",
            zip_code="94601",
            property_type=PropertyType.MULTIFAMILY,
            square_feet=15000.0,
            year_built=1995,
            zoning_code="R-1",
        )
        engine = GeospatialRiskEngine()
        # R-1 zoning: max FAR 0.6, max height 35 ft
        result = engine.evaluate_zoning_capacity(
            parcel=residential_parcel,
            proposed_gross_floor_area=20_000.0,
            proposed_height=50.0,
            lot_area_sqft=10_000.0,
        )
        assert result["proposed_far"] == 2.0
        assert result["far_compliant"] is False
        assert result["height_compliant"] is False
        assert result["variance_required"] is True
        assert result["entitlement_risk"] == "high"

    def test_environmental_proximity_decay(self, sample_parcel: PropertyParcel) -> None:
        """Verify distance decay environmental risk scoring."""
        engine = GeospatialRiskEngine()
        assert engine.calculate_environmental_proximity_score([0.1]) == 95.0
        assert engine.calculate_environmental_proximity_score([0.4]) == 75.0
        assert engine.calculate_environmental_proximity_score([0.8]) == 45.0
        assert engine.calculate_environmental_proximity_score([1.5]) == 20.0
        assert engine.calculate_environmental_proximity_score([5.0]) == 5.0
        assert engine.calculate_environmental_proximity_score([]) == 0.0

        metrics = engine.assess_parcel_risk(
            parcel=sample_parcel,
            distances_to_superfund_miles=[0.35],
        )
        assert metrics.environmental_contamination_risk == 75.0

    def test_climate_risk_projections(self, sample_parcel: PropertyParcel) -> None:
        """Verify 10-30 year climate risk modeling and insurance multiplier."""
        engine = GeospatialRiskEngine()
        clim = engine.project_climate_risk(sample_parcel, horizon_years=30)
        assert "year_10" in clim["projected_scores"]
        assert "year_20" in clim["projected_scores"]
        assert "year_30" in clim["projected_scores"]
        assert clim["estimated_insurance_premium_multiplier"] > 1.0
