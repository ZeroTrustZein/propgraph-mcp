# PropGraph MCP

**PropGraph MCP** is an autonomous Commercial Real Estate (CRE) underwriting swarm using temporal Graph-RAG over municipal deed streams and SEC filings to automate multi-scenario DCF valuation and geospatial risk analysis via the Model Context Protocol (MCP).

---

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │            Model Context Protocol      │
                      │               (MCP Server v2)          │
                      └───────────────────▲────────────────────┘
                                          │
       ┌──────────────────────────────────┴──────────────────────────────────┐
       │                                                                     │
┌──────┴───────────────┐           ┌──────────────────────┐        ┌────────┴───────────────┐
│  Temporal Graph-RAG  │           │  Multi-Scenario DCF  │        │  Geospatial & Climate  │
│  (Deed & SEC Lineage)│           │  (Valuation & Yield) │        │     Risk Engine        │
└──────▲───────────────┘           └──────────────────────┘        └────────────────────────┘
       │
┌──────┴───────────────┐
│ Municipal Deeds &    │
│ SEC EDGAR Streams    │
└──────────────────────┘
```

### Key Subsystems
1. **Temporal Graph-RAG (`propgraph_mcp.graph`)**:
   - Directed multigraph tracking ownership changes, warranties, encumbrances, and SEC EDGAR holding disclosures across time.
   - Extracts complete chain-of-title and entity networks.
2. **Multi-Scenario DCF Engine (`propgraph_mcp.valuation`)**:
   - Automated financial projection supporting Base, Bull, and Bear underwriting cases.
   - Computes Net Present Value (NPV), Internal Rate of Return (IRR), and Terminal Capitalization.
3. **Geospatial & Regulatory Risk (`propgraph_mcp.risk`)**:
   - Composite scoring across flood hazard, seismic exposure, zoning compliance, and environmental proximity.
4. **Model Context Protocol (`propgraph_mcp.server`)**:
   - Exposes underwriting tools directly to LLM agents: `query_property_graph`, `ingest_deed_record`, `ingest_sec_filing`, `calculate_dcf_valuation`, `assess_geospatial_risk`, and `run_underwriting_pipeline`.

---

## Installation

```bash
git clone https://github.com/zein/propgraph-mcp.git
cd propgraph-mcp
python -m pip install -e ".[dev]"
```

---

## CLI Usage

```bash
# View metadata and capabilities
python -m propgraph_mcp.cli info

# Run quick multi-scenario DCF underwriting
python -m propgraph_mcp.cli underwrite --apn APN-102-55 --price 12000000 --revenue 1400000 --expenses 450000

# Start MCP Server
python -m propgraph_mcp.cli serve --transport stdio
```

---

## Running Tests

```bash
python -m pytest tests
python -m ruff check src tests
```
