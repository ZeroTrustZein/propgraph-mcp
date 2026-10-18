"""Geospatial, climate, and zoning compliance risk assessment engine."""

from __future__ import annotations

from typing import Optional

from propgraph_mcp.types import GeospatialRiskMetrics, PropertyParcel


class GeospatialRiskEngine:
    """Evaluates multi-factor spatial risk including flood, seismic, and zoning compliance."""

    def __init__(
        self,
        flood_weight: float = 0.35,
        seismic_weight: float = 0.25,
        zoning_weight: float = 0.25,
        environmental_weight: float = 0.15,
    ) -> None:
        self.flood_weight = flood_weight
        self.seismic_weight = seismic_weight
        self.zoning_weight = zoning_weight
        self.environmental_weight = environmental_weight

    def assess_parcel_risk(
        self,
        parcel: PropertyParcel,
        flood_zone: Optional[str] = None,
        seismic_zone: Optional[int] = None,
        has_brownfield_proximity: bool = False,
    ) -> GeospatialRiskMetrics:
        """Calculate composite geospatial risk metrics [0-100, where higher is riskier]."""
        # Flood hazard estimation
        flood_score = 10.0
        if flood_zone:
            fz = flood_zone.upper()
            if "A" in fz or "V" in fz:
                flood_score = 85.0
            elif "X500" in fz or "B" in fz:
                flood_score = 45.0
            else:
                flood_score = 15.0

        # Seismic hazard estimation
        seismic_score = 20.0
        if seismic_zone is not None:
            if seismic_zone >= 4:
                seismic_score = 80.0
            elif seismic_zone == 3:
                seismic_score = 50.0
            else:
                seismic_score = 15.0

        # Zoning compliance risk: 0 is completely compliant, 100 is non-compliant
        zoning_score = 10.0
        if parcel.zoning_code.startswith("R-") and parcel.property_type.value in ["office", "industrial"]:
            zoning_score = 90.0  # High zoning variance risk
        elif parcel.zoning_code.startswith("M-") and parcel.property_type.value == "retail":
            zoning_score = 60.0

        # Environmental risk
        env_score = 80.0 if has_brownfield_proximity else 10.0

        composite = (
            flood_score * self.flood_weight
            + seismic_score * self.seismic_weight
            + zoning_score * self.zoning_weight
            + env_score * self.environmental_weight
        )

        return GeospatialRiskMetrics(
            parcel_id=parcel.apn,
            flood_hazard_score=round(flood_score, 2),
            seismic_risk_score=round(seismic_score, 2),
            zoning_compliance_score=round(100.0 - zoning_score, 2),  # Compliance %
            environmental_contamination_risk=round(env_score, 2),
            composite_risk_score=round(composite, 2),
        )
