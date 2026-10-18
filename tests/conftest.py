"""Pytest fixtures for PropGraph MCP tests."""

from __future__ import annotations

from datetime import date

import pytest
from click.testing import CliRunner

from propgraph_mcp.types import (
    DeedRecord,
    PropertyParcel,
    PropertyType,
    SECFilingRecord,
)


@pytest.fixture
def cli_runner() -> CliRunner:
    """Fixture providing Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def sample_parcel() -> PropertyParcel:
    """Fixture providing a commercial office parcel record."""
    return PropertyParcel(
        apn="APN-884-219-00",
        address="742 Market Street",
        city="San Francisco",
        state="CA",
        zip_code="94103",
        property_type=PropertyType.OFFICE,
        square_feet=45000.0,
        year_built=2012,
        zoning_code="C-3-O",
        latitude=37.7885,
        longitude=-122.4042,
    )


@pytest.fixture
def sample_deed() -> DeedRecord:
    """Fixture providing a municipal deed transfer record."""
    return DeedRecord(
        deed_id="DEED-2024-SF-9912",
        parcel_id="APN-884-219-00",
        grantor="SOMA Holdings LLC",
        grantee="Pacific Crest Real Estate Trust",
        transfer_date=date(2024, 3, 15),
        sale_price=18500000.0,
        document_type="Grant Deed",
        recording_number="2024-009912",
    )


@pytest.fixture
def sample_sec_filing() -> SECFilingRecord:
    """Fixture providing an SEC EDGAR filing mentioning the property."""
    return SECFilingRecord(
        accession_number="0001193125-24-067890",
        cik="0001552345",
        company_name="Pacific Crest Real Estate Trust",
        filing_type="10-K",
        filing_date=date(2024, 4, 1),
        properties_mentioned=["APN-884-219-00"],
        lease_obligations={"Year1": 1500000.0, "Year2": 1550000.0},
    )
