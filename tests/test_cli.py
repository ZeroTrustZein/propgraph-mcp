"""Comprehensive test suite for PropGraph MCP CLI."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from propgraph_mcp import cli


@pytest.fixture
def sample_deeds_json(tmp_path: Path) -> Path:
    """Create a temporary JSON file with sample deed records."""
    deeds = [
        {
            "deed_id": "DEED-001",
            "parcel_id": "APN-100",
            "grantor": "Apex Holdings LLC",
            "grantee": "Beacon Commercial Trust",
            "sale_date": "2020-05-15",
            "sale_price_raw": 5_000_000.0,
            "deed_type": "Warranty Deed",
        },
        {
            "deed_id": "DEED-002",
            "parcel_id": "APN-100",
            "grantor": "Beacon Commercial Trust",
            "grantee": "Citadel Realty Fund",
            "sale_date": "2023-08-20",
            "sale_price_raw": 7_200_000.0,
            "deed_type": "Warranty Deed",
        },
    ]
    file_path = tmp_path / "deeds.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(deeds, f)
    return file_path


@pytest.fixture
def sample_deeds_csv(tmp_path: Path) -> Path:
    """Create a temporary CSV file with sample deed records."""
    file_path = tmp_path / "deeds.csv"
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "deed_id",
                "parcel_id",
                "grantor",
                "grantee",
                "sale_date",
                "sale_price_raw",
                "deed_type",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "deed_id": "DEED-CSV-01",
                "parcel_id": "APN-CSV-1",
                "grantor": "Seller A",
                "grantee": "Buyer B",
                "sale_date": "2021-01-10",
                "sale_price_raw": "2500000.0",
                "deed_type": "Special Warranty Deed",
            }
        )
    return file_path


@pytest.fixture
def sample_encumbrances_json(tmp_path: Path) -> Path:
    """Create a temporary JSON file with sample encumbrances."""
    encs = [
        {
            "encumbrance_id": "MORT-1",
            "parcel_id": "APN-100",
            "instrument": "first_mortgage",
            "amount": 4_000_000.0,
            "lender": "JPMorgan Chase Bank",
            "recording_date": "2020-05-15",
            "seniority_rank": 1,
        },
        {
            "encumbrance_id": "MEZZ-1",
            "parcel_id": "APN-100",
            "instrument": "mezzanine_debt",
            "amount": 1_000_000.0,
            "lender": "Starwood Property Trust",
            "recording_date": "2021-06-01",
            "seniority_rank": 2,
        },
    ]
    file_path = tmp_path / "encumbrances.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(encs, f)
    return file_path


@pytest.fixture
def sample_parcels_json(tmp_path: Path) -> Path:
    """Create a temporary JSON file with neighboring parcels for assemblage."""
    parcels = [
        {
            "apn": "APN-101",
            "address": "101 Grand Ave",
            "property_type": "office",
            "square_feet": 25_000.0,
            "latitude": 34.0522,
            "longitude": -118.2437,
            "owner": "entity:apex_capital",
        },
        {
            "apn": "APN-102",
            "address": "105 Grand Ave",
            "property_type": "office",
            "square_feet": 30_000.0,
            "latitude": 34.0525,
            "longitude": -118.2439,
            "owner": "entity:apex_capital",
        },
    ]
    file_path = tmp_path / "parcels.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(parcels, f)
    return file_path


def test_cli_info_command(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli.cli, ["info"])
    assert result.exit_code == 0
    assert "PropGraph MCP" in result.output
    assert "Temporal Graph-RAG" in result.output
    assert "Multi-Scenario DCF" in result.output


def test_cli_serve_help(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli.cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--transport" in result.output
    assert "--host" in result.output
    assert "--port" in result.output


def test_cli_underwrite_table(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "underwrite",
            "--apn",
            "APN-999",
            "--price",
            "8000000",
            "--revenue",
            "1000000",
            "--expenses",
            "350000",
        ],
    )
    assert result.exit_code == 0
    assert "CRE DCF Underwriting Results: APN-999" in result.output
    assert "Base" in result.output
    assert "Bull" in result.output
    assert "Bear" in result.output


def test_cli_underwrite_json(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "underwrite",
            "--apn",
            "APN-999",
            "--price",
            "8000000",
            "--revenue",
            "1000000",
            "--expenses",
            "350000",
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "Base" in data
    assert "Bull" in data
    assert "Bear" in data
    assert data["Base"]["property_id"] == "APN-999"
    assert data["Base"]["purchase_price"] == 8_000_000.0


def test_cli_validate_deeds_json(cli_runner: CliRunner, sample_deeds_json: Path) -> None:
    result = cli_runner.invoke(cli.cli, ["validate-deeds", "-f", str(sample_deeds_json)])
    assert result.exit_code == 0
    assert "Deed Stream Validation Summary" in result.output
    assert "Total Processed" in result.output
    assert "Clean Records" in result.output


def test_cli_validate_deeds_csv(cli_runner: CliRunner, sample_deeds_csv: Path) -> None:
    result = cli_runner.invoke(
        cli.cli, ["validate-deeds", "-f", str(sample_deeds_csv), "--json-output"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_records"] == 1
    assert data["clean_records"] == 1


def test_cli_validate_deeds_quarantine(cli_runner: CliRunner, tmp_path: Path) -> None:
    invalid_deeds = [
        {
            "raw_id": "RAW-BAD-1",
            "parcel_id": "APN-X",
            "grantor": "",  # missing grantor
            "grantee": "Acme",
            "sale_date": "2024-01-01",
            "sale_price_raw": -50.0,
        }
    ]
    in_file = tmp_path / "bad_deeds.json"
    with open(in_file, "w", encoding="utf-8") as f:
        json.dump(invalid_deeds, f)

    quar_file = tmp_path / "quarantined.json"
    result = cli_runner.invoke(
        cli.cli,
        [
            "validate-deeds",
            "-f",
            str(in_file),
            "--quarantine-out",
            str(quar_file),
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["quarantined_records"] == 1
    assert quar_file.exists()


def test_cli_chain_of_title(cli_runner: CliRunner, sample_deeds_json: Path) -> None:
    result = cli_runner.invoke(
        cli.cli,
        ["chain-of-title", "--apn", "APN-100", "-f", str(sample_deeds_json)],
    )
    assert result.exit_code == 0
    assert "Chain of Title Audit: APN-100" in result.output
    assert "Apex Holdings LLC" in result.output
    assert "Beacon Commercial Trust" in result.output


def test_cli_chain_of_title_json(cli_runner: CliRunner, sample_deeds_json: Path) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "chain-of-title",
            "--apn",
            "APN-100",
            "-f",
            str(sample_deeds_json),
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "timeline" in data
    assert "audit" in data
    assert len(data["timeline"]) == 2
    assert data["audit"]["is_valid"] is True


def test_cli_risk_assess_table(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "risk-assess",
            "--apn",
            "APN-RISK-1",
            "--property-type",
            "office",
            "--flood-zone",
            "AE",
            "--seismic-zone",
            "4",
            "--brownfield",
        ],
    )
    assert result.exit_code == 0
    assert "Geospatial Risk Assessment: APN-RISK-1" in result.output
    assert "Flood Hazard" in result.output
    assert "Seismic Exposure" in result.output
    assert "Overall Risk Tier" in result.output


def test_cli_risk_assess_json(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "risk-assess",
            "--apn",
            "APN-RISK-2",
            "--property-type",
            "industrial",
            "--flood-zone",
            "X",
            "--seismic-zone",
            "1",
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["parcel_id"] == "APN-RISK-2"
    assert data["seismic_risk_score"] == 10.0
    assert data["flood_hazard_score"] == 10.0


def test_cli_encumbrance(cli_runner: CliRunner, sample_encumbrances_json: Path) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "encumbrance",
            "--apn",
            "APN-100",
            "-f",
            str(sample_encumbrances_json),
            "-v",
            "8000000",
        ],
    )
    assert result.exit_code == 0
    assert "Lien Priority Waterfall: APN-100" in result.output
    assert "Total Debt" in result.output


def test_cli_encumbrance_json(cli_runner: CliRunner, sample_encumbrances_json: Path) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "encumbrance",
            "--apn",
            "APN-100",
            "-f",
            str(sample_encumbrances_json),
            "-v",
            "10000000",
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    waterfall = json.loads(result.output)
    assert waterfall["total_debt"] == 5_000_000.0
    assert waterfall["overall_ltv"] == 0.5


def test_cli_assemblage(cli_runner: CliRunner, sample_parcels_json: Path) -> None:
    result = cli_runner.invoke(
        cli.cli,
        ["assemblage", "-f", str(sample_parcels_json), "-d", "500"],
    )
    assert result.exit_code == 0
    assert "Contiguous Parcel Assemblages" in result.output
    assert "APN-101" in result.output
    assert "APN-102" in result.output


def test_cli_assemblage_json(cli_runner: CliRunner, sample_parcels_json: Path) -> None:
    result = cli_runner.invoke(
        cli.cli,
        ["assemblage", "-f", str(sample_parcels_json), "-d", "500", "--json-output"],
    )
    assert result.exit_code == 0
    clusters = json.loads(result.output)
    assert len(clusters) == 1
    assert clusters[0]["parcel_count"] == 2
    assert "APN-101" in clusters[0]["parcels"]
    assert "APN-102" in clusters[0]["parcels"]


def test_cli_entity_resolve(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "entity-resolve",
            "--names",
            "Blackstone Real Estate Group LLC, Blackstone Real Estate Group Inc, Unrelated Fund",
            "-t",
            "0.7",
        ],
    )
    assert result.exit_code == 0
    assert "Entity Alias Resolution" in result.output
    assert "Blackstone" in result.output


def test_cli_entity_resolve_json(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli.cli,
        [
            "entity-resolve",
            "--names",
            "Apollo Commercial Real Estate, Apollo Commercial Real Estate Trust",
            "-t",
            "0.6",
            "--json-output",
        ],
    )
    assert result.exit_code == 0
    matches = json.loads(result.output)
    assert len(matches) >= 1
    assert matches[0]["similarity_score"] >= 0.6


def test_cli_export_graph_json(cli_runner: CliRunner, sample_deeds_json: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "export.json"
    result = cli_runner.invoke(
        cli.cli,
        ["export-graph", "-f", str(sample_deeds_json), "--format", "json", "-o", str(out_file)],
    )
    assert result.exit_code == 0
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "node_count" in data
    assert "edge_count" in data
    assert data["node_count"] > 0


def test_cli_export_graph_geojson(
    cli_runner: CliRunner, sample_deeds_json: Path, tmp_path: Path
) -> None:
    out_file = tmp_path / "export.geojson"
    result = cli_runner.invoke(
        cli.cli,
        ["export-graph", "-f", str(sample_deeds_json), "--format", "geojson", "-o", str(out_file)],
    )
    assert result.exit_code == 0
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["type"] == "FeatureCollection"


def test_cli_file_not_found_error(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli.cli, ["validate-deeds", "-f", "non_existent_file.json"])
    assert result.exit_code != 0
    assert "File not found" in result.output


def test_cli_unsupported_format_error(cli_runner: CliRunner, tmp_path: Path) -> None:
    bad_file = tmp_path / "test.txt"
    bad_file.write_text("hello world")
    result = cli_runner.invoke(cli.cli, ["validate-deeds", "-f", str(bad_file)])
    assert result.exit_code != 0
    assert "Unsupported file format" in result.output
