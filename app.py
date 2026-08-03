"""
Commercial Operations Copilot
Streamlit application entry point.

This application is a portfolio project. All account data displayed,
uploaded, or bundled with this repository is SYNTHETIC AND FICTIONAL.
No real companies, employees, or business relationships are represented.

Business logic is fully deterministic and defined in docs/BUSINESS_RULES.md.
No external AI API is used anywhere in this application.

Page layout (top to bottom):
    1. KPI Dashboard
    2. Action Queue
    3. Executive Summary
    4. Full Tracker
"""

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from src.workflow_rules import (
    REQUIRED_COLUMNS,
    load_and_validate,
    apply_business_rules,
    build_action_queue,
    compute_kpis,
    generate_executive_summary,
)

DEFAULT_DATA_PATH = Path("data/synthetic_operations_tracker.csv")

st.set_page_config(
    page_title="Commercial Operations Copilot",
    page_icon="📋",
    layout="wide",
)


def load_csv_safely(file_or_path):
    """Read a CSV (path or uploaded file object). Returns (df, error_message)."""
    try:
        df = pd.read_csv(file_or_path)
    except pd.errors.EmptyDataError:
        return None, "This file is empty. Please upload a CSV that contains data."
    except pd.errors.ParserError:
        return None, "This file could not be read as a CSV. Please check the file format."
    except UnicodeDecodeError:
        return None, "This file uses an unsupported text encoding. Please upload a UTF-8 CSV."
    except Exception as exc:  # noqa: BLE001
        return None, f"An unexpected error occurred while reading the file: {exc}"

    if df.empty:
        return None, "This CSV has no rows. Please upload a file that contains account data."

    return df, None


def main():
    st.title("📋 Commercial Operations Copilot")
    st.caption(
        "⚠️ All data shown in this application is synthetic and fictional, "
        "generated for demonstration purposes only. No real companies, "
        "employees, or business relationships are represented."
    )

    uploaded_file = st.file_uploader(
        "Upload a synthetic CSV tracker (optional — the bundled sample loads by default)",
        type=["csv"],
    )

    if uploaded_file is not None:
        df, error = load_csv_safely(uploaded_file)
        source_label = f"Uploaded file: {uploaded_file.name}"
    else:
        if not DEFAULT_DATA_PATH.exists():
            st.error(f"Default dataset not found at `{DEFAULT_DATA_PATH}`. Please upload a CSV to continue.")
            return
        df, error = load_csv_safely(DEFAULT_DATA_PATH)
        source_label = f"Default dataset: {DEFAULT_DATA_PATH}"

    if error:
        st.error(error)
        return

    df, warnings, missing_columns = load_and_validate(df)

    if missing_columns:
        st.error("This CSV is missing required column(s): " + ", ".join(missing_columns))
        with st.expander("Required columns"):
            st.code(", ".join(REQUIRED_COLUMNS), language=None)
        return

    st.success(f"Loaded {len(df)} row(s) — {source_label}")

    if warnings:
        with st.expander(f"⚠️ {len(warnings)} data quality warning(s)"):
            for w in warnings:
                st.warning(w)

    df = apply_business_rules(df)
    kpis = compute_kpis(df)

    # ------------------------------------------------------------------
    # 1. KPI Dashboard
    # ------------------------------------------------------------------
    st.subheader("1. KPI Dashboard")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Accounts", kpis["total_accounts"])
    col2.metric("Approved", kpis["approved"])
    col3.metric("Pending Review", kpis["pending_review"])
    col4.metric("Revision Required", kpis["revision_required"])
    col5.metric("High Risk", kpis["high_risk"])

    st.divider()

    # ------------------------------------------------------------------
    # 2. Action Queue
    # ------------------------------------------------------------------
    st.subheader("2. Action Queue")
    st.caption("Accounts requiring attention, sorted with the highest risk first.")

    full_queue_df = build_action_queue(df)

    if full_queue_df.empty:
        st.info("No accounts currently require follow-up.")
    else:
        queue_display_df = full_queue_df[
            ["account_name", "next_action_owner", "risk_level", "recommended_next_action"]
        ].rename(
            columns={
                "account_name": "Account",
                "next_action_owner": "Owner",
                "risk_level": "Risk",
                "recommended_next_action": "Recommended Action",
            }
        )
        st.dataframe(queue_display_df, use_container_width=True, hide_index=True)

        csv_buffer = io.StringIO()
        queue_display_df.to_csv(csv_buffer, index=False)
        st.download_button(
            "⬇️ Download Action Queue as CSV",
            data=csv_buffer.getvalue(),
            file_name="action_queue.csv",
            mime="text/csv",
        )

    st.divider()

    # ------------------------------------------------------------------
    # 3. Executive Summary
    # ------------------------------------------------------------------
    st.subheader("3. Executive Summary")
    st.caption("Generated entirely from deterministic business rules. No AI model is used.")
    st.text(generate_executive_summary(df, kpis))

    st.divider()

    # ------------------------------------------------------------------
    # 4. Full Tracker
    # ------------------------------------------------------------------
    st.subheader("4. Full Tracker")
    st.caption("Complete account list with calculated status, risk, overdue, and follow-up fields.")
    st.dataframe(df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()