"""Temporal Graph-RAG engine for CRE entity resolution and deed/SEC lineage."""

from __future__ import annotations

from typing import Any, Dict, List

import networkx as nx

from propgraph_mcp.types import (
    DeedRecord,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    PropertyParcel,
    SECFilingRecord,
)


class TemporalPropGraph:
    """MultiDiGraph capturing temporal relationships between properties, deeds, SEC filings, and entities."""

    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()

    def add_node(self, node: GraphNode) -> None:
        self.graph.add_node(
            node.node_id,
            node_type=node.node_type.value,
            label=node.label,
            attributes=node.attributes,
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_to=node.valid_to.isoformat() if node.valid_to else None,
        )

    def add_edge(self, edge: GraphEdge) -> None:
        self.graph.add_edge(
            edge.source_id,
            edge.target_id,
            edge_type=edge.edge_type.value,
            attributes=edge.attributes,
            effective_date=edge.effective_date.isoformat() if edge.effective_date else None,
        )

    def add_property(self, parcel: PropertyParcel) -> None:
        node = GraphNode(
            node_id=parcel.apn,
            node_type=NodeType.PROPERTY,
            label=f"{parcel.address}, {parcel.city}",
            attributes=parcel.model_dump(),
        )
        self.add_node(node)

    def add_deed(self, deed: DeedRecord) -> None:
        deed_node_id = f"deed:{deed.deed_id}"
        self.add_node(
            GraphNode(
                node_id=deed_node_id,
                node_type=NodeType.DEED,
                label=f"Deed {deed.deed_id} ({deed.document_type})",
                attributes=deed.model_dump(),
            )
        )

        # Grantor Entity node
        grantor_id = f"entity:{deed.grantor.lower().replace(' ', '_')}"
        if not self.graph.has_node(grantor_id):
            self.add_node(
                GraphNode(
                    node_id=grantor_id,
                    node_type=NodeType.ENTITY,
                    label=deed.grantor,
                )
            )

        # Grantee Entity node
        grantee_id = f"entity:{deed.grantee.lower().replace(' ', '_')}"
        if not self.graph.has_node(grantee_id):
            self.add_node(
                GraphNode(
                    node_id=grantee_id,
                    node_type=NodeType.ENTITY,
                    label=deed.grantee,
                )
            )

        # Edge: Grantor transferred deed
        self.add_edge(
            GraphEdge(
                source_id=grantor_id,
                target_id=deed_node_id,
                edge_type=EdgeType.TRANSFERRED_TO,
                effective_date=deed.transfer_date,
            )
        )

        # Edge: Deed transferred to Grantee
        self.add_edge(
            GraphEdge(
                source_id=deed_node_id,
                target_id=grantee_id,
                edge_type=EdgeType.TRANSFERRED_TO,
                effective_date=deed.transfer_date,
            )
        )

        # Edge: Grantee owns Property
        self.add_edge(
            GraphEdge(
                source_id=grantee_id,
                target_id=deed.parcel_id,
                edge_type=EdgeType.OWNS,
                effective_date=deed.transfer_date,
                attributes={"sale_price": deed.sale_price},
            )
        )

    def add_sec_filing(self, filing: SECFilingRecord) -> None:
        filing_node_id = f"sec:{filing.accession_number}"
        self.add_node(
            GraphNode(
                node_id=filing_node_id,
                node_type=NodeType.SEC_FILING,
                label=f"{filing.company_name} {filing.filing_type}",
                attributes=filing.model_dump(),
            )
        )

        entity_id = f"entity:{filing.company_name.lower().replace(' ', '_')}"
        if not self.graph.has_node(entity_id):
            self.add_node(
                GraphNode(
                    node_id=entity_id,
                    node_type=NodeType.ENTITY,
                    label=filing.company_name,
                    attributes={"cik": filing.cik},
                )
            )

        # Entity disclosed in filing
        self.add_edge(
            GraphEdge(
                source_id=entity_id,
                target_id=filing_node_id,
                edge_type=EdgeType.DISCLOSED_IN,
                effective_date=filing.filing_date,
            )
        )

        for prop_id in filing.properties_mentioned:
            if self.graph.has_node(prop_id):
                self.add_edge(
                    GraphEdge(
                        source_id=filing_node_id,
                        target_id=prop_id,
                        edge_type=EdgeType.DISCLOSED_IN,
                        effective_date=filing.filing_date,
                    )
                )

    def get_ownership_timeline(self, parcel_id: str) -> List[Dict[str, Any]]:
        """Extract chronologically ordered chain of title for a property parcel."""
        timeline: List[Dict[str, Any]] = []
        if not self.graph.has_node(parcel_id):
            return timeline

        for u, v, data in self.graph.in_edges(parcel_id, data=True):
            if data.get("edge_type") == EdgeType.OWNS.value:
                owner_label = self.graph.nodes[u].get("label", u)
                timeline.append(
                    {
                        "owner_id": u,
                        "owner_name": owner_label,
                        "effective_date": data.get("effective_date"),
                        "sale_price": data.get("attributes", {}).get("sale_price", 0.0),
                    }
                )

        timeline.sort(key=lambda x: str(x.get("effective_date", "")), reverse=True)
        return timeline

    def get_related_entities(self, node_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Traverse connected neighborhood around a property or entity."""
        if not self.graph.has_node(node_id):
            return []

        undirected = self.graph.to_undirected()
        subgraph_nodes = nx.single_source_shortest_path_length(undirected, node_id, cutoff=depth)

        results = []
        for n, dist in subgraph_nodes.items():
            if n != node_id:
                node_data = self.graph.nodes[n]
                results.append(
                    {
                        "node_id": n,
                        "distance": dist,
                        "node_type": node_data.get("node_type"),
                        "label": node_data.get("label"),
                    }
                )
        return sorted(results, key=lambda x: x["distance"])

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()
