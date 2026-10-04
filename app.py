import os
from pathlib import Path

import pandas as pd
import streamlit as st
from openai import OpenAIError

from src.agents import AgentError, run_merchandising_panel
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

    with st.container(border=True):
        st.subheader("Director decision")
        st.metric("FINAL ACTION", decision["final_action"])
        st.markdown(f"**PRODUCT**  \n{decision['sku']} — {decision['product_name']}")

        why = decision["why"]
        st.markdown(f"**WHY THIS ACTION WINS**  \n{why['explanation']}")
        st.caption(
            "Decision evidence: "
            + ", ".join(f"{item['field']} = {item['value']:g}" for item in why["evidence"])
        )

        debate = decision["agent_debate"]
        st.markdown("**AGENT DEBATE**")
        for agent, recommendation in debate["recommendations"].items():
            st.markdown(f"- {agent}: **{recommendation}**")
        if debate["disagreement"]:
            st.markdown(f"**Disagreement resolved:** {debate['resolution']}")
        else:
            st.markdown(f"**Resolution:** {debate['resolution']}")

        confidence_col, risk_col = st.columns(2)
        confidence_col.markdown(f"**CONFIDENCE**  \n{decision['confidence']}")
        risk = decision["risk"]
        risk_col.markdown(f"**RISK — {risk['level']}**  \n{risk['explanation']}")
        st.caption(
            "Risk evidence: "
            + ", ".join(f"{item['field']} = {item['value']:g}" for item in risk["evidence"])
        )


def main() -> None:
    st.title("🧠 Merchandising Decision Lab")
    st.caption("AI commercial decision system for fashion merchandising")

    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "The deterministic simulator works without an API key. The AI Merchandising Panel requires OPENAI_API_KEY."
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
    st.dataframe(decisions_display, width="stretch", hide_index=True)

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
            width="stretch",
            hide_index=True,
        )

    st.divider()

    st.subheader("4. AI Merchandising Panel")
    st.caption(
        "Demand, Inventory and Pricing agents analyse the commercial data independently. A Merchandising Director resolves the trade-offs."
    )
    st.caption(
        "Python calculates deterministic metrics; AI specialists interpret that evidence and the Director resolves their trade-offs."
    )

    if st.button("Run AI Merchandising Panel"):
        st.session_state.pop("ai_results", None)
        if not os.getenv("OPENAI_API_KEY"):
            st.warning(
                "The deterministic simulator works without an API key. The AI Merchandising Panel requires OPENAI_API_KEY."
            )
        else:
            try:
                with st.spinner("Running three specialists and the Merchandising Director..."):
                    result = run_merchandising_panel(product_metrics)
            except (AgentError, OpenAIError) as error:
                st.error(f"AI Merchandising Panel failed: {error}")
            else:
                st.session_state["ai_results"] = result
                st.success("AI specialist analysis and Director decision completed.")

    if "ai_results" in st.session_state:
        result = st.session_state["ai_results"]
        if result.get("status") == "ok":
            st.markdown("#### Director decision")
            render_final_decision(result.get("final_decision", {}))

            st.markdown("#### AI specialist analysis")
            for label in ["Demand Analyst", "Inventory Analyst", "Pricing Analyst"]:
                with st.expander(label):
                    key = label.lower().replace(" ", "_")
                    payload = result.get(f"{key}", {})
                    st.markdown(f"**RECOMMENDATION:** {payload['recommendation']}")
                    st.markdown(f"**PRODUCT:** {payload['sku']} — {payload['product_name']}")
                    st.markdown(
                        "**TOP EVIDENCE:** "
                        + ", ".join(
                            f"{item['field']} = {item['value']:g}" for item in payload["evidence"]
                        )
                    )
                    st.markdown(f"**TRADE-OFF:** {payload['trade_off']}")
                    st.markdown(f"**CONFIDENCE:** {payload['confidence']}")
        else:
            st.warning(result.get("message", "AI panel unavailable."))
    else:
        st.info("The AI panel has not run yet. Use the button to generate the commercial recommendation.")

    st.divider()

    with st.expander("Underlying Product Data"):
        st.dataframe(product_metrics, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
