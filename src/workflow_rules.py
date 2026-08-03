"""
Deterministic business rules for the Commercial Operations Copilot.

This module is the single source of computational logic for the app.
It implements the rules documented in docs/BUSINESS_RULES.md:
    1. Overall status         -> sourced directly from the validated 'review_status' column
    2. Risk level              -> compute_risk_level()
    3. Follow-up required      -> compute_follow_up()
    4. Days overdue            -> compute_days_overdue()
    5. Recommended next action -> compute_next_action()

No AI model, external API, or probabilistic scoring is used anywhere
in this module. Every output can be traced back to specific field values.
All data processed by this module is expected to be synthetic and fictional.

Functions imported by app.py (names must match exactly):
    REQUIRED_COLUMNS, load_and_validate, apply_business_rules,
    build_action_queue, compute_kpis, generate_executive_summary
"""

from datetime import datetime

import pandas as pd

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

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

DATE_COLUMNS = [
    "plan_created",
    "sent_date",
    "received_date",
    "feedback_returned_date",
    "approval_date",
    "due_date",
    "last_updated",
]

YES_NO_COLUMNS = ["plan_sent", "plan_received", "feedback_returned", "final_approval", "blocker"]

VALID_PRIORITY = {"High", "Medium", "Low"}
VALID_REVIEW_STATUS = {
    "Not Started",
    "Waiting for Response",
    "Under Review",
    "Revision Required",
    "Approved",
    "Blocked",
}

RISK_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

DATA_NOTICE_TEXT = "Synthetic portfolio data - no real company information"


# ---------------------------------------------------------------------------
# Validation / normalization
# ---------------------------------------------------------------------------

def load_and_validate(df: pd.DataFrame):
    """
    Validate and normalize an uploaded or default dataframe.

    Returns:
        (validated_df, warnings, missing_columns)
        If missing_columns is non-empty, validated_df is None and the
        caller should stop and display the missing columns to the user.
    """
    warnings = []
    df = df.copy()

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        return None, warnings, missing_columns

    before_count = len(df)
    df = df[df["account_id"].notna() & (df["account_id"].astype(str).str.strip() != "")]
    dropped = before_count - len(df)
    if dropped > 0:
        warnings.append(f"Dropped {dropped} row(s) with a missing account_id.")

    invalid_date_total = 0
    for col in DATE_COLUMNS:
        original_non_null = df[col].notna().sum()
        df[col] = pd.to_datetime(df[col], errors="coerce", format=None)
        new_non_null = df[col].notna().sum()
        invalid_date_total += original_non_null - new_non_null
    if invalid_date_total > 0:
        warnings.append(
            f"{invalid_date_total} date value(s) could not be parsed and were treated as blank. "
            "Expected format is YYYY-MM-DD."
        )

    for col in YES_NO_COLUMNS:
        df[col] = df[col].apply(_normalize_yes_no)

    invalid_priority = ~df["priority"].isin(VALID_PRIORITY)
    if invalid_priority.any():
        count = int(invalid_priority.sum())
        warnings.append(f"{count} row(s) had an unrecognized priority value and were set to 'Unknown'.")
        df.loc[invalid_priority, "priority"] = "Unknown"

    invalid_status = ~df["review_status"].isin(VALID_REVIEW_STATUS)
    if invalid_status.any():
        count = int(invalid_status.sum())
        warnings.append(
            f"{count} row(s) had an unrecognized review_status value and were set to 'Unknown'."
        )
        df.loc[invalid_status, "review_status"] = "Unknown"

    df["data_notice"] = DATA_NOTICE_TEXT

    return df, warnings, []


def _normalize_yes_no(value) -> str:
    if pd.isna(value):
        return "No"
    text = str(value).strip().lower()
    if text in ("yes", "y", "true", "1"):
        return "Yes"
    return "No"


# ---------------------------------------------------------------------------
# Rule calculations (row-level helpers)
# ---------------------------------------------------------------------------

def _days_since(date_value, today: pd.Timestamp):
    if pd.isna(date_value):
        return None
    return (today - date_value).days


def compute_days_overdue(row, today: pd.Timestamp) -> int:
    """Rule 4: Days Overdue. See docs/BUSINESS_RULES.md Rules 4.1 and 4.2."""
    due = row["due_date"]
    if pd.isna(due):
        return 0
    if row["review_status"] == "Approved":
        return 0
    if due < today:
        return int((today - due).days)
    return 0


def compute_risk_level(row, days_overdue: int, today: pd.Timestamp) -> str:
    """Rule 2: Risk Level. See docs/BUSINESS_RULES.md Rules 2.1 - 2.4."""
    status = row["review_status"]
    priority = row["priority"]
    due = row["due_date"]

    if status == "Blocked" or days_overdue > 0:
        return "Critical"

    if status == "Revision Required":
        days_since_review = _days_since(row["received_date"], today)
        feedback_returned = row["feedback_returned"] == "Yes"
        if not feedback_returned and days_since_review is not None and days_since_review > 5:
            return "High"

    if priority == "High" and pd.notna(due):
        days_to_due = (due - today).days
        if 0 <= days_to_due <= 5 and status != "Approved":
            return "High"

    if status == "Waiting for Response":
        days_since_sent = _days_since(row["sent_date"], today)
        if days_since_sent is not None and days_since_sent > 7:
            return "Medium"

    return "Low"


def compute_follow_up(row, days_overdue: int, today: pd.Timestamp):
    """Rule 3: Follow-up required. See docs/BUSINESS_RULES.md Rules 3.1 - 3.4."""
    status = row["review_status"]

    if status == "Blocked":
        return "Yes", "Unresolved blocker"

    if status == "Waiting for Response":
        days_since_sent = _days_since(row["sent_date"], today)
        if days_since_sent is not None and days_since_sent > 7:
            return "Yes", "No response after 7 days"

    if status == "Revision Required":
        days_since_review = _days_since(row["received_date"], today)
        if row["feedback_returned"] != "Yes" and days_since_review is not None and days_since_review > 5:
            return "Yes", "Revision feedback overdue"

    if days_overdue > 0:
        return "Yes", "Due date passed"

    return "No", ""


def compute_next_action(row, days_overdue: int, today: pd.Timestamp) -> str:
    """Rule 5: Recommended Next Action. See docs/BUSINESS_RULES.md Rules 5.1 - 5.7."""
    status = row["review_status"]
    priority = row["priority"]
    due = row["due_date"]

    if status == "Blocked":
        return "Escalate and resolve blocking dependency"

    if days_overdue > 0:
        return "Escalate to account owner - due date passed"

    if priority == "High" and pd.notna(due):
        days_to_due = (due - today).days
        if 0 <= days_to_due <= 5 and status != "Approved":
            return "Expedite review - high-priority due date approaching"

    if status == "Waiting for Response":
        days_since_sent = _days_since(row["sent_date"], today)
        if days_since_sent is not None and days_since_sent > 7:
            return "Send follow-up reminder to account contact"
        return "Monitor for response"

    if status == "Revision Required":
        days_since_review = _days_since(row["received_date"], today)
        if row["feedback_returned"] != "Yes" and days_since_review is not None and days_since_review > 5:
            return "Request updated feedback on revision"
        return "Continue internal review"

    if status == "Under Review":
        return "Proceed with internal approval review"

    if status == "Approved":
        return "No action needed"

    if status == "Not Started":
        return "Initiate quarterly plan"

    return "Review account manually"


# ---------------------------------------------------------------------------
# Dataframe-level application
# ---------------------------------------------------------------------------

def apply_business_rules(df: pd.DataFrame, today: pd.Timestamp = None) -> pd.DataFrame:
    """
    Apply all deterministic rules to every row and return an enriched dataframe
    with the following added columns:
        days_overdue, risk_level, follow_up_required, follow_up_reason,
        recommended_next_action
    """
    if today is None:
        today = pd.Timestamp(datetime.today().date())

    df = df.copy()

    days_overdue_list = []
    risk_level_list = []
    follow_up_list = []
    follow_up_reason_list = []
    next_action_list = []

    for _, row in df.iterrows():
        days_overdue = compute_days_overdue(row, today)
        risk_level = compute_risk_level(row, days_overdue, today)
        follow_up, reason = compute_follow_up(row, days_overdue, today)
        next_action = compute_next_action(row, days_overdue, today)

        days_overdue_list.append(days_overdue)
        risk_level_list.append(risk_level)
        follow_up_list.append(follow_up)
        follow_up_reason_list.append(reason)
        next_action_list.append(next_action)

    df["days_overdue"] = days_overdue_list
    df["risk_level"] = risk_level_list
    df["follow_up_required"] = follow_up_list
    df["follow_up_reason"] = follow_up_reason_list
    df["recommended_next_action"] = next_action_list

    return df


# ---------------------------------------------------------------------------
# KPIs, action queue, executive summary
# ---------------------------------------------------------------------------

def compute_kpis(df: pd.DataFrame) -> dict:
    """Return the five headline KPIs used on the dashboard."""
    total = len(df)
    approved = int((df["review_status"] == "Approved").sum())
    pending_review = int(
        df["review_status"].isin(["Not Started", "Waiting for Response", "Under Review"]).sum()
    )
    revision_required = int((df["review_status"] == "Revision Required").sum())
    high_risk = int(df["risk_level"].isin(["High", "Critical"]).sum())

    return {
        "total_accounts": total,
        "approved": approved,
        "pending_review": pending_review,
        "revision_required": revision_required,
        "high_risk": high_risk,
    }


def build_action_queue(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a prioritized action queue containing accounts that require
    follow-up or carry High/Critical risk, sorted by:
        1. Risk level (Critical > High > Medium > Low)
        2. Days overdue (descending)
        3. Due date (ascending, soonest first)
    """
    queue = df[
        (df["follow_up_required"] == "Yes") | (df["risk_level"].isin(["Critical", "High"]))
    ].copy()

    if queue.empty:
        return queue

    queue["_risk_rank"] = queue["risk_level"].map(RISK_ORDER).fillna(99)
    queue = queue.sort_values(
        by=["_risk_rank", "days_overdue", "due_date"],
        ascending=[True, False, True],
    )
    queue = queue.drop(columns=["_risk_rank"])

    display_cols = [
        "account_id",
        "account_name",
        "account_manager",
        "priority",
        "region",
        "review_status",
        "risk_level",
        "days_overdue",
        "follow_up_required",
        "follow_up_reason",
        "recommended_next_action",
        "next_action_owner",
        "due_date",
        "data_notice",
    ]
    display_cols = [c for c in display_cols if c in queue.columns]
    return queue[display_cols].reset_index(drop=True)


def generate_executive_summary(df: pd.DataFrame, kpis: dict) -> str:
    """
    Generate a concise, factual executive summary built entirely from
    counted values in the dataset. No AI model or external API is used.
    """
    total = kpis["total_accounts"]
    approved = kpis["approved"]
    pending = kpis["pending_review"]
    revision = kpis["revision_required"]

    blocked = int((df["review_status"] == "Blocked").sum())
    critical = int((df["risk_level"] == "Critical").sum())
    high = int((df["risk_level"] == "High").sum())
    medium = int((df["risk_level"] == "Medium").sum())
    low = int((df["risk_level"] == "Low").sum())
    overdue = int((df["days_overdue"] > 0).sum())
    follow_up = int((df["follow_up_required"] == "Yes").sum())

    lines = [
        "SYNTHETIC DATA — for demonstration purposes only.",
        "",
        f"Portfolio: {total} account(s) this planning period — "
        f"{approved} Approved, {pending} Pending Review, {revision} Revision Required, {blocked} Blocked.",
        f"Risk: {critical} Critical, {high} High, {medium} Medium, {low} Low.",
        f"{overdue} account(s) are past due. {follow_up} account(s) require follow-up.",
    ]

    if critical > 0:
        lines.append(f"Priority: address the {critical} Critical-risk account(s) first.")
    elif follow_up == 0:
        lines.append("No accounts currently require follow-up action.")

    return "\n".join(lines)