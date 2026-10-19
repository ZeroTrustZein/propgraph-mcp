"""Entity resolution, corporate alias disambiguation, and beneficial ownership tracing."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.types import EdgeType, NodeType


def token_jaccard_similarity(str1: str, str2: str) -> float:
    """Compute Jaccard similarity over word token sets."""
    tokens1 = set(re.findall(r"\w+", str1.lower()))
    tokens2 = set(re.findall(r"\w+", str2.lower()))
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def character_ngram_similarity(str1: str, str2: str, n: int = 3) -> float:
    """Compute n-gram Jaccard similarity over characters."""
    s1, s2 = re.sub(r"\s+", "", str1.lower()), re.sub(r"\s+", "", str2.lower())
    if s1 == s2:
        return 1.0
    if len(s1) < n or len(s2) < n:
        return 1.0 if s1 in s2 or s2 in s1 else 0.0

    ngrams1 = {s1[i : i + n] for i in range(len(s1) - n + 1)}
    ngrams2 = {s2[i : i + n] for i in range(len(s2) - n + 1)}
    inter = ngrams1.intersection(ngrams2)
    union = ngrams1.union(ngrams2)
    return len(inter) / len(union) if union else 0.0


def composite_entity_similarity(name1: str, name2: str) -> float:
    """Composite similarity combining standardized tokens and character n-grams."""
    norm1 = TemporalPropGraph.normalize_entity_name(name1)
    norm2 = TemporalPropGraph.normalize_entity_name(name2)
    if norm1 == norm2:
        return 1.0
    if not norm1 or not norm2:
        return 0.0

    tok_sim = token_jaccard_similarity(norm1, norm2)
    ngram_sim = character_ngram_similarity(norm1, norm2, n=3)
    return round(0.6 * tok_sim + 0.4 * ngram_sim, 4)


class EntityResolver:
    """Resolves corporate aliases, consolidates entity duplicates, and traces beneficial ownership."""

    def __init__(self, similarity_threshold: float = 0.80) -> None:
        self.similarity_threshold = similarity_threshold

    def are_likely_same_entity(
        self, name1: str, name2: str, threshold: Optional[float] = None
    ) -> Tuple[bool, float]:
        """Check if two entity names likely denote the same corporate entity."""
        sim = composite_entity_similarity(name1, name2)
        target = threshold if threshold is not None else self.similarity_threshold
        return sim >= target, sim

    def find_duplicate_entities(
        self, graph: TemporalPropGraph, threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Identify potential duplicate entity vertices in the graph."""
        target = threshold if threshold is not None else self.similarity_threshold
        entity_nodes: List[Tuple[str, str, Dict[str, Any]]] = []

        for node_id, data in graph.graph.nodes(data=True):
            if data.get("node_type") == NodeType.ENTITY.value:
                label = data.get("label", node_id)
                entity_nodes.append((node_id, label, data.get("attributes", {})))

        duplicates: List[Dict[str, Any]] = []
        n = len(entity_nodes)
        for i in range(n):
            id1, name1, attr1 = entity_nodes[i]
            for j in range(i + 1, n):
                id2, name2, attr2 = entity_nodes[j]

                # Match by exact CIK if both have it
                cik1 = attr1.get("cik")
                cik2 = attr2.get("cik")
                if cik1 and cik2 and cik1 == cik2:
                    duplicates.append(
                        {
                            "entity_id_1": id1,
                            "name_1": name1,
                            "entity_id_2": id2,
                            "name_2": name2,
                            "similarity": 1.0,
                            "match_reason": "MATCHING_CIK",
                        }
                    )
                    continue

                is_match, score = self.are_likely_same_entity(name1, name2, threshold=target)
                if is_match:
                    duplicates.append(
                        {
                            "entity_id_1": id1,
                            "name_1": name1,
                            "entity_id_2": id2,
                            "name_2": name2,
                            "similarity": score,
                            "match_reason": "NAME_SIMILARITY",
                        }
                    )

        return duplicates

    def merge_entities(
        self, graph: TemporalPropGraph, primary_id: str, duplicate_id: str
    ) -> bool:
        """Merge duplicate entity into primary entity, repointing all edges."""
        if primary_id == duplicate_id:
            return False
        if not graph.graph.has_node(primary_id) or not graph.graph.has_node(duplicate_id):
            return False

        # Merge node attributes
        primary_data = graph.graph.nodes[primary_id]
        duplicate_data = graph.graph.nodes[duplicate_id]

        primary_attrs = primary_data.setdefault("attributes", {})
        dup_attrs = duplicate_data.get("attributes", {})

        # Record alias
        aliases = primary_attrs.setdefault("aliases", [])
        dup_label = duplicate_data.get("label")
        if dup_label and dup_label not in aliases and dup_label != primary_data.get("label"):
            aliases.append(dup_label)

        # Merge missing attributes
        for k, v in dup_attrs.items():
            if k not in primary_attrs:
                primary_attrs[k] = v

        # Rewire incoming edges to duplicate -> primary
        in_edges = list(graph.graph.in_edges(duplicate_id, data=True, keys=True))
        for u, _, key, data in in_edges:
            if u != primary_id:  # prevent self-loop
                graph.graph.add_edge(u, primary_id, **data)

        # Rewire outgoing edges from duplicate -> primary
        out_edges = list(graph.graph.out_edges(duplicate_id, data=True, keys=True))
        for _, v, key, data in out_edges:
            if v != primary_id:  # prevent self-loop
                graph.graph.add_edge(primary_id, v, **data)

        # Remove duplicate node
        graph.graph.remove_node(duplicate_id)
        return True

    def trace_ultimate_beneficial_owners(
        self, graph: TemporalPropGraph, entity_id: str
    ) -> List[Dict[str, Any]]:
        """Trace holding companies and ultimate beneficial owners (UBO) upstream."""
        if not graph.graph.has_node(entity_id):
            return []

        visited: Set[str] = set()
        ubo_list: List[Dict[str, Any]] = []
        queue: List[Tuple[str, int]] = [(entity_id, 0)]

        while queue:
            curr_id, depth = queue.pop(0)
            if curr_id in visited:
                continue
            visited.add(curr_id)

            node_data = graph.graph.nodes[curr_id]
            is_parent = False

            # Search in-edges for ownership or parent relationship
            for u, _, data in graph.graph.in_edges(curr_id, data=True):
                edge_type = data.get("edge_type")
                if edge_type in (EdgeType.OWNS.value, "subsidiary_of", "parent_of"):
                    is_parent = True
                    queue.append((u, depth + 1))

            if depth > 0:
                ubo_list.append(
                    {
                        "entity_id": curr_id,
                        "label": node_data.get("label", curr_id),
                        "depth": depth,
                        "node_type": node_data.get("node_type"),
                        "is_terminal_parent": not is_parent,
                        "cik": node_data.get("attributes", {}).get("cik"),
                    }
                )

        return ubo_list
