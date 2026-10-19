"""Spatial contiguity, geographic distance, and parcel assemblage analysis."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.types import EdgeType, GraphEdge, NodeType, PropertyParcel


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Compute great-circle distance between two WGS84 coordinates in meters."""
    earth_radius_m = 6371000.0  # Earth radius in meters

    rlat1 = math.radians(lat1)
    rlon1 = math.radians(lon1)
    rlat2 = math.radians(lat2)
    rlon2 = math.radians(lon2)

    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return earth_radius_m * c


def haversine_distance_feet(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Compute great-circle distance between two WGS84 coordinates in feet."""
    return haversine_distance_meters(lat1, lon1, lat2, lon2) * 3.28084


class SpatialContiguityEngine:
    """Analyzes spatial adjacency, contiguity, and assemblage potential across parcel boundaries."""

    def __init__(self, default_adjacency_threshold_meters: float = 150.0) -> None:
        self.default_threshold_m = default_adjacency_threshold_meters

    def infer_spatial_adjacencies(
        self,
        graph: TemporalPropGraph,
        max_distance_meters: Optional[float] = None,
    ) -> int:
        """Infer and add adjacency edges for parcels within geographic distance threshold."""
        threshold = max_distance_meters or self.default_threshold_m
        parcels: List[Tuple[str, float, float, Dict[str, Any]]] = []

        for node_id, data in graph.graph.nodes(data=True):
            if data.get("node_type") == NodeType.PROPERTY.value:
                attrs = data.get("attributes", {})
                lat = attrs.get("latitude")
                lon = attrs.get("longitude")
                if lat is not None and lon is not None:
                    parcels.append((node_id, float(lat), float(lon), attrs))

        edges_added = 0
        n = len(parcels)
        for i in range(n):
            id1, lat1, lon1, _ = parcels[i]
            for j in range(i + 1, n):
                id2, lat2, lon2, _ = parcels[j]
                dist = haversine_distance_meters(lat1, lon1, lat2, lon2)
                if dist <= threshold:
                    # Check if adjacency edge already exists
                    has_edge = False
                    for _, _, edata in graph.graph.out_edges(id1, data=True):
                        if edata.get("edge_type") == "adjacent_to":
                            has_edge = True
                            break

                    if not has_edge:
                        graph.add_edge(
                            GraphEdge(
                                source_id=id1,
                                target_id=id2,
                                edge_type=EdgeType.TRANSFERRED_TO,  # or custom adjacent edge
                                attributes={
                                    "distance_meters": round(dist, 2),
                                    "distance_feet": round(dist * 3.28084, 1),
                                    "relationship": "adjacent_to",
                                },
                            )
                        )
                        edges_added += 1

        return edges_added

    def find_assemblage_clusters(
        self,
        graph: TemporalPropGraph,
        max_distance_meters: float = 200.0,
        assemblage_bonus_rate: float = 0.15,
    ) -> List[Dict[str, Any]]:
        """Identify adjacent or contiguous parcels owned by the same or affiliated entity."""
        # Find owners and their properties
        owner_parcels: Dict[str, List[Tuple[str, float, float, float]]] = {}

        for node_id, data in graph.graph.nodes(data=True):
            if data.get("node_type") == NodeType.PROPERTY.value:
                attrs = data.get("attributes", {})
                lat = attrs.get("latitude")
                lon = attrs.get("longitude")
                sqft = float(attrs.get("square_feet") or 0.0)

                # Determine current owner from graph
                owner = None
                for u, _, edata in graph.graph.in_edges(node_id, data=True):
                    if edata.get("edge_type") == EdgeType.OWNS.value:
                        owner = u
                        break

                if owner and lat is not None and lon is not None:
                    owner_parcels.setdefault(owner, []).append((node_id, lat, lon, sqft))

        if not owner_parcels:
            unowned: List[Tuple[str, float, float, float]] = []
            for node_id, data in graph.graph.nodes(data=True):
                if data.get("node_type") == NodeType.PROPERTY.value:
                    attrs = data.get("attributes", {})
                    lat = attrs.get("latitude")
                    lon = attrs.get("longitude")
                    sqft = float(attrs.get("square_feet") or 0.0)
                    if lat is not None and lon is not None:
                        unowned.append((node_id, lat, lon, sqft))
            if len(unowned) >= 2:
                owner_parcels["common_assemblage"] = unowned

        assemblages: List[Dict[str, Any]] = []

        for owner, props in owner_parcels.items():
            if len(props) < 2:
                continue

            # Build adjacency graph among properties owned by this owner
            adj_graph = nx.Graph()
            for p_id, lat, lon, sqft in props:
                adj_graph.add_node(p_id, lat=lat, lon=lon, sqft=sqft)

            m = len(props)
            for i in range(m):
                id1, lat1, lon1, _ = props[i]
                for j in range(i + 1, m):
                    id2, lat2, lon2, _ = props[j]
                    d = haversine_distance_meters(lat1, lon1, lat2, lon2)
                    if d <= max_distance_meters:
                        adj_graph.add_edge(id1, id2, distance=d)

            # Connected components in adj_graph form assemblage clusters
            for comp in nx.connected_components(adj_graph):
                if len(comp) >= 2:
                    cluster_parcels = list(comp)
                    total_sqft = sum(
                        adj_graph.nodes[p]["sqft"] for p in cluster_parcels
                    )
                    assemblages.append(
                        {
                            "owner_entity": owner,
                            "parcel_count": len(cluster_parcels),
                            "parcels": cluster_parcels,
                            "combined_square_feet": total_sqft,
                            "assemblage_bonus_rate": assemblage_bonus_rate,
                            "estimated_density_uplift": round(total_sqft * assemblage_bonus_rate, 2),
                        }
                    )

        return assemblages

    @staticmethod
    def calculate_bounding_box(
        parcels: List[PropertyParcel | Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compute minimum bounding box and geographic centroid across parcels."""
        lats: List[float] = []
        lons: List[float] = []

        for p in parcels:
            lat = p.latitude if isinstance(p, PropertyParcel) else p.get("latitude")
            lon = p.longitude if isinstance(p, PropertyParcel) else p.get("longitude")
            if lat is not None and lon is not None:
                lats.append(float(lat))
                lons.append(float(lon))

        if not lats or not lons:
            return {"error": "No valid geographic coordinates found in parcels"}

        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)

        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)

        span_ns_m = haversine_distance_meters(min_lat, center_lon, max_lat, center_lon)
        span_ew_m = haversine_distance_meters(center_lat, min_lon, center_lat, max_lon)

        return {
            "min_latitude": min_lat,
            "max_latitude": max_lat,
            "min_longitude": min_lon,
            "max_longitude": max_lon,
            "centroid": {"latitude": round(center_lat, 6), "longitude": round(center_lon, 6)},
            "span_north_south_meters": round(span_ns_m, 2),
            "span_east_west_meters": round(span_ew_m, 2),
            "total_geocoded_parcels": len(lats),
        }
