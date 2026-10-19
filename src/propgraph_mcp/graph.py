"""Temporal Graph-RAG engine for CRE entity resolution and deed/SEC lineage."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

import networkx as nx

from propgraph_mcp.types import (
    DeedRecord,
    EdgeType,
    EncumbranceRecord,
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

        # Edge: Deed conveys parcel
        self.add_edge(
            GraphEdge(
                source_id=deed_node_id,
                target_id=deed.parcel_id,
                edge_type=EdgeType.TRANSFERRED_TO,
                effective_date=deed.transfer_date,
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

    @staticmethod
    def normalize_entity_name(name: str) -> str:
        """Standardize corporate and entity names by removing punctuation and legal suffixes."""
        cleaned = name.lower().strip()
        # Remove periods so L.L.C. -> llc, Inc. -> inc
        cleaned = re.sub(r"\.", "", cleaned)
        cleaned = re.sub(r"[,;:\-\']", " ", cleaned)
        suffixes = [
            r"\bllc\b",
            r"\bllp\b",
            r"\blp\b",
            r"\binc\b",
            r"\bincorporated\b",
            r"\bcorp\b",
            r"\bcorporation\b",
            r"\bltd\b",
            r"\blimited\b",
            r"\bco\b",
            r"\bcompany\b",
            r"\btrust\b",
            r"\breit\b",
        ]
        for pattern in suffixes:
            cleaned = re.sub(pattern, " ", cleaned)
        return " ".join(cleaned.split())

    def get_deeds_for_parcel(self, parcel_id: str) -> List[Dict[str, Any]]:
        """Return chronologically sorted list of deed attributes for a parcel."""
        deeds = [
            dict(data.get("attributes", {}))
            for _, data in self.graph.nodes(data=True)
            if (
                data.get("node_type") == NodeType.DEED.value
                and data.get("attributes", {}).get("parcel_id") == parcel_id
            )
        ]
        deeds.sort(key=lambda d: str(d.get("transfer_date", "")))
        return deeds

    def verify_chain_of_title(self, parcel_id: str) -> Dict[str, Any]:
        """Validate unbroken chain of title and detect defects or gaps across deeds."""
        deeds = self.get_deeds_for_parcel(parcel_id)
        breaks: List[Dict[str, Any]] = []
        warnings: List[str] = []
        has_quitclaim = False

        for i, deed in enumerate(deeds):
            doc_type = str(deed.get("document_type", ""))
            if "quitclaim" in doc_type.lower():
                has_quitclaim = True
                warnings.append(
                    f"Deed {deed.get('deed_id')} is a Quitclaim Deed with no title warranty."
                )

            if i > 0:
                prev_grantee = deeds[i - 1].get("grantee", "")
                curr_grantor = deed.get("grantor", "")
                if self.normalize_entity_name(prev_grantee) != self.normalize_entity_name(
                    curr_grantor
                ):
                    breaks.append(
                        {
                            "deed_id": deed.get("deed_id"),
                            "previous_grantee": prev_grantee,
                            "current_grantor": curr_grantor,
                            "transfer_date": deed.get("transfer_date"),
                            "reason": "Grantor does not match prior grantee in chain of title.",
                        }
                    )

        current_owner = deeds[-1].get("grantee") if deeds else None

        return {
            "parcel_id": parcel_id,
            "is_valid": len(breaks) == 0,
            "deed_count": len(deeds),
            "current_owner": current_owner,
            "breaks": breaks,
            "has_quitclaim": has_quitclaim,
            "warnings": warnings,
        }

    def get_ownership_at_date(self, parcel_id: str, as_of: date) -> Optional[Dict[str, Any]]:
        """Determine verified property ownership as of a specific historical date."""
        timeline = self.get_ownership_timeline(parcel_id)
        as_of_str = as_of.isoformat()

        # Timeline is sorted newest first; find the first entry on or before as_of
        for entry in timeline:
            eff = entry.get("effective_date")
            if eff and str(eff) <= as_of_str:
                return entry
        return None

    def get_entity_portfolio(self, entity_name: str) -> List[Dict[str, Any]]:
        """Find all real estate assets owned or disclosed by a corporate entity."""
        norm_target = self.normalize_entity_name(entity_name)
        matched_entities = []

        for n, data in self.graph.nodes(data=True):
            if data.get("node_type") == NodeType.ENTITY.value:
                label = data.get("label", "")
                if self.normalize_entity_name(label) == norm_target:
                    matched_entities.append(n)

        portfolio: List[Dict[str, Any]] = []
        seen_parcels = set()

        for ent_id in matched_entities:
            # Check direct property ownership
            for _, target, edge_data in self.graph.out_edges(ent_id, data=True):
                if edge_data.get("edge_type") == EdgeType.OWNS.value:
                    if target not in seen_parcels:
                        seen_parcels.add(target)
                        portfolio.append(
                            {
                                "parcel_id": target,
                                "relationship": "owns",
                                "effective_date": edge_data.get("effective_date"),
                                "sale_price": edge_data.get("attributes", {}).get("sale_price"),
                            }
                        )

            # Check SEC filing disclosures
            for _, sec_id, edge_data in self.graph.out_edges(ent_id, data=True):
                if edge_data.get("edge_type") == EdgeType.DISCLOSED_IN.value:
                    for _, prop_target, sec_edge_data in self.graph.out_edges(sec_id, data=True):
                        if sec_edge_data.get("edge_type") == EdgeType.DISCLOSED_IN.value:
                            if prop_target not in seen_parcels:
                                seen_parcels.add(prop_target)
                                portfolio.append(
                                    {
                                        "parcel_id": prop_target,
                                        "relationship": "disclosed_in_sec",
                                        "filing_id": sec_id,
                                        "effective_date": sec_edge_data.get("effective_date"),
                                    }
                                )

        return portfolio

    def add_financing(
        self,
        lender_name: str,
        parcel_id: str,
        loan_amount: float,
        recording_date: date,
        maturity_date: Optional[date] = None,
        loan_type: str = "Mortgage",
    ) -> str:
        """Attach a mortgage or deed of trust financing encumbrance to a property parcel."""
        lender_id = f"lender:{self.normalize_entity_name(lender_name).replace(' ', '_')}"
        if not self.graph.has_node(lender_id):
            self.add_node(
                GraphNode(
                    node_id=lender_id,
                    node_type=NodeType.LENDER,
                    label=lender_name,
                )
            )

        self.add_edge(
            GraphEdge(
                source_id=lender_id,
                target_id=parcel_id,
                edge_type=EdgeType.FINANCED_BY,
                effective_date=recording_date,
                attributes={
                    "loan_amount": loan_amount,
                    "maturity_date": maturity_date.isoformat() if maturity_date else None,
                    "loan_type": loan_type,
                    "status": "active",
                },
            )
        )
        return lender_id

    def get_property_encumbrances(self, parcel_id: str) -> List[Dict[str, Any]]:
        """Retrieve all active financing instruments and encumbrances on a property parcel."""
        encumbrances: List[Dict[str, Any]] = []
        if not self.graph.has_node(parcel_id):
            return encumbrances

        for u, _, edge_data in self.graph.in_edges(parcel_id, data=True):
            if edge_data.get("edge_type") in [
                EdgeType.FINANCED_BY.value,
                EdgeType.ENCUMBERS.value,
            ]:
                lender_label = self.graph.nodes[u].get("label", u)
                attrs = edge_data.get("attributes", {})
                encumbrances.append(
                    {
                        "lender_id": u,
                        "lender_name": lender_label,
                        "loan_amount": attrs.get("loan_amount", 0.0),
                        "loan_type": attrs.get("loan_type", "Mortgage"),
                        "effective_date": edge_data.get("effective_date"),
                        "maturity_date": attrs.get("maturity_date"),
                        "status": attrs.get("status", "active"),
                    }
                )

        encumbrances.sort(key=lambda x: str(x.get("effective_date", "")), reverse=True)
        return encumbrances

    def get_chain_of_title(self, parcel_id: str) -> List[Dict[str, Any]]:
        """Return chronological deed history with break-in-title detection for each transfer."""
        deeds = self.get_deeds_for_parcel(parcel_id)
        result: List[Dict[str, Any]] = []

        for i, deed in enumerate(deeds):
            is_break = False
            break_reason = None
            if i > 0:
                prev_grantee = deeds[i - 1].get("grantee", "")
                curr_grantor = deed.get("grantor", "")
                if self.normalize_entity_name(prev_grantee) != self.normalize_entity_name(
                    curr_grantor
                ):
                    is_break = True
                    break_reason = (
                        f"Grantor '{curr_grantor}' does not match prior grantee '{prev_grantee}'"
                    )

            result.append(
                {
                    "deed_id": deed.get("deed_id"),
                    "parcel_id": parcel_id,
                    "grantor": deed.get("grantor"),
                    "grantee": deed.get("grantee"),
                    "transfer_date": deed.get("transfer_date"),
                    "sale_price": deed.get("sale_price"),
                    "document_type": deed.get("document_type"),
                    "recording_number": deed.get("recording_number"),
                    "is_break_in_title": is_break,
                    "break_reason": break_reason,
                }
            )
        return result

    def add_encumbrance(self, enc: EncumbranceRecord) -> None:
        """Attach a formal EncumbranceRecord to a parcel in the graph."""
        enc_type_val = (
            enc.encumbrance_type.value
            if hasattr(enc.encumbrance_type, "value")
            else str(enc.encumbrance_type)
        )
        lender_id = f"lender:{self.normalize_entity_name(enc.lender).replace(' ', '_')}"
        if not self.graph.has_node(lender_id):
            self.add_node(
                GraphNode(
                    node_id=lender_id,
                    node_type=NodeType.LENDER,
                    label=enc.lender,
                )
            )
        self.add_edge(
            GraphEdge(
                source_id=lender_id,
                target_id=enc.parcel_id,
                edge_type=EdgeType.ENCUMBERS,
                effective_date=enc.recording_date,
                attributes={
                    "encumbrance_id": enc.encumbrance_id,
                    "instrument": enc_type_val,
                    "amount": enc.amount,
                    "principal_amount": enc.amount,
                    "lender": enc.lender,
                    "seniority_rank": enc.seniority_rank,
                },
            )
        )

    def export_geojson(self) -> Dict[str, Any]:
        """Export parcel nodes as GeoJSON FeatureCollection."""
        features: List[Dict[str, Any]] = []
        for node_id, data in self.graph.nodes(data=True):
            if data.get("node_type") == NodeType.PROPERTY.value:
                attrs = data.get("attributes", {})
                lat = attrs.get("latitude")
                lon = attrs.get("longitude")
                if lat is not None and lon is not None:
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [float(lon), float(lat)],
                            },
                            "properties": {
                                "apn": node_id,
                                **attrs,
                            },
                        }
                    )
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()
