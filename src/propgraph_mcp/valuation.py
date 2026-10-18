"""Discounted Cash Flow (DCF) valuation and multi-scenario underwriting engine."""

from __future__ import annotations

from typing import Dict, List, Optional

from propgraph_mcp.types import CashFlowYear, DCFScenario, ValuationOutput


def calculate_irr(cash_flows: List[float], guess: float = 0.1, max_iter: int = 100, tol: float = 1e-6) -> float:
    """Compute Internal Rate of Return using Newton-Raphson approximation."""
    rate = guess
    for _ in range(max_iter):
        npv = sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cash_flows))
        d_npv = sum(-t * cf / ((1.0 + rate) ** (t + 1)) for t, cf in enumerate(cash_flows))

        if abs(d_npv) < 1e-12:
            break

        new_rate = rate - npv / d_npv
        if abs(new_rate - rate) < tol:
            return float(new_rate)
        rate = new_rate
    return float(rate)


class DCFValuationEngine:
    """Computes projected cash flows, terminal capitalization, NPV, and IRR."""

    def __init__(self, default_scenarios: Optional[Dict[str, DCFScenario]] = None) -> None:
        if default_scenarios is not None:
            self.scenarios = default_scenarios
        else:
            self.scenarios = {
                "Base": DCFScenario(
                    scenario_name="Base",
                    discount_rate=0.08,
                    exit_cap_rate=0.065,
                    holding_period_years=5,
                    rent_growth_rate=0.03,
                    expense_growth_rate=0.025,
                    vacancy_rate=0.05,
                ),
                "Bull": DCFScenario(
                    scenario_name="Bull",
                    discount_rate=0.07,
                    exit_cap_rate=0.055,
                    holding_period_years=5,
                    rent_growth_rate=0.05,
                    expense_growth_rate=0.02,
                    vacancy_rate=0.03,
                ),
                "Bear": DCFScenario(
                    scenario_name="Bear",
                    discount_rate=0.10,
                    exit_cap_rate=0.08,
                    holding_period_years=5,
                    rent_growth_rate=0.01,
                    expense_growth_rate=0.04,
                    vacancy_rate=0.10,
                ),
            }

    def run_scenario(
        self,
        property_id: str,
        initial_gross_revenue: float,
        initial_operating_expenses: float,
        purchase_price: float,
        scenario: DCFScenario,
        debt_service_annual: float = 0.0,
    ) -> ValuationOutput:
        """Run single DCF projection for a specific scenario."""
        cash_flows: List[CashFlowYear] = []
        annual_cfs_for_irr: List[float] = [-purchase_price]

        rev = initial_gross_revenue
        exp = initial_operating_expenses

        for t in range(1, scenario.holding_period_years + 1):
            rev *= (1.0 + scenario.rent_growth_rate)
            effective_gross_income = rev * (1.0 - scenario.vacancy_rate)
            exp *= (1.0 + scenario.expense_growth_rate)
            noi = effective_gross_income - exp
            net_cf = noi - debt_service_annual

            cash_flows.append(
                CashFlowYear(
                    year=t,
                    gross_revenue=round(rev, 2),
                    operating_expenses=round(exp, 2),
                    net_operating_income=round(noi, 2),
                    debt_service=round(debt_service_annual, 2),
                    net_cash_flow=round(net_cf, 2),
                )
            )
            annual_cfs_for_irr.append(net_cf)

        # Terminal Year NOI for Exit Cap Rate
        next_year_noi = (
            rev * (1.0 + scenario.rent_growth_rate) * (1.0 - scenario.vacancy_rate)
            - exp * (1.0 + scenario.expense_growth_rate)
        )
        terminal_value = next_year_noi / scenario.exit_cap_rate
        annual_cfs_for_irr[-1] += terminal_value

        # NPV calculation
        npv = sum(
            cf / ((1.0 + scenario.discount_rate) ** t)
            for t, cf in enumerate(annual_cfs_for_irr)
        )

        # IRR calculation
        irr = calculate_irr(annual_cfs_for_irr)

        total_net_cf = sum(cf.net_cash_flow for cf in cash_flows) + terminal_value

        return ValuationOutput(
            property_id=property_id,
            scenario_name=scenario.scenario_name,
            purchase_price=purchase_price,
            npv=round(npv, 2),
            irr=round(irr, 4),
            terminal_value=round(terminal_value, 2),
            cash_flows=cash_flows,
            total_net_cash_flow=round(total_net_cf, 2),
        )

    def run_all_scenarios(
        self,
        property_id: str,
        initial_gross_revenue: float,
        initial_operating_expenses: float,
        purchase_price: float,
        debt_service_annual: float = 0.0,
    ) -> Dict[str, ValuationOutput]:
        """Underwrite across all defined scenarios (Base, Bull, Bear)."""
        outputs = {}
        for name, scenario in self.scenarios.items():
            outputs[name] = self.run_scenario(
                property_id=property_id,
                initial_gross_revenue=initial_gross_revenue,
                initial_operating_expenses=initial_operating_expenses,
                purchase_price=purchase_price,
                scenario=scenario,
                debt_service_annual=debt_service_annual,
            )
        return outputs
