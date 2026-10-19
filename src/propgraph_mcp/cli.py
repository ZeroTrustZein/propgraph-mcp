"""Command line interface for PropGraph MCP."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.table import Table

from propgraph_mcp import __version__
from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.risk import GeospatialRiskEngine
from propgraph_mcp.server import create_mcp_server
from propgraph_mcp.subsystems.encumbrance import EncumbranceAnalyzer
from propgraph_mcp.subsystems.entity_resolution import (
    composite_entity_similarity,
)
from propgraph_mcp.subsystems.spatial import SpatialContiguityEngine
from propgraph_mcp.subsystems.stream_validator import DeedStreamValidator
from propgraph_mcp.types import (
    PropertyParcel,
    PropertyType,
)
from propgraph_mcp.valuation import DCFValuationEngine

console = Console()


def _load_records_from_file(file_path: str) -> List[Dict[str, Any]]:
    """Helper to parse JSON or CSV records into list of dictionaries."""
    path = Path(file_path)
    if not path.exists():
        raise click.ClickException(f"File not found: {file_path}")

    suffix = path.suffix.lower()
    raw_list: List[Dict[str, Any]] = []
    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                raw_list = data
            elif isinstance(data, dict):
                for key in ("records", "deeds", "parcels", "data"):
                    if key in data and isinstance(data[key], list):
                        raw_list = data[key]
                        break
                else:
                    raw_list = [data]
    elif suffix in (".csv", ".tsv"):
        delimiter = "\t" if suffix == ".tsv" else ","
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            raw_list = list(reader)
    else:
        raise click.ClickException(f"Unsupported file format '{suffix}'. Use .json, .csv, or .tsv.")

    # Normalize common field aliases across deed/parcel streams
    normalized: List[Dict[str, Any]] = []
    for item in raw_list:
        rec = dict(item)
        if "sale_date" not in rec and "transfer_date" in rec:
            rec["sale_date"] = rec["transfer_date"]
        if "sale_price_raw" not in rec and "sale_price" in rec:
            rec["sale_price_raw"] = rec["sale_price"]
        if "deed_type" not in rec and "document_type" in rec:
            rec["deed_type"] = rec["document_type"]
        normalized.append(rec)
    return normalized


@click.group()
@click.version_option(__version__, prog_name="propgraph")
def cli() -> None:
    """PropGraph MCP: Autonomous CRE underwriting swarm CLI."""


@cli.command()
def info() -> None:
    """Display PropGraph MCP package metadata and system capabilities."""
    console.print(f"[bold cyan]PropGraph MCP[/bold cyan] [green]v{__version__}[/green]")
    console.print(
        "Autonomous CRE underwriting swarm using temporal Graph-RAG over municipal deed streams and SEC filings."
    )

    table = Table(title="Core Subsystems & MCP Capabilities")
    table.add_column("Subsystem", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Status", style="green")

    table.add_row(
        "Temporal Graph-RAG",
        "NetworkX MultiDiGraph chain-of-title & SEC disclosure traversal",
        "Ready",
    )
    table.add_row(
        "Multi-Scenario DCF",
        "Base / Bull / Bear cash flow simulations with IRR & NPV",
        "Ready",
    )
    table.add_row(
        "Geospatial Risk",
        "Flood, seismic, zoning compliance, environmental risk scoring",
        "Ready",
    )
    table.add_row("MCP Server", "Model Context Protocol v2 tools & resources endpoint", "Ready")
    console.print(table)


@cli.command()
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    help="MCP transport protocol.",
)
@click.option("--host", default="127.0.0.1", help="Host address for network transport.")
@click.option("--port", default=8000, type=int, help="Port for network transport.")
def serve(transport: str, host: str, port: int) -> None:
    """Launch the PropGraph MCP Server."""
    console.print(
        f"[bold green]Starting PropGraph MCP Server[/bold green] (transport: {transport}, host: {host}, port: {port})..."
    )
    server = create_mcp_server()
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=transport, host=host, port=port)


@cli.command()
@click.option("--apn", default="APN-098-442-01", help="Assessor parcel number.")
@click.option("--price", default=10_000_000.0, type=float, help="Property purchase price.")
@click.option("--revenue", default=1_200_000.0, type=float, help="Initial gross revenue.")
@click.option("--expenses", default=400_000.0, type=float, help="Initial operating expenses.")
@click.option("--years", default=5, type=int, help="Holding period in years.")
@click.option("--discount-rate", default=0.08, type=float, help="Discount rate (e.g. 0.08).")
@click.option("--exit-cap", default=0.065, type=float, help="Exit cap rate (e.g. 0.065).")
@click.option("--json-output", is_flag=True, help="Output results in JSON format.")
def underwrite(
    apn: str,
    price: float,
    revenue: float,
    expenses: float,
    years: int,
    discount_rate: float,
    exit_cap: float,
    json_output: bool,
) -> None:
    """Execute multi-scenario DCF underwriting for a property."""
    engine = DCFValuationEngine()
    results = engine.run_all_scenarios(
        property_id=apn,
        initial_gross_revenue=revenue,
        initial_operating_expenses=expenses,
        purchase_price=price,
    )

    if json_output:
        dump = {k: v.model_dump() for k, v in results.items()}
        click.echo(json.dumps(dump, indent=2, default=str))
        return

    table = Table(title=f"CRE DCF Underwriting Results: {apn}")
    table.add_column("Scenario", style="cyan")
    table.add_column("Purchase Price", style="white")
    table.add_column("NPV ($)", style="green")
    table.add_column("IRR (%)", style="yellow")
    table.add_column("Exit Value ($)", style="magenta")

    for name, res in results.items():
        table.add_row(
            name,
            f"${res.purchase_price:,.0f}",
            f"${res.npv:,.2f}",
            f"{res.irr * 100:.2f}%",
            f"${res.terminal_value:,.2f}",
        )
    console.print(table)


@cli.command("validate-deeds")
@click.option("--file", "-f", "file_path", required=True, help="Path to deeds JSON or CSV file.")
@click.option(
    "--quarantine-out", default=None, help="Optional output path to write quarantined records."
)
@click.option("--json-output", is_flag=True, help="Output summary in JSON format.")
def validate_deeds(file_path: str, quarantine_out: Optional[str], json_output: bool) -> None:
    """Validate municipal deed stream and quarantine anomalous records."""
    records = _load_records_from_file(file_path)
    validator = DeedStreamValidator()
    clean_list, quar_list, summary = validator.validate_batch(records)

    if quarantine_out and quar_list:
        with open(quarantine_out, "w", encoding="utf-8") as f:
            json.dump([q.model_dump() for q in quar_list], f, indent=2, default=str)

    if json_output:
        click.echo(json.dumps(summary.model_dump(), indent=2, default=str))
        return

    table = Table(title="Deed Stream Validation Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Processed", str(summary.total_records))
    table.add_row("Clean Records", str(summary.clean_records))
    table.add_row("Quarantined Records", str(summary.quarantined_records))
    table.add_row("Total Dollar Volume", f"${summary.total_dollar_volume:,.0f}")
    table.add_row("Arms-Length Count", str(summary.arms_length_count))
    console.print(table)


@cli.command("chain-of-title")
@click.option("--apn", required=True, help="Assessor parcel number.")
@click.option(
    "--file", "-f", "file_path", default=None, help="Optional deeds file to ingest before query."
)
@click.option("--json-output", is_flag=True, help="Output chain-of-title in JSON format.")
def chain_of_title(apn: str, file_path: Optional[str], json_output: bool) -> None:
    """Audit property chain-of-title for breaks and quitclaim deeds."""
    graph = TemporalPropGraph()
    if file_path:
        records = _load_records_from_file(file_path)
        validator = DeedStreamValidator()
        clean_list, _, _ = validator.validate_batch(records)
        validator.ingest_batch_to_graph(graph, clean_list)

    audit = graph.verify_chain_of_title(apn)
    timeline = graph.get_ownership_timeline(apn)
    deeds = graph.get_deeds_for_parcel(apn)

    if json_output:
        res = {"audit": audit, "timeline": timeline, "deeds": deeds}
        click.echo(json.dumps(res, indent=2, default=str))
        return

    table = Table(title=f"Chain of Title Audit: {apn}")
    table.add_column("Date", style="cyan")
    table.add_column("Grantor", style="white", no_wrap=True)
    table.add_column("Grantee", style="white", no_wrap=True)
    table.add_column("Document", style="yellow")
    table.add_column("Price ($)", style="green")

    display_records = deeds if deeds else timeline
    for rec in display_records:
        t_date = rec.get("transfer_date") or rec.get("effective_date") or ""
        grantor = rec.get("grantor") or ""
        grantee = rec.get("grantee") or rec.get("owner_name") or ""
        doc = rec.get("document_type") or "Deed"
        price = rec.get("sale_price") or 0.0
        table.add_row(
            str(t_date),
            str(grantor),
            str(grantee),
            str(doc),
            f"${float(price):,.0f}",
        )
    console.print(table)
    is_valid_str = (
        "[green]Valid unbroken chain[/green]"
        if audit.get("is_valid")
        else "[red]Break detected[/red]"
    )
    console.print(f"Chain Status: {is_valid_str} | Deeds: {audit.get('deed_count', 0)}")
    for warn in audit.get("warnings", []):
        console.print(f"[yellow]Warning: {warn}[/yellow]")


@cli.command("risk-assess")
@click.option("--apn", default="APN-001", help="Assessor parcel number.")
@click.option("--address", default="100 Main St", help="Property street address.")
@click.option("--city", default="Los Angeles", help="City.")
@click.option("--state", default="CA", help="State code.")
@click.option("--zip-code", default="90012", help="ZIP code.")
@click.option(
    "--property-type",
    default="office",
    type=click.Choice(
        ["office", "retail", "industrial", "multifamily", "hospitality", "flex", "land"]
    ),
    help="Commercial property type.",
)
@click.option("--sqft", default=50_000.0, type=float, help="Gross square feet.")
@click.option("--year-built", default=1995, type=int, help="Year built.")
@click.option("--flood-zone", default="AE", help="FEMA Flood Zone code.")
@click.option("--seismic-zone", default=4, type=int, help="UBC Seismic Zone (0-4).")
@click.option(
    "--brownfield", is_flag=True, help="Flag parcel proximity to known brownfield / Superfund site."
)
@click.option("--json-output", is_flag=True, help="Output risk assessment in JSON format.")
def risk_assess(
    apn: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    property_type: str,
    sqft: float,
    year_built: int,
    flood_zone: str,
    seismic_zone: int,
    brownfield: bool,
    json_output: bool,
) -> None:
    """Assess geospatial, climate, seismic, and zoning risk metrics."""
    parcel = PropertyParcel(
        apn=apn,
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        property_type=PropertyType(property_type),
        square_feet=sqft,
        year_built=year_built,
    )
    risk_engine = GeospatialRiskEngine()
    metrics = risk_engine.assess_parcel_risk(
        parcel=parcel,
        flood_zone=flood_zone,
        seismic_zone=seismic_zone,
        has_brownfield_proximity=brownfield,
    )

    if json_output:
        click.echo(json.dumps(metrics.model_dump(), indent=2, default=str))
        return

    table = Table(title=f"Geospatial Risk Assessment: {apn}")
    table.add_column("Risk Category", style="cyan")
    table.add_column("Score (0-100)", style="yellow")

    table.add_row("Flood Hazard", f"{metrics.flood_hazard_score:.1f}")
    table.add_row("Seismic Exposure", f"{metrics.seismic_risk_score:.1f}")
    table.add_row("Environmental Contamination", f"{metrics.environmental_contamination_risk:.1f}")
    table.add_row("Zoning Compliance Score", f"{metrics.zoning_compliance_score:.1f}")
    table.add_row(
        "[bold]Composite Risk Score[/bold]",
        f"[bold]{metrics.composite_risk_score:.1f}[/bold]",
    )
    table.add_row("Overall Risk Tier", f"[bold green]{metrics.risk_tier.value}[/bold green]")
    console.print(table)


@cli.command("encumbrance")
@click.option("--apn", required=True, help="Assessor parcel number.")
@click.option("--file", "-f", "file_path", default=None, help="Path to encumbrance JSON file.")
@click.option("--valuation", "-v", default=None, type=float, help="Property valuation for LTV.")
@click.option("--json-output", is_flag=True, help="Output waterfall in JSON format.")
def encumbrance(
    apn: str,
    file_path: Optional[str],
    valuation: Optional[float],
    json_output: bool,
) -> None:
    """Analyze parcel lien priority waterfall and cumulative loan-to-value (LTV)."""
    graph = TemporalPropGraph()
    if not graph.graph.has_node(apn):
        parcel = PropertyParcel(
            apn=apn,
            address="Underwritten Asset",
            city="City",
            state="CA",
            zip_code="00000",
            property_type=PropertyType.OFFICE,
            square_feet=50_000.0,
            year_built=2000,
        )
        graph.add_property(parcel)

    if file_path:
        records = _load_records_from_file(file_path)
        from propgraph_mcp.types import EdgeType, GraphEdge

        for rec in records:
            inst = str(rec.get("instrument") or rec.get("encumbrance_type") or "mortgage")
            amt = float(rec.get("amount") or rec.get("principal_amount") or 0.0)
            lender = str(rec.get("lender") or "lender_default")
            lender_id = f"lender:{lender.lower().replace(' ', '_')}"
            graph.add_edge(
                GraphEdge(
                    source_id=lender_id,
                    target_id=apn,
                    edge_type=EdgeType.ENCUMBERS,
                    effective_date=date.fromisoformat(str(rec.get("recording_date", "2020-01-01"))),
                    attributes={"instrument": inst, "amount": amt, "lender": lender},
                )
            )

    analyzer = EncumbranceAnalyzer()
    waterfall_res = analyzer.analyze_parcel_encumbrance_waterfall(
        graph, apn, property_valuation=valuation
    )

    if json_output:
        click.echo(json.dumps(waterfall_res, indent=2, default=str))
        return

    table = Table(title=f"Lien Priority Waterfall: {apn}")
    table.add_column("Rank", style="cyan")
    table.add_column("Instrument", style="white")
    table.add_column("Lender", style="white")
    table.add_column("Amount ($)", style="yellow")
    table.add_column("Cumulative ($)", style="green")
    table.add_column("Recovery (%)", style="magenta")

    for lien in waterfall_res.get("waterfall", []):
        rec_pct = lien.get("recovery_percentage")
        rec_str = f"{rec_pct * 100:.1f}%" if rec_pct is not None else "100.0%"
        table.add_row(
            str(lien.get("seniority_rank", "-")),
            str(lien.get("instrument", "-")),
            str(lien.get("lender") or lien.get("source_id", "-")),
            f"${lien.get('amount', 0.0):,.0f}",
            f"${lien.get('cumulative_debt', 0.0):,.0f}",
            rec_str,
        )
    console.print(table)
    overall_ltv = waterfall_res.get("overall_ltv")
    ltv_disp = f"{overall_ltv * 100:.1f}%" if overall_ltv is not None else "N/A"
    console.print(
        f"Total Debt: [bold yellow]${waterfall_res.get('total_debt', 0.0):,.0f}[/bold yellow] | "
        f"Overall LTV: [bold green]{ltv_disp}[/bold green] | "
        f"Remaining Equity: [bold cyan]${waterfall_res.get('remaining_equity', 0.0):,.0f}[/bold cyan]"
    )


@cli.command("assemblage")
@click.option("--file", "-f", "file_path", required=True, help="Path to parcels JSON file.")
@click.option(
    "--distance",
    "-d",
    default=200.0,
    type=float,
    help="Max distance in meters for adjacency clustering.",
)
@click.option("--json-output", is_flag=True, help="Output clusters in JSON format.")
def assemblage(file_path: str, distance: float, json_output: bool) -> None:
    """Identify contiguous parcel assemblage opportunities."""
    records = _load_records_from_file(file_path)
    graph = TemporalPropGraph()
    from propgraph_mcp.types import EdgeType, GraphEdge

    for rec in records:
        apn = rec["apn"]
        parcel = PropertyParcel(
            apn=apn,
            address=rec.get("address", "Unknown"),
            city=rec.get("city", "City"),
            state=rec.get("state", "CA"),
            zip_code=rec.get("zip_code", "00000"),
            property_type=PropertyType(rec.get("property_type", "office")),
            square_feet=float(rec.get("square_feet", 10_000)),
            year_built=int(rec.get("year_built", 2000)),
            latitude=float(rec.get("latitude", 0.0)),
            longitude=float(rec.get("longitude", 0.0)),
        )
        graph.add_property(parcel)
        owner = rec.get("owner", "entity:common_owner")
        graph.add_edge(GraphEdge(source_id=owner, target_id=apn, edge_type=EdgeType.OWNS))

    spatial_engine = SpatialContiguityEngine()
    clusters = spatial_engine.find_assemblage_clusters(graph, max_distance_meters=distance)

    if json_output:
        click.echo(json.dumps(clusters, indent=2, default=str))
        return

    table = Table(title=f"Contiguous Parcel Assemblages (<= {distance:.0f}m)")
    table.add_column("Owner", style="cyan")
    table.add_column("Parcels", style="white")
    table.add_column("Count", style="yellow")
    table.add_column("Total SqFt", style="green")
    table.add_column("Density Uplift", style="magenta")

    for cluster in clusters:
        table.add_row(
            str(cluster.get("owner_entity")),
            ", ".join(cluster.get("parcels", [])),
            str(cluster.get("parcel_count")),
            f"{cluster.get('combined_square_feet', 0.0):,.0f}",
            f"{cluster.get('estimated_density_uplift', 0.0):,.0f}",
        )
    console.print(table)


@cli.command("entity-resolve")
@click.option(
    "--names",
    default=None,
    help="Comma-separated entity names to test similarity (e.g. 'Acme LLC, Acme Corp').",
)
@click.option("--threshold", "-t", default=0.75, type=float, help="Similarity threshold for match.")
@click.option("--json-output", is_flag=True, help="Output matches in JSON format.")
def entity_resolve(names: Optional[str], threshold: float, json_output: bool) -> None:
    """Disambiguate corporate aliases and identify potential entity duplicates."""
    name_list: List[str] = []
    if names:
        name_list = [n.strip() for n in names.split(",") if n.strip()]
    else:
        name_list = [
            "Acme Real Estate Holdings, LLC",
            "ACME Real Estate Holdings LLC",
            "Acme RE Holdings Inc",
            "Blackstone Real Estate Group",
            "Blackstone RE Group LP",
        ]

    matches = []
    for i in range(len(name_list)):
        for j in range(i + 1, len(name_list)):
            sim = composite_entity_similarity(name_list[i], name_list[j])
            if sim >= threshold:
                matches.append(
                    {
                        "entity_1": name_list[i],
                        "entity_2": name_list[j],
                        "similarity_score": round(sim, 3),
                        "suggested_canonical": TemporalPropGraph.normalize_entity_name(
                            name_list[i]
                        ),
                    }
                )

    if json_output:
        click.echo(json.dumps(matches, indent=2, default=str))
        return

    table = Table(title=f"Entity Alias Resolution (threshold >= {threshold})")
    table.add_column("Entity 1", style="cyan")
    table.add_column("Entity 2", style="white")
    table.add_column("Score", style="yellow")
    table.add_column("Canonical Name", style="green")

    for m in matches:
        table.add_row(
            m["entity_1"],
            m["entity_2"],
            f"{m['similarity_score']:.3f}",
            m["suggested_canonical"],
        )
    console.print(table)


@cli.command("export-graph")
@click.option("--file", "-f", "file_path", required=True, help="Path to deeds JSON file.")
@click.option(
    "--format",
    "-fmt",
    default="json",
    type=click.Choice(["json", "geojson"]),
    help="Export format.",
)
@click.option("--output", "-o", default=None, help="Path to write export output.")
def export_graph(file_path: str, format: str, output: Optional[str]) -> None:
    """Export property graph topology or GeoJSON."""
    records = _load_records_from_file(file_path)
    graph = TemporalPropGraph()
    validator = DeedStreamValidator()
    clean_list, _, _ = validator.validate_batch(records)
    validator.ingest_batch_to_graph(graph, clean_list)

    if format == "geojson":
        res = graph.export_geojson()
    else:
        res = {
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            "nodes": [{"id": n, "data": graph.graph.nodes[n]} for n in graph.graph.nodes()],
            "edges": [{"u": u, "v": v, "data": d} for u, v, d in graph.graph.edges(data=True)],
        }

    out_str = json.dumps(res, indent=2, default=str)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(out_str)
        console.print(f"[green]Graph exported to {output}[/green]")
    else:
        click.echo(out_str)


if __name__ == "__main__":
    cli()
