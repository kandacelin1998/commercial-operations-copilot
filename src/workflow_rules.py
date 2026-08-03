"""
Deterministic business rules for the Commercial Operations Copilot.

This module is the single source of computational logic for the app.
It implements the rules documented in docs/BUSINESS_RULES.md:
    1. Overall status        -> sourced directly from the validated 'review_status' column
    2. Risk level             -> compute_risk_level()
    3. Follow-up required     -> compute_follow_up()
    4. Days overdue           -> compute_days_overdue()
    5. Recommended next action -> compute_next_action()

No AI model, external API, or probabilistic scoring is used anywhere
in this module. Every output can be traced back to specific field values.
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