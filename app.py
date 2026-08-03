"""
Commercial Operations Copilot
Feature 1: Upload a CSV, validate required columns, display the table.

This is an intentionally minimal version of the app. No risk/overdue/
follow-up calculations happen here, and there is no dashboard yet.
All data is synthetic and fictional.
"""

import pandas as pd
import streamlit as st

REQUIRED_COLUMNS = [
    "account_id",
    "account_name",
    "account_manager",
    "priority",
    "region",
    "planning_period",
    "plan_created",
    "plan_sent",
    "sent_date",
    "plan_received",
    "received_date",
    "review_status",
    "feedback_returned",
    "feedback_returned_date",
    "final_approval",
    "approval_date",
    "next_action",
    "next_action_owner",
    "due_date",
    "blocker",
    "last_updated",
    "data_notice",
]

st.set_page_config(page_title="Commercial Operations Copilot", page_icon="📋")

st.title("📋 Commercial Operations Copilot")
st.caption(
    "⚠️ All data shown in this application is synthetic and fictional, "
    "used for demonstration purposes only."
)

uploaded_file = st.file_uploader("Upload a CSV tracker", type=["csv"])

if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file)
    except pd.errors.EmptyDataError:
        st.error("This file is empty. Please upload a CSV that contains data.")
        st.stop()
    except pd.errors.ParserError:
        st.error("This file could not be read as a CSV. Please check the file format.")
        st.stop()
    except UnicodeDecodeError:
        st.error("This file uses an unsupported text encoding. Please upload a UTF-8 CSV.")
        st.stop()

    if df.empty:
        st.error("This CSV has no rows. Please upload a file that contains account data.")
        st.stop()

    missing_columns = [col for col in REQUIRED_COLUMNS if col not in df.columns]

    if missing_columns:
        st.error(
            "This CSV is missing required column(s): "
            + ", ".join(missing_columns)
        )
        st.stop()

    st.success(f"File loaded successfully — {len(df)} row(s) found.")
    st.dataframe(df, use_container_width=True, hide_index=True)

else:
    st.info("Upload a CSV file to get started.")