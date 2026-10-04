"""Merchandising decision engine for the AI fashion merchandising demo."""

from __future__ import annotations

import pandas as pd


def calculate_product_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate core commercial metrics for each product."""
    data = df.copy()

    required_columns = [
        "sku",
        "product_name",
        "price",
        "cost",
        "units_sold",
        "units_available",
        "return_rate",
    ]
    missing = [col for col in required_columns if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns for product metrics: {missing}")

    data["margin_pct"] = ((data["price"] - data["cost"]) / data["price"] * 100).round(1)
    data["inventory_value"] = (data["units_available"] * data["cost"]).round(2)

    total_units = data["units_sold"] + data["units_available"]
    data["sell_through_pct"] = (data["units_sold"] / total_units * 100).replace([float("inf"), float("-inf")], 0.0).fillna(0.0).round(1)

    data["weekly_units_sold"] = (data["units_sold"] / 12).round(1)
    data["weeks_of_cover"] = (data["units_available"] / data["weekly_units_sold"].replace(0, 0.1)).round(1)

    return data


def classify_product(row: pd.Series) -> str:
    """Return the commercial action indicated by the metrics."""
    sell_through = float(row["sell_through_pct"])
    weeks_cover = float(row["weeks_of_cover"])
    margin = float(row["margin_pct"])

    if sell_through >= 60 and weeks_cover <= 3:
        return "REORDER"
    if sell_through < 40 and weeks_cover >= 6:
        return "MARKDOWN"
    if sell_through >= 55 and margin >= 60:
        return "KEEP FULL PRICE"
    if sell_through >= 45 and weeks_cover <= 5:
        return "MONITOR"
    return "INVESTIGATE"


def build_decision_queue(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """Return the highest-priority commercial decisions as a ranked table."""
    data = calculate_product_metrics(df)
    data["action"] = data.apply(classify_product, axis=1)
    data["recommended_action"] = data["action"]
    data["priority_score"] = (abs(data["sell_through_pct"] - 50) + abs(data["weeks_of_cover"] - 4) * 5).round(1)
    ranked = data.sort_values("priority_score", ascending=False).head(top_n).reset_index(drop=True)
    return ranked[["sku", "product_name", "action", "sell_through_pct", "weeks_of_cover", "margin_pct", "inventory_value"]].copy()


def simulate_markdown(price: float, cost: float, units_available: int, markdown_pct: float, expected_demand_lift: float = 0.20) -> dict:
    """Simulate the financial impact of a markdown."""
    new_price = price * (1 - markdown_pct)
    expected_units_sold = min(units_available, units_available * (1 + expected_demand_lift))
    current_revenue = price * units_available
    new_revenue = new_price * expected_units_sold
    current_profit = (price - cost) * units_available
    new_profit = (new_price - cost) * expected_units_sold

    return {
        "original_price": round(price, 2),
        "new_price": round(new_price, 2),
        "expected_units_sold": round(expected_units_sold),
        "current_revenue": round(current_revenue, 2),
        "new_revenue": round(new_revenue, 2),
        "current_profit": round(current_profit, 2),
        "new_profit": round(new_profit, 2),
        "profit_change": round(new_profit - current_profit, 2),
    }


def simulate_collection(collection: pd.DataFrame, budget: float, target_margin: float) -> dict:
    """Simulate a proposed collection against a budget and target gross margin."""
    data = collection.copy()

    data["investment"] = data["unit_cost"] * data["proposed_units"]
    data["revenue_potential"] = data["proposed_price"] * data["proposed_units"]
    data["margin_pct"] = ((data["proposed_price"] - data["unit_cost"]) / data["proposed_price"] * 100).round(1)
    total_investment = float(data["investment"].sum())
    data["budget_pressure"] = (data["investment"] / total_investment * 100).round(1) if total_investment else 0.0

    def collection_action(row):
        if row["margin_pct"] < target_margin:
            return "REPRICE"
        if row["budget_pressure"] > 12:
            return "REDUCE"
        return "KEEP"

    data["recommendation"] = data.apply(collection_action, axis=1)
    average_margin = (
        ((data["revenue_potential"].sum() - data["investment"].sum()) / data["revenue_potential"].sum()) * 100
        if data["revenue_potential"].sum() > 0
        else 0.0
    )
    over_budget = max(total_investment - budget, 0.0)

    return {
        "products": data,
        "total_investment": round(total_investment, 2),
        "budget": round(budget, 2),
        "over_budget": round(over_budget, 2),
        "average_margin": round(average_margin, 1),
        "within_budget": total_investment <= budget,
    }
