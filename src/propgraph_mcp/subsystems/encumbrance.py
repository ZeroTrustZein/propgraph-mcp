"""Encumbrance propagation, lien priority ranking, and cross-collateralization analysis."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from propgraph_mcp.graph import TemporalPropGraph
from propgraph_mcp.types import EdgeType, NodeType

# Relative seniority rank: lower rank number = higher legal priority in foreclosure
LIEN_SENIORITY_RANKS: Dict[str, int] = {
    "tax_lien": 1,
    "mechanics_lien": 2,
    "first_mortgage": 3,
    "deed_of_trust": 3,
    "second_mortgage": 4,
    "mezzanine_debt": 4,
    "ucc_filing": 5,
    "judgment_lien": 6,
    "lis_pendens": 6,
    "easement": 7,
    "covenant": 8,
}


class EncumbranceAnalyzer:
    """Evaluates cross-collateralized debts, lien priority waterfalls, and lender exposure."""

    @staticmethod
    def get_lien_seniority(instrument: str) -> int:
        """Return numeric seniority rank (1 is highest priority)."""
        key = instrument.lower().replace(" ", "_").replace("-", "_")
        for k, v in LIEN_SENIORITY_RANKS.items():
            if k in key:
                return v
        return 99

    def analyze_parcel_encumbrance_waterfall(
        self,
        graph: TemporalPropGraph,
        parcel_id: str,
        property_valuation: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compute full lien waterfall, cumulative LTV, and debt burden on a given parcel."""
        if not graph.graph.has_node(parcel_id):
            return {"error": f"Parcel '{parcel_id}' not found in graph"}

        liens: List[Dict[str, Any]] = []
        total_debt = 0.0

        # Look for in-edges with ENCUMBERS or FINANCED_BY or out-edges with ENCUMBERS
        # In TemporalPropGraph: lender or encumbrance -> parcel (or vice versa)
        for u, v, data in graph.graph.in_edges(parcel_id, data=True):
            edge_type = data.get("edge_type")
            if edge_type in (EdgeType.ENCUMBERS.value, EdgeType.FINANCED_BY.value):
                attrs = data.get("attributes", {})
                amount = float(attrs.get("principal_amount") or attrs.get("amount") or 0.0)
                instrument = attrs.get("instrument") or attrs.get("document_type") or "mortgage"
                seniority = self.get_lien_seniority(instrument)
                liens.append(
                    {
                        "source_id": u,
                        "instrument": instrument,
                        "seniority_rank": seniority,
                        "amount": amount,
                        "recording_date": data.get("effective_date"),
                        "lender": attrs.get("lender") or u,
                    }
                )
                total_debt += amount

        # Also inspect reverse edges if attached out-direction
        for u, v, data in graph.graph.out_edges(parcel_id, data=True):
            edge_type = data.get("edge_type")
            if edge_type in (EdgeType.ENCUMBERS.value, EdgeType.FINANCED_BY.value):
                attrs = data.get("attributes", {})
                amount = float(attrs.get("principal_amount") or attrs.get("amount") or 0.0)
                instrument = attrs.get("instrument") or attrs.get("document_type") or "mortgage"
                seniority = self.get_lien_seniority(instrument)
                liens.append(
                    {
                        "source_id": v,
                        "instrument": instrument,
                        "seniority_rank": seniority,
                        "amount": amount,
                        "recording_date": data.get("effective_date"),
                        "lender": attrs.get("lender") or v,
                    }
                )
                total_debt += amount

        # Sort liens by legal seniority first, then date
        liens.sort(key=lambda x: (x["seniority_rank"], str(x["recording_date"] or "")))

        # Waterfall calculation against valuation
        cumulative_debt = 0.0
        val = property_valuation or 0.0
        waterfall: List[Dict[str, Any]] = []

        for item in liens:
            amt = item["amount"]
            prior_debt = cumulative_debt
            cumulative_debt += amt
            coverage_pct = 1.0
            if val > 0.0:
                if cumulative_debt <= val:
                    coverage_pct = 1.0
                elif prior_debt < val:
                    coverage_pct = round((val - prior_debt) / amt, 4)
                else:
                    coverage_pct = 0.0

            waterfall.append(
                {
                    **item,
                    "cumulative_debt": round(cumulative_debt, 2),
                    "cumulative_ltv": round(cumulative_debt / val, 4) if val > 0.0 else None,
                    "recovery_percentage": coverage_pct,
                }
            )

        ltv = round(total_debt / val, 4) if val > 0.0 else None
        remaining_equity = max(0.0, val - total_debt) if val > 0.0 else None

        return {
            "parcel_id": parcel_id,
            "property_valuation": val,
            "total_encumbrances": len(liens),
            "total_debt": round(total_debt, 2),
            "overall_ltv": ltv,
            "total_ltv": ltv,
            "remaining_equity": round(remaining_equity, 2)
            if remaining_equity is not None
            else None,
            "has_senior_tax_lien": any(x["seniority_rank"] == 1 for x in liens),
            "waterfall": waterfall,
        }

    def detect_cross_collateralization(self, graph: TemporalPropGraph) -> List[Dict[str, Any]]:
        """Identify blanket mortgages or lenders cross-collateralized across multiple properties."""
        lender_parcels: Dict[str, List[Dict[str, Any]]] = {}

        for u, v, data in graph.graph.edges(data=True):
            edge_type = data.get("edge_type")
            if edge_type in (EdgeType.ENCUMBERS.value, EdgeType.FINANCED_BY.value):
                # Identify parcel and lender
                node_u = graph.graph.nodes.get(u, {})
                node_v = graph.graph.nodes.get(v, {})

                parcel_id = None
                lender_id = None
                if node_v.get("node_type") == NodeType.PROPERTY.value:
                    parcel_id = v
                    lender_id = u
                elif node_u.get("node_type") == NodeType.PROPERTY.value:
                    parcel_id = u
                    lender_id = v
                else:
                    parcel_id = v
                    lender_id = u

                attrs = data.get("attributes", {})
                amt = float(attrs.get("principal_amount") or attrs.get("amount") or 0.0)

                lender_parcels.setdefault(lender_id, []).append(
                    {
                        "parcel_id": parcel_id,
                        "amount": amt,
                        "effective_date": data.get("effective_date"),
                        "instrument": attrs.get("instrument") or "mortgage",
                    }
                )

        cross_collateral: List[Dict[str, Any]] = []
        for lender_id, entries in lender_parcels.items():
            distinct_parcels = list({e["parcel_id"] for e in entries})
            if len(distinct_parcels) > 1:
                total_portfolio_debt = sum(e["amount"] for e in entries)
                cross_collateral.append(
                    {
                        "lender_id": lender_id,
                        "parcel_count": len(distinct_parcels),
                        "parcels": distinct_parcels,
                        "total_cross_collateral_debt": round(total_portfolio_debt, 2),
                        "entries": entries,
                    }
                )

        return cross_collateral
