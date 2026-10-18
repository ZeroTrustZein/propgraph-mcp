"""Geospatial, climate, and zoning compliance risk assessment engine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
        distances_to_superfund_miles: Optional[List[float]] = None,
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
        if distances_to_superfund_miles is not None:
            env_score = self.calculate_environmental_proximity_score(distances_to_superfund_miles)
        else:
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

    def calculate_environmental_proximity_score(
        self, distances_to_superfund_miles: List[float]
    ) -> float:
        """Compute proximity decay hazard score based on distances to toxic/CERCLA sites."""
        if not distances_to_superfund_miles:
            return 0.0

        closest = min(distances_to_superfund_miles)
        if closest < 0.25:
            score = 95.0
        elif closest < 0.5:
            score = 75.0
        elif closest < 1.0:
            score = 45.0
        elif closest < 2.0:
            score = 20.0
        else:
            score = 5.0
        return round(score, 2)

    def evaluate_zoning_capacity(
        self,
        parcel: PropertyParcel,
        proposed_gross_floor_area: Optional[float] = None,
        proposed_height: Optional[float] = None,
        lot_area_sqft: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluate architectural capacity against municipal zoning FAR and height constraints."""
        lot_area = lot_area_sqft if lot_area_sqft and lot_area_sqft > 0 else parcel.square_feet * 0.5
        current_far = round(parcel.square_feet / lot_area, 2)

        code = parcel.zoning_code.upper()
        if code.startswith("C-3"):
            max_far = 9.0
            max_height = 250.0
        elif code.startswith("C-2"):
            max_far = 4.0
            max_height = 85.0
        elif code.startswith("C-1"):
            max_far = 2.0
            max_height = 45.0
        elif code.startswith("M-"):
            max_far = 2.5
            max_height = 65.0
        elif code.startswith("R-3"):
            max_far = 2.0
            max_height = 55.0
        elif code.startswith("R-1"):
            max_far = 0.6
            max_height = 35.0
        else:
            max_far = 2.5
            max_height = 50.0

        far_compliant = True
        proposed_far = None
        if proposed_gross_floor_area is not None:
            proposed_far = round(proposed_gross_floor_area / lot_area, 2)
            far_compliant = proposed_far <= max_far

        height_compliant = True
        if proposed_height is not None:
            height_compliant = proposed_height <= max_height

        variance_required = not (far_compliant and height_compliant)
        entitlement_risk = "high" if variance_required else "low"

        return {
            "parcel_id": parcel.apn,
            "zoning_code": parcel.zoning_code,
            "lot_area_sqft": lot_area,
            "current_far": current_far,
            "max_permissible_far": max_far,
            "proposed_far": proposed_far,
            "far_compliant": far_compliant,
            "max_height_ft": max_height,
            "proposed_height_ft": proposed_height,
            "height_compliant": height_compliant,
            "variance_required": variance_required,
            "entitlement_risk": entitlement_risk,
        }

    def project_climate_risk(
        self,
        parcel: PropertyParcel,
        horizon_years: int = 30,
    ) -> Dict[str, Any]:
        """Model compound 10-30 year climate risk escalation and insurance premium impact."""
        state = parcel.state.upper()
        # Coastal / hurricane / high-exposure states
        coastal_high_risk = state in ["FL", "LA", "TX", "MS", "AL", "SC", "NC"]
        baseline_climate = 65.0 if coastal_high_risk else 25.0

        # Latitudinal adjustments
        if parcel.latitude and parcel.latitude < 32.0:
            baseline_climate += 10.0

        annual_escalation_pct = 0.025 if coastal_high_risk else 0.012

        projections = {}
        for y in [10, 20, 30]:
            if y <= horizon_years:
                proj_score = min(100.0, round(baseline_climate * ((1.0 + annual_escalation_pct) ** y), 2))
                projections[f"year_{y}"] = proj_score

        # Insurance premium inflation multiplier over the period
        insurance_multiplier = round((1.0 + annual_escalation_pct * 1.5) ** horizon_years, 3)

        return {
            "parcel_id": parcel.apn,
            "state": parcel.state,
            "baseline_climate_score": round(baseline_climate, 2),
            "projected_scores": projections,
            "estimated_insurance_premium_multiplier": insurance_multiplier,
            "underwriting_advisory": (
                "High climate exposure: model 15-25% annual insurance OpEx reserves."
                if coastal_high_risk
                else "Standard climate exposure: conventional insurance coverage adequate."
            ),
        }
