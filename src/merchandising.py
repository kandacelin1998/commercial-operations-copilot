"""
Merchandising Decision Engine

Deterministic calculations used by the AI merchandising agents.
The AI should interpret these metrics rather than invent financial numbers.
"""

from __future__ import annotations

import pandas as pd


def calculate_product_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate core commercial metrics for each product."""

    data = df.copy()

    # Gross margin
    data["margin_pct"] = (
        (data["price"] - data["cost"]) / data["price"] * 100
    ).round(1)

    # Inventory value
    data["inventory_value"] = (
        data["units_available"] * data["cost"]
    ).round(2)

    # Sell-through
    total_units = data["units_sold"] + data["units_available"]

    data["sell_through_pct"] = (
        data["units_sold"] / total_units * 100
    ).round(1)

    # Average weekly sales.
    # We use a simple 12-week estimate for the prototype.
    data["weekly_units_sold"] = (
        data["units_sold"] / 12
    ).round(1)

    # Weeks of cover
    data["weeks_of_cover"] = (
        data["units_available"] /
        data["weekly_units_sold"].replace(0, 0.1)
    ).round(1)

    # Simple commercial health score
    data["commercial_score"] = (
        data["sell_through_pct"] * 0.45
        + data["margin_pct"] * 0.30
        + (100 - data["return_rate"] * 100) * 0.15
        + data["margin_pct"].clip(upper=100) * 0.10
    ).round(1)

    return data


def classify_product(row: pd.Series) -> str:
    """Classify a product into a commercial action."""

    sell_through = row["sell_through_pct"]
    weeks_cover = row["weeks_of_cover"]
    margin = row["margin_pct"]

    # Strong demand + low stock
    if sell_through >= 60 and weeks_cover <= 3:
        return "REORDER"

    # Weak demand + excessive inventory
    if sell_through < 40 and weeks_cover >= 6:
        return "MARKDOWN"

    # Strong commercial performance
    if sell_through >= 55 and margin >= 60:
        return "KEEP FULL PRICE"

    # Healthy but needs monitoring
    if sell_through >= 45 and weeks_cover <= 5:
        return "MONITOR"

    return "INVESTIGATE"


def build_decision_queue(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """Build the highest-priority commercial decisions."""

    data = calculate_product_metrics(df)

    data["recommended_action"] = data.apply(
        classify_product,
        axis=1
    )

    # Priority score:
    # Products with extreme inventory or demand signals rise to the top.
    data["decision_priority"] = (
        abs(data["sell_through_pct"] - 50)
        + abs(data["weeks_of_cover"] - 4) * 5
    ).round(1)

    return (
        data.sort_values(
            "decision_priority",
            ascending=False
        )
        .head(top_n)
        .reset_index(drop=True)
    )


def simulate_markdown(
    price: float,
    cost: float,
    units_available: int,
    markdown_pct: float,
    expected_demand_lift: float = 0.20,
) -> dict:
    """Simulate the financial effect of a markdown."""

    new_price = price * (1 - markdown_pct)

    expected_units_sold = min(
        units_available,
        units_available * (1 + expected_demand_lift)
    )

    current_revenue = price * units_available
    new_revenue = new_price * expected_units_sold

    current_profit = (
        price - cost
    ) * units_available

    new_profit = (
        new_price - cost
    ) * expected_units_sold

    return {
        "original_price": round(price, 2),
        "new_price": round(new_price, 2),
        "expected_units_sold": round(expected_units_sold),
        "current_revenue": round(current_revenue, 2),
        "new_revenue": round(new_revenue, 2),
        "current_profit": round(current_profit, 2),
        "new_profit": round(new_profit, 2),
        "profit_change": round(
            new_profit - current_profit,
            2
        ),
    }


def simulate_collection(
    collection: pd.DataFrame,
    budget: float,
    target_margin: float,
) -> dict:
    """
    Simulate a proposed collection against a budget
    and target gross margin.
    """

    data = collection.copy()

    data["investment"] = (
        data["unit_cost"] * data["proposed_units"]
    )

    data["revenue_potential"] = (
        data["proposed_price"] *
        data["proposed_units"]
    )

    data["margin_pct"] = (
        (
            data["proposed_price"] -
            data["unit_cost"]
        )
        / data["proposed_price"]
        * 100
    )

    total_investment = data["investment"].sum()

    average_margin = (
        (
            data["revenue_potential"].sum()
            - data["investment"].sum()
        )
        / data["revenue_potential"].sum()
        * 100
    )

    # Identify products that create the biggest budget pressure.
    data["budget_pressure"] = (
        data["investment"] / total_investment * 100
    )

    # Initial recommendation
    def collection_action(row):
        if row["margin_pct"] < target_margin:
            return "REPRICE"

        if row["budget_pressure"] > 12:
            return "REDUCE"

        return "KEEP"

    data["recommendation"] = data.apply(
        collection_action,
        axis=1
    )

    if total_investment > budget:
        over_budget = total_investment - budget
    else:
        over_budget = 0

    return {
        "products": data,
        "total_investment": round(total_investment, 2),
        "budget": round(budget, 2),
        "over_budget": round(over_budget, 2),
        "average_margin": round(average_margin, 1),
        "within_budget": total_investment <= budget,
    }
