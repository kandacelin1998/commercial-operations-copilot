from __future__ import annotations

import os
from collections import Counter
from typing import Any

from openai import OpenAI

from src.merchandising import calculate_product_metrics


DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")


def _get_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def _call_responses(prompt: str, model: str | None = None) -> str:
    client = _get_client()
    if client is None:
        raise ValueError("OPENAI_API_KEY is not set. The AI panel requires an OpenAI API key.")

    response = client.responses.create(
        model=model or DEFAULT_MODEL,
        input=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_output_tokens=500,
    )
    if hasattr(response, "output_text") and response.output_text:
        return response.output_text
    if hasattr(response, "output"):
        chunks = []
        for item in response.output:
            if hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        chunks.append(block.text)
        if chunks:
            return "\n".join(chunks)
    return "No AI response was generated."


def demand_analyst(df):
    product_df = calculate_product_metrics(df)
    top = product_df.sort_values(["sell_through_pct", "weekly_units_sold"], ascending=False).iloc[0]
    weakest = product_df.sort_values(["sell_through_pct", "weeks_of_cover"], ascending=[True, False]).iloc[0]
    recommendation = "REORDER" if top["sell_through_pct"] >= 60 else "MONITOR"
    evidence = (
        f"SKU {top['sku']} sold {top['units_sold']} units with a sell-through of {top['sell_through_pct']}% and "
        f"{top['weeks_of_cover']} weeks of cover."
    )
    trade_offs = (
        f"The strongest demand signal is {top['product_name']}, but the weakest demand case is {weakest['product_name']} at "
        f"{weakest['sell_through_pct']}% sell-through and {weakest['weeks_of_cover']} weeks of cover."
    )
    return {
        "agent": "Demand Analyst",
        "recommendation": recommendation,
        "evidence": evidence,
        "trade_offs": trade_offs,
        "summary": "Demand is strongest where sell-through is above 60% and weeks of cover remain low; action reflects that evidence.",
    }


def inventory_analyst(df):
    product_df = calculate_product_metrics(df)
    high_cover = product_df.sort_values("weeks_of_cover", ascending=False).iloc[0]
    low_cover = product_df.sort_values("weeks_of_cover", ascending=True).iloc[0]
    recommendation = "MARKDOWN" if high_cover["sell_through_pct"] < 40 else "REORDER"
    evidence = (
        f"SKU {high_cover['sku']} has {high_cover['weeks_of_cover']} weeks of cover and {high_cover['inventory_value']:.0f} in inventory value, "
        f"while SKU {low_cover['sku']} has {low_cover['weeks_of_cover']} weeks of cover and is the tightest item in stock."
    )
    trade_offs = (
        "The balance is between reducing excess stock and protecting in-demand items from stock-outs; the decision should protect the lowest-cover items."
    )
    return {
        "agent": "Inventory Analyst",
        "recommendation": recommendation,
        "evidence": evidence,
        "trade_offs": trade_offs,
        "summary": "Inventory risk is driven by weeks of cover and inventory value; excess stock should be reduced without exposing slow-turning essentials.",
    }


def pricing_analyst(df):
    product_df = calculate_product_metrics(df)
    best_margin = product_df.sort_values("margin_pct", ascending=False).iloc[0]
    cheapest_margin = product_df.sort_values("margin_pct", ascending=True).iloc[0]
    recommendation = "KEEP FULL PRICE" if best_margin["sell_through_pct"] >= 55 and best_margin["margin_pct"] >= 60 else "MONITOR"
    evidence = (
        f"SKU {best_margin['sku']} holds a margin of {best_margin['margin_pct']}% with sell-through of {best_margin['sell_through_pct']}%, "
        f"while SKU {cheapest_margin['sku']} sits at {cheapest_margin['margin_pct']}% margin."
    )
    trade_offs = (
        "Protecting gross margin is essential, but strong sell-through can justify keeping full price if inventory is not excessive."
    )
    return {
        "agent": "Pricing Analyst",
        "recommendation": recommendation,
        "evidence": evidence,
        "trade_offs": trade_offs,
        "summary": "Pricing actions should support margin and sell-through without unnecessarily discounting strong performers.",
    }


def merchandising_director(product_data, demand_rec, inventory_rec, pricing_rec):
    metrics = calculate_product_metrics(product_data)
    top = metrics.sort_values(["sell_through_pct", "margin_pct"], ascending=False).iloc[0]
    actions = [demand_rec.get("recommendation"), inventory_rec.get("recommendation"), pricing_rec.get("recommendation")]
    counts = Counter(actions)
    main_action = counts.most_common(1)[0][0]

    if top["sell_through_pct"] >= 60 and top["weeks_of_cover"] <= 3:
        action = "REORDER"
        why = "Demand is strong and stock cover is tight, so the business should replenish the fastest-moving lines."
    elif top["sell_through_pct"] < 40 and top["weeks_of_cover"] >= 6:
        action = "MARKDOWN"
        why = "Sales are weak and cover is stretched, so the product needs price intervention to improve velocity."
    elif top["sell_through_pct"] >= 55 and top["margin_pct"] >= 60:
        action = "KEEP FULL PRICE"
        why = "The item is generating healthy sell-through at a strong gross margin, so price protection is the correct call."
    elif top["sell_through_pct"] >= 45 and top["weeks_of_cover"] <= 5:
        action = "MONITOR"
        why = "The SKU is trending well but needs active watch to avoid building inventory exposure."
    else:
        action = "INVESTIGATE"
        why = "The commercial signal is mixed and needs a closer review before cash is committed."

    debate = (
        f"Demand recommends {demand_rec.get('recommendation')}, Inventory recommends {inventory_rec.get('recommendation')}, "
        f"and Pricing recommends {pricing_rec.get('recommendation')}. The Director resolves the disagreement by prioritising the strongest demand signal "
        f"against stock cover and margin risk for {top['product_name']} ({top['sell_through_pct']}% sell-through, {top['weeks_of_cover']} weeks cover, {top['margin_pct']}% margin)."
    )

    return {
        "FINAL DECISION": action,
        "PRODUCT": f"{top['sku']} - {top['product_name']}",
        "ACTION": action,
        "WHY": why,
        "AGENT DEBATE": debate,
        "CONFIDENCE": "High" if counts[main_action] >= 2 else "Medium",
        "RISK": "Low" if action in {"REORDER", "KEEP FULL PRICE"} else "Medium",
    }


def run_merchandising_panel(df):
    """Run the specialist agents and then the director. Returns a structured decision package."""
    if not os.getenv("OPENAI_API_KEY"):
        return {
            "status": "unavailable",
            "message": "The deterministic simulator works without an API key. The AI panel requires OPENAI_API_KEY before specialist analysis can run.",
            "demand_analyst": demand_analyst(df),
            "inventory_analyst": inventory_analyst(df),
            "pricing_analyst": pricing_analyst(df),
        }

    demand = demand_analyst(df)
    inventory = inventory_analyst(df)
    pricing = pricing_analyst(df)
    director = merchandising_director(df, demand, inventory, pricing)
    return {
        "status": "ok",
        "demand_analyst": demand,
        "inventory_analyst": inventory,
        "pricing_analyst": pricing,
        "final_decision": director,
    }
