"""Discounted Cash Flow (DCF) valuation and multi-scenario underwriting engine."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from propgraph_mcp.types import CashFlowYear, DCFScenario, ValuationOutput


def calculate_irr(cash_flows: List[float], guess: float = 0.1, max_iter: int = 100, tol: float = 1e-6) -> float:
    """Compute Internal Rate of Return using Newton-Raphson approximation with bisection fallback."""
    if not cash_flows or all(cf >= 0 for cf in cash_flows) or all(cf <= 0 for cf in cash_flows):
        return 0.0

    def npv_func(r: float) -> float:
        return sum(cf / ((1.0 + r) ** t) for t, cf in enumerate(cash_flows))

    def d_npv_func(r: float) -> float:
        return sum(-t * cf / ((1.0 + r) ** (t + 1)) for t, cf in enumerate(cash_flows))

    # Phase 1: Newton-Raphson
    rate = guess
    for _ in range(max_iter):
        npv = npv_func(rate)
        if abs(npv) < tol:
            return float(rate)

        d_npv = d_npv_func(rate)
        if abs(d_npv) < 1e-12:
            break

        new_rate = rate - npv / d_npv
        if new_rate <= -0.999:  # Prevent divergent negative roots
            break

        if abs(new_rate - rate) < tol:
            return float(new_rate)
        rate = new_rate

    # Phase 2: Bisection Fallback on [-0.95, 10.0]
    low, high = -0.95, 10.0
    f_low, f_high = npv_func(low), npv_func(high)

    if f_low * f_high <= 0:
        for _ in range(max_iter):
            mid = (low + high) / 2.0
            f_mid = npv_func(mid)
            if abs(f_mid) < tol or (high - low) / 2.0 < tol:
                return float(mid)
            if f_low * f_mid <= 0:
                high = mid
                f_high = f_mid
            else:
                low = mid
                f_low = f_mid
        return float((low + high) / 2.0)

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

    def calculate_sensitivity_table(
        self,
        property_id: str,
        initial_gross_revenue: float,
        initial_operating_expenses: float,
        purchase_price: float,
        discount_rates: Optional[List[float]] = None,
        exit_cap_rates: Optional[List[float]] = None,
        holding_period_years: int = 5,
        debt_service_annual: float = 0.0,
    ) -> Dict[str, Any]:
        """Compute 2D sensitivity matrix of NPV and IRR across discount rates and exit cap rates."""
        d_rates = discount_rates or [0.07, 0.08, 0.09, 0.10]
        c_rates = exit_cap_rates or [0.055, 0.060, 0.065, 0.070, 0.075]

        npv_grid: Dict[str, Dict[str, float]] = {}
        irr_grid: Dict[str, Dict[str, float]] = {}

        for dr in d_rates:
            dr_key = f"{round(dr * 100, 2)}%"
            npv_grid[dr_key] = {}
            irr_grid[dr_key] = {}
            for cr in c_rates:
                cr_key = f"{round(cr * 100, 2)}%"
                scenario = DCFScenario(
                    scenario_name=f"Sens_{dr_key}_{cr_key}",
                    discount_rate=dr,
                    exit_cap_rate=cr,
                    holding_period_years=holding_period_years,
                )
                output = self.run_scenario(
                    property_id=property_id,
                    initial_gross_revenue=initial_gross_revenue,
                    initial_operating_expenses=initial_operating_expenses,
                    purchase_price=purchase_price,
                    scenario=scenario,
                    debt_service_annual=debt_service_annual,
                )
                npv_grid[dr_key][cr_key] = output.npv
                irr_grid[dr_key][cr_key] = output.irr

        return {
            "property_id": property_id,
            "purchase_price": purchase_price,
            "discount_rates": d_rates,
            "exit_cap_rates": c_rates,
            "npv_matrix": npv_grid,
            "irr_matrix": irr_grid,
        }

    def calculate_debt_metrics(
        self,
        purchase_price: float,
        net_operating_income_y1: float,
        loan_amount: float,
        annual_debt_service: float,
    ) -> Dict[str, Any]:
        """Compute key commercial real estate debt and leverage underwriting metrics."""
        ltv = round(loan_amount / purchase_price, 4) if purchase_price > 0 else 0.0
        dscr = (
            round(net_operating_income_y1 / annual_debt_service, 2)
            if annual_debt_service > 0
            else 0.0
        )
        debt_yield = (
            round(net_operating_income_y1 / loan_amount, 4) if loan_amount > 0 else 0.0
        )
        compliant = bool(dscr >= 1.25 and ltv <= 0.75)

        return {
            "loan_amount": loan_amount,
            "purchase_price": purchase_price,
            "loan_to_value": ltv,
            "debt_service_coverage_ratio": dscr,
            "debt_yield": debt_yield,
            "is_covenant_compliant": compliant,
            "min_required_dscr": 1.25,
            "max_allowable_ltv": 0.75,
        }

    def calculate_equity_multiple(
        self,
        purchase_price: float,
        loan_amount: float,
        cash_flows: List[CashFlowYear],
        terminal_value: float,
        remaining_loan_balance: float = 0.0,
    ) -> float:
        """Compute equity multiple (total net distributions / initial equity invested)."""
        initial_equity = purchase_price - loan_amount
        if initial_equity <= 0:
            return 0.0

        net_terminal_proceeds = max(0.0, terminal_value - remaining_loan_balance)
        total_cash_distributed = (
            sum(cf.net_cash_flow for cf in cash_flows) + net_terminal_proceeds
        )
        return round(total_cash_distributed / initial_equity, 3)

    def calculate_breakeven_occupancy(
        self,
        gross_revenue: float,
        operating_expenses: float,
        annual_debt_service: float = 0.0,
    ) -> float:
        """Calculate break-even occupancy percentage required to service OpEx and debt."""
        if gross_revenue <= 0:
            return 1.0
        return round((operating_expenses + annual_debt_service) / gross_revenue, 4)
