from __future__ import annotations

from typing import Any

import pandas as pd


def _decision_for_row(row: pd.Series, target_margin: float, budget: float, total_investment: float) -> str:
    margin = float(row.get("margin_pct", 0.0))
    budget_pressure = float(row.get("budget_pressure", 0.0))
    investment = float(row.get("investment", 0.0))

    if margin < target_margin:
        return "REPRICE"
    if total_investment > budget and (budget_pressure >= 8 or investment >= 0.08 * budget):
        return "CUT"
    return "KEEP"


def recommend_collection_actions(collection: pd.DataFrame, budget: float, target_margin: float) -> dict[str, Any]:
    """Return a collection recommendation summary that responds to budget and margin changes."""
    if collection is None or collection.empty:
        return {
            "budget": float(budget),
            "investment": 0.0,
            "average_margin": 0.0,
            "within_budget": True,
            "over_budget": 0.0,
            "target_margin": float(target_margin),
            "recommendations": [],
            "products": pd.DataFrame(),
        }

    data = collection.copy()
    data["investment"] = data["unit_cost"] * data["proposed_units"]
    data["revenue_potential"] = data["proposed_price"] * data["proposed_units"]
    data["margin_pct"] = (((data["proposed_price"] - data["unit_cost"]) / data["proposed_price"]) * 100).round(1)

    total_investment = float(data["investment"].sum())
    if total_investment > 0:
        data["budget_pressure"] = (data["investment"] / total_investment * 100).round(1)
    else:
        data["budget_pressure"] = 0.0

    data["recommendation"] = data.apply(
        lambda row: _decision_for_row(row, float(target_margin), float(budget), total_investment),
        axis=1,
    )

    if total_investment > 0:
        average_margin = (((data["revenue_potential"].sum() - data["investment"].sum()) / data["revenue_potential"].sum()) * 100)
    else:
        average_margin = 0.0

    within_budget = total_investment <= float(budget)
    over_budget = max(total_investment - float(budget), 0.0)
    portfolio_status = (
        "The portfolio is within budget."
        if within_budget
        else f"The portfolio remains £{over_budget:,.0f} over budget."
    )

    recommendations = []
    for _, row in data.iterrows():
        if row["recommendation"] == "CUT":
            reason = (
                f"This product meets the {target_margin}% margin target and was selected for reduction because "
                f"it represents {row['budget_pressure']}% of collection investment. {portfolio_status}"
            )
        elif row["recommendation"] == "REPRICE":
            reason = (
                f"Margin {row['margin_pct']}% is below the {target_margin}% goal, so pricing should be reviewed before purchase. "
                f"{portfolio_status}"
            )
        else:
            reason = (
                f"Margin {row['margin_pct']}% meets the {target_margin}% target and this product does not meet the "
                f"product-level cut threshold. {portfolio_status}"
            )

        recommendations.append(
            {
                "sku": row["sku"],
                "product_name": row["product_name"],
                "action": row["recommendation"],
                "reason": reason,
                "investment": round(float(row["investment"]), 2),
                "margin_pct": round(float(row["margin_pct"]), 1),
            }
        )

    return {
        "budget": float(budget),
        "investment": round(total_investment, 2),
        "average_margin": round(float(average_margin), 1),
        "within_budget": bool(within_budget),
        "over_budget": round(over_budget, 2),
        "target_margin": float(target_margin),
        "recommendations": recommendations,
        "products": data,
    }
