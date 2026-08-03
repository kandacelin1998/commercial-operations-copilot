"""
Deterministic business rules for the Commercial Operations Copilot.

This module implements the rule engine for the publisher-tracker schema:
    Overall Status  -> compute_overall_status()   (7 categories)
    Days Overdue     -> compute_days_overdue()
    Follow-up needed -> compute_follow_up()
    Recommended action -> compute_next_action()

No AI model, external API, or probabilistic scoring is used anywhere
in this module. Every output can be traced back to specific field values.
All data processed by this module is expected to be synthetic and fictional.
"""

from datetime import datetime

import pandas as pd

# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "Publisher",
    "Account Manager",
    "Priority",
    "Calendar Period",
    "Calendar Created?",
    "Calendar Owner",
    "Plan Ownership",
    "Plan Sent?",
    "Sent Date",
    "Plan Received?",
    "Received Date",
    "Review Status",
    "Feedback Returned Date",
    "Uploaded to Tracking Tool?",
    "Tracking Tool Upload Date",
    "Tracking Tool Status",
    "Blocker?",
    "Due Date",
    "Notes",
    "Data Notice",
]

DATE_COLUMNS = [
    "Sent Date",
    "Received Date",
    "Feedback Returned Date",
    "Tracking Tool Upload Date",
    "Due Date",
]

YES_NO_COLUMNS = ["Calendar Created?", "Uploaded to Tracking Tool?", "Blocker?"]

VALID_PRIORITY = {"High", "Medium", "Low"}
VALID_REVIEW_STATUS = {"Not Started", "Pending Review", "In Review", "Revision Requested", "Approved", "Blocked"}
VALID_SENT = {"Sent", "Not Sent"}
VALID_RECEIVED = {"Received", "Not Received"}

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}

DATA_NOTICE_TEXT = "Synthetic portfolio data - no real company information"

COMPLETE_TOOL_STATUSES = {"live", "complete", "pushed"}


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

    # Drop rows without a Publisher name — cannot be tracked meaningfully
    before_count = len(df)
    df = df[df["Publisher"].notna() & (df["Publisher"].astype(str).str.strip() != "")]
    dropped = before_count - len(df)
    if dropped > 0:
        warnings.append(f"Dropped {dropped} row(s) with a missing Publisher name.")

    # Coerce date columns
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

    # Normalize simple Yes/No fields
    for col in YES_NO_COLUMNS:
        df[col] = df[col].apply(_normalize_yes_no)

    # Normalize Plan Sent? / Plan Received?
    df["Plan Sent?"] = df["Plan Sent?"].apply(lambda v: _normalize_choice(v, "Sent", "Not Sent"))
    df["Plan Received?"] = df["Plan Received?"].apply(lambda v: _normalize_choice(v, "Received", "Not Received"))

    # Normalize Priority
    invalid_priority = ~df["Priority"].isin(VALID_PRIORITY)
    if invalid_priority.any():
        count = int(invalid_priority.sum())
        warnings.append(f"{count} row(s) had an unrecognized Priority value and were set to 'Unknown'.")
        df.loc[invalid_priority, "Priority"] = "Unknown"

    # Normalize Review Status
    invalid_status = ~df["Review Status"].isin(VALID_REVIEW_STATUS)
    if invalid_status.any():
        count = int(invalid_status.sum())
        warnings.append(f"{count} row(s) had an unrecognized Review Status value and were set to 'Unknown'.")
        df.loc[invalid_status, "Review Status"] = "Unknown"

    # Enforce the synthetic data notice regardless of source file content
    df["Data Notice"] = DATA_NOTICE_TEXT

    return df, warnings, []


def _normalize_yes_no(value) -> str:
    if pd.isna(value):
        return "No"
    text = str(value).strip().lower()
    if text in ("yes", "y", "true", "1"):
        return "Yes"
    return "No"


def _normalize_choice(value, true_label: str, false_label: str) -> str:
    if pd.isna(value):
        return false_label
    text = str(value).strip().lower()
    if text == true_label.lower():
        return true_label
    return false_label


# ---------------------------------------------------------------------------
# Rule calculations (row-level helpers)
# ---------------------------------------------------------------------------

def _days_since(date_value, today: pd.Timestamp):
    if pd.isna(date_value):
        return None
    return (today - date_value).days


def compute_overall_status(row) -> str:
    """
    Overall Status (7 categories), computed from raw fields:
        Not Started, Waiting for External Response, Internal Review,
        Revision Required, Approved, Blocked, Complete
    """
    review_status = row["Review Status"]
    plan_sent = row["Plan Sent?"]
    plan_received = row["Plan Received?"]
    blocker = row["Blocker?"]
    tool_status = str(row["Tracking Tool Status"]).strip().lower() if pd.notna(row["Tracking Tool Status"]) else ""

    # Complete: approved AND fully pushed to the tracking tool
    if review_status == "Approved" and tool_status in COMPLETE_TOOL_STATUSES:
        return "Complete"

    # Blocked: an unresolved dependency overrides other states
    if blocker == "Yes":
        return "Blocked"

    # Revision Required: plan was reviewed and sent back for changes
    if review_status == "Revision Requested":
        return "Revision Required"

    # Waiting for External Response: sent to publisher, no reply yet
    if plan_sent == "Sent" and plan_received == "Not Received":
        return "Waiting for External Response"

    # Internal Review: received and being reviewed internally
    if plan_received == "Received" and review_status in ("Pending Review", "In Review"):
        return "Internal Review"

    # Approved (interim): approved but not yet pushed to the tool
    if review_status == "Approved":
        return "Approved"

    # Fallback: nothing has been sent yet
    return "Not Started"


def compute_days_overdue(row, overall_status: str, today: pd.Timestamp) -> int:
    """Days Overdue: 0 unless the due date has passed and the item isn't Complete."""
    due = row["Due Date"]
    if pd.isna(due):
        return 0
    if overall_status == "Complete":
        return 0
    if due < today:
        return int((today - due).days)
    return 0


def compute_follow_up(row, overall_status: str, days_overdue: int, today: pd.Timestamp):
    """Follow-up required: Yes/No plus a short reason."""
    if overall_status == "Blocked":
        return "Yes", "Unresolved blocker"

    if overall_status == "Waiting for External Response":
        days_since_sent = _days_since(row["Sent Date"], today)
        if days_since_sent is not None and days_since_sent > 7:
            return "Yes", "No response after 7 days"

    if overall_status == "Revision Required":
        days_since_review = _days_since(row["Received Date"], today)
        feedback_returned = pd.notna(row["Feedback Returned Date"])
        if not feedback_returned and days_since_review is not None and days_since_review > 5:
            return "Yes", "Revision feedback overdue"

    if days_overdue > 0:
        return "Yes", "Due date passed"

    return "No", ""


def compute_next_action(row, overall_status: str, days_overdue: int, today: pd.Timestamp) -> str:
    """Recommended next action, based on Overall Status, Priority, and due date."""
    priority = row["Priority"]
    due = row["Due Date"]

    if overall_status == "Blocked":
        return "Escalate and resolve blocking dependency"

    if days_overdue > 0:
        return "Escalate to publisher contact - due date passed"

    if priority == "High" and pd.notna(due):
        days_to_due = (due - today).days
        if 0 <= days_to_due <= 5 and overall_status not in ("Approved", "Complete"):
            return "Expedite review - high-priority due date approaching"

    if overall_status == "Waiting for External Response":
        days_since_sent = _days_since(row["Sent Date"], today)
        if days_since_sent is not None and days_since_sent > 7:
            return "Send follow-up reminder to publisher contact"
        return "Monitor for response"

    if overall_status == "Revision Required":
        days_since_review = _days_since(row["Received Date"], today)
        feedback_returned = pd.notna(row["Feedback Returned Date"])
        if not feedback_returned and days_since_review is not None and days_since_review > 5:
            return "Request updated feedback on revision"
        return "Continue internal review"

    if overall_status == "Internal Review":
        return "Proceed with internal approval review"

    if overall_status == "Approved":
        return "Upload to tracking tool and finalize"

    if overall_status == "Complete":
        return "No action needed"

    if overall_status == "Not Started":
        return "Send calendar and initiate quarterly plan"

    return "Review publisher manually"


# ---------------------------------------------------------------------------
# Dataframe-level application
# ---------------------------------------------------------------------------

def apply_business_rules(df: pd.DataFrame, today: pd.Timestamp = None) -> pd.DataFrame:
    """
    Apply all deterministic rules to every row and return an enriched dataframe
    with the following added columns:
        Overall Status, Days Overdue, Follow-Up Required, Follow-Up Reason,
        Recommended Next Action
    """
    if today is None:
        today = pd.Timestamp(datetime.today().date())

    df = df.copy()

    overall_status_list = []
    days_overdue_list = []
    follow_up_list = []
    follow_up_reason_list = []
    next_action_list = []

    for _, row in df.iterrows():
        overall_status = compute_overall_status(row)
        days_overdue = compute_days_overdue(row, overall_status, today)
        follow_up, reason = compute_follow_up(row, overall_status, days_overdue, today)
        next_action = compute_next_action(row, overall_status, days_overdue, today)

        overall_status_list.append(overall_status)
        days_overdue_list.append(days_overdue)
        follow_up_list.append(follow_up)
        follow_up_reason_list.append(reason)
        next_action_list.append(next_action)

    df["Overall Status"] = overall_status_list
    df["Days Overdue"] = days_overdue_list
    df["Follow-Up Required"] = follow_up_list
    df["Follow-Up Reason"] = follow_up_reason_list
    df["Recommended Next Action"] = next_action_list

    return df


# ---------------------------------------------------------------------------
# KPIs, action queue, executive summary
# ---------------------------------------------------------------------------

def compute_kpis(df: pd.DataFrame) -> dict:
    """
    Return the five headline KPIs used on the dashboard.
    'Overdue' replaces the previous 'High Risk' metric now that risk
    level is no longer tracked.
    """
    total = len(df)
    approved = int(df["Overall Status"].isin(["Approved", "Complete"]).sum())
    pending_review = int(
        df["Overall Status"].isin(["Not Started", "Waiting for External Response", "Internal Review"]).sum()
    )
    revision_required = int((df["Overall Status"] == "Revision Required").sum())
    overdue = int((df["Days Overdue"] > 0).sum())

    return {
        "total_publishers": total,
        "approved": approved,
        "pending_review": pending_review,
        "revision_required": revision_required,
        "overdue": overdue,
    }


def build_action_queue(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a prioritized action queue containing publishers that require
    follow-up, sorted by:
        1. Priority (High > Medium > Low)
        2. Days Overdue (descending)
        3. Due Date (ascending, soonest first)
    """
    queue = df[df["Follow-Up Required"] == "Yes"].copy()

    if queue.empty:
        return queue

    queue["_priority_rank"] = queue["Priority"].map(PRIORITY_ORDER).fillna(99)
    queue = queue.sort_values(
        by=["_priority_rank", "Days Overdue", "Due Date"],
        ascending=[True, False, True],
    )
    queue = queue.drop(columns=["_priority_rank"])

    display_cols = [
        "Publisher",
        "Account Manager",
        "Priority",
        "Overall Status",
        "Days Overdue",
        "Follow-Up Reason",
        "Recommended Next Action",
        "Due Date",
        "Data Notice",
    ]
    display_cols = [c for c in display_cols if c in queue.columns]
    return queue[display_cols].reset_index(drop=True)


def generate_executive_summary(df: pd.DataFrame, kpis: dict) -> str:
    """
    Generate a concise, factual executive summary built entirely from
    counted values in the dataset. No AI model or external API is used.
    """
    total = kpis["total_publishers"]
    approved = kpis["approved"]
    pending = kpis["pending_review"]
    revision = kpis["revision_required"]
    overdue = kpis["overdue"]

    blocked = int((df["Overall Status"] == "Blocked").sum())
    complete = int((df["Overall Status"] == "Complete").sum())
    follow_up = int((df["Follow-Up Required"] == "Yes").sum())

    lines = [
        "SYNTHETIC DATA — for demonstration purposes only.",
        "",
        f"Portfolio: {total} publisher(s) this planning period — "
        f"{approved} Approved ({complete} fully Complete), {pending} Pending Review, "
        f"{revision} Revision Required, {blocked} Blocked.",
        f"{overdue} publisher(s) are past their due date. {follow_up} publisher(s) require follow-up.",
    ]

    if overdue > 0:
        lines.append(f"Priority: address the {overdue} overdue publisher(s) first.")
    elif follow_up == 0:
        lines.append("No publishers currently require follow-up action.")

    return "\n".join(lines)