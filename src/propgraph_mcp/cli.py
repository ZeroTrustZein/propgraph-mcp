"""Command line interface for PropGraph MCP."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from propgraph_mcp import __version__
from propgraph_mcp.server import create_mcp_server
from propgraph_mcp.valuation import DCFValuationEngine

console = Console()


@click.group()
@click.version_option(__version__, prog_name="propgraph")
def cli() -> None:
    """PropGraph MCP: Autonomous CRE underwriting swarm CLI."""


@cli.command()
def info() -> None:
    """Display PropGraph MCP package metadata and system capabilities."""
    console.print(f"[bold cyan]PropGraph MCP[/bold cyan] [green]v{__version__}[/green]")
    console.print("Autonomous CRE underwriting swarm using temporal Graph-RAG over municipal deed streams and SEC filings.")

    table = Table(title="Core Subsystems & MCP Capabilities")
    table.add_column("Subsystem", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Status", style="green")

    table.add_row("Temporal Graph-RAG", "NetworkX MultiDiGraph chain-of-title & SEC disclosure traversal", "Ready")
    table.add_row("Multi-Scenario DCF", "Base / Bull / Bear cash flow simulations with IRR & NPV", "Ready")
    table.add_row("Geospatial Risk", "Flood, seismic, zoning compliance, environmental risk scoring", "Ready")
    table.add_row("MCP Server", "Model Context Protocol v2 tools & resources endpoint", "Ready")
    console.print(table)


@cli.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]), help="MCP transport protocol.")
@click.option("--port", default=8000, type=int, help="Port for SSE transport.")
def serve(transport: str, port: int) -> None:
    """Launch the PropGraph MCP Server."""
    console.print(f"[bold green]Starting PropGraph MCP Server[/bold green] (transport: {transport}, port: {port})...")
    server = create_mcp_server()
    if transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="sse", port=port)


@cli.command()
@click.option("--apn", default="APN-098-442-01", help="Assessor parcel number.")
@click.option("--price", default=10_000_000.0, type=float, help="Property purchase price.")
@click.option("--revenue", default=1_200_000.0, type=float, help="Initial gross revenue.")
@click.option("--expenses", default=400_000.0, type=float, help="Initial operating expenses.")
def underwrite(apn: str, price: float, revenue: float, expenses: float) -> None:
    """Execute multi-scenario DCF underwriting for a property."""
    engine = DCFValuationEngine()
    results = engine.run_all_scenarios(
        property_id=apn,
        initial_gross_revenue=revenue,
        initial_operating_expenses=expenses,
        purchase_price=price,
    )

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


if __name__ == "__main__":
    cli()
