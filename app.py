import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src.agents import run_merchandising_panel
from src.merchandising import build_decision_queue, calculate_product_metrics
from src.simulator import recommend_collection_actions


PRODUCTS_PATH = Path("data/fashion/fashion_products.csv")
PROPOSED_COLLECTION_PATH = Path("data/fashion/proposed_collection.csv")

st.set_page_config(
    page_title="Merchandising Decision Lab",
    page_icon="🧠",
    layout="wide",
)


@st.cache_data
def load_product_data() -> pd.DataFrame:
    return pd.read_csv(PRODUCTS_PATH)


@st.cache_data
def load_collection_data() -> pd.DataFrame:
    return pd.read_csv(PROPOSED_COLLECTION_PATH)


def render_final_decision(decision: dict):
    if not decision:
        st.info("AI final decision is not available yet.")
        return

    st.markdown("### Final Merchandising Decision")
    st.write(f"Product: {decision.get('PRODUCT', 'n/a')}")
    st.write(f"Action: {decision.get('ACTION', 'n/a')}")
    st.write(f"Why: {decision.get('WHY', 'n/a')}")
    st.write(f"Agent Debate: {decision.get('AGENT DEBATE', 'n/a')}")
    st.write(f"Confidence: {decision.get('CONFIDENCE', 'n/a')}")
    st.write(f"Risk: {decision.get('RISK', 'n/a')}")


def main() -> None:
    st.title("🧠 Merchandising Decision Lab")
    st.caption("AI commercial decision system for fashion merchandising")

    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "Deterministic simulator works without an API key. The AI panel requires OPENAI_API_KEY before specialist analysis can run."
        )

    product_df = load_product_data()
    collection_df = load_collection_data()
    product_metrics = calculate_product_metrics(product_df)

    st.subheader("1. Commercial Overview")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Products", len(product_metrics))
    col2.metric("Inventory Value", f"£{product_metrics['inventory_value'].sum():,.0f}")
    col3.metric("Average Margin", f"{product_metrics['margin_pct'].mean():.1f}%")
    col4.metric("Average Sell-through", f"{product_metrics['sell_through_pct'].mean():.1f}%")

    st.divider()

    st.subheader("2. Today's Commercial Decisions")
    decisions = build_decision_queue(product_metrics, top_n=5)
    decisions_display = decisions[
        ["sku", "product_name", "action", "sell_through_pct", "weeks_of_cover", "margin_pct", "inventory_value"]
    ].rename(
        columns={
            "sku": "SKU",
            "product_name": "Product",
            "action": "Action",
            "sell_through_pct": "Sell-through",
            "weeks_of_cover": "Weeks of Cover",
            "margin_pct": "Margin",
            "inventory_value": "Inventory Value",
        }
    )
    st.dataframe(decisions_display, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("3. Collection Simulator")
    budget = st.slider("Collection Budget", min_value=300000, max_value=700000, value=500000, step=25000)
    target_margin = st.slider("Target Gross Margin", min_value=50, max_value=75, value=68, step=1)

    collection_result = recommend_collection_actions(collection_df, budget, target_margin)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Collection Investment", f"£{collection_result['investment']:,.0f}")
    col2.metric("Budget", f"£{collection_result['budget']:,.0f}")
    col3.metric("Average Margin", f"{collection_result['average_margin']:.1f}%")
    col4.metric("Budget Status", "Within Budget" if collection_result["within_budget"] else "Over Budget")

    recommendations = pd.DataFrame(collection_result["recommendations"])
    if not recommendations.empty:
        st.dataframe(
            recommendations[["sku", "product_name", "action", "margin_pct", "investment"]].rename(
                columns={
                    "sku": "SKU",
                    "product_name": "Product",
                    "action": "Recommendation",
                    "margin_pct": "Margin%",
                    "investment": "Investment",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    st.subheader("4. AI Merchandising Panel")
    st.caption(
        "Demand, Inventory and Pricing agents analyse the commercial data independently. A Merchandising Director resolves the trade-offs."
    )

    if st.button("Run AI Merchandising Panel"):
        if not os.getenv("OPENAI_API_KEY"):
            st.warning(
                "The deterministic simulator works without an API key. The AI panel requires OPENAI_API_KEY to call the OpenAI Responses API."
            )
        else:
            result = run_merchandising_panel(product_metrics)
            st.session_state["ai_results"] = result
            st.success("AI panel completed.")

    if "ai_results" in st.session_state:
        result = st.session_state["ai_results"]
        if result.get("status") == "ok":
            render_final_decision(result.get("final_decision", {}))

            for label in ["Demand Analyst", "Inventory Analyst", "Pricing Analyst"]:
                with st.expander(label):
                    key = label.lower().replace(" ", "_")
                    payload = result.get(f"{key}", {})
                    st.write(payload.get("agent", label))
                    st.write(f"Recommendation: {payload.get('recommendation', 'n/a')}")
                    st.write(f"Evidence: {payload.get('evidence', 'n/a')}")
                    st.write(f"Trade-offs: {payload.get('trade_offs', 'n/a')}")
                    st.write(f"Summary: {payload.get('summary', 'n/a')}")
        else:
            st.warning(result.get("message", "AI panel unavailable."))
    else:
        st.info("The AI panel has not run yet. Use the button to generate the commercial recommendation.")

    st.divider()

    with st.expander("Underlying Product Data"):
        st.dataframe(product_metrics, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()