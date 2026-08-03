# Commercial Operations Copilot — Deterministic Business Rules

## Purpose
This document defines the deterministic (rule-based, non-AI) logic used to evaluate quarterly account plans within the Commercial Operations Copilot. Every output is calculated from fixed conditions applied to structured fields in the synthetic dataset, ensuring results are consistent, explainable, and auditable.

All account names, dates, and figures used in examples are **synthetic and fictional**.

---

## Reference Fields
These synthetic fields drive all rule evaluation:

| Field | Description |
|---|---|
| `plan_sent_date` | Date the quarterly plan was sent to the account contact |
| `response_received_date` | Date a response was received (blank if none) |
| `due_date` | Date the plan is due for completion |
| `today` | Current system date used for all calculations |
| `priority_tier` | `Standard` or `High` |
| `feedback_status` | `Not Requested`, `Requested`, or `Received` |
| `revision_flag` | `Yes` / `No` — plan has been sent back for revision |
| `blocker_flag` | `Yes` / `No` — an unresolved dependency exists |
| `approval_flag` | `Yes` / `No` — plan has been formally approved |
| `completion_flag` | `Yes` / `No` — all planning steps are finished |

---

## 1. Overall Status Rules

Evaluated top-down; the first matching rule determines status.

### Rule 1.1 — Complete
- **Condition:** `approval_flag = Yes` AND `completion_flag = Yes`
- **Output:** `Complete`
- **Rationale:** No further action exists once a plan is both approved and fully executed.
- **Example:** Account "Fictional Corp A" has an approved plan with all steps closed → status = `Complete`.

### Rule 1.2 — Blocked
- **Condition:** `blocker_flag = Yes` AND `completion_flag = No`
- **Output:** `Blocked`
- **Rationale:** An unresolved dependency prevents progress regardless of other fields.
- **Example:** Account "Sample Ventures B" is waiting on a dependency from another team → status = `Blocked`.

### Rule 1.3 — Revision Required
- **Condition:** `revision_flag = Yes` AND `blocker_flag = No`
- **Output:** `Revision required`
- **Rationale:** The plan was reviewed and sent back for changes; it is active but not yet acceptable.
- **Example:** Account "Demo Industries C" plan was reviewed and marked for edits → status = `Revision required`.

### Rule 1.4 — Waiting for External Response
- **Condition:** `plan_sent_date` is not blank AND `response_received_date` is blank AND `revision_flag = No` AND `blocker_flag = No`
- **Output:** `Waiting for external response`
- **Rationale:** The plan has been sent but the account contact has not yet responded.
- **Example:** Plan sent to "Placeholder Ltd D" 10 days ago with no reply → status = `Waiting for external response`.

### Rule 1.5 — Internal Review
- **Condition:** `response_received_date` is not blank AND `approval_flag = No` AND `revision_flag = No`
- **Output:** `Internal review`
- **Rationale:** A response has come back and the internal team is now evaluating it.
- **Example:** "Test Group E" responded and the plan awaits sign-off → status = `Internal review`.

### Rule 1.6 — Not Started
- **Condition:** `plan_sent_date` is blank
- **Output:** `Not started`
- **Rationale:** No plan has been initiated yet for this account.
- **Example:** "Fictional Org F" has no `plan_sent_date` recorded → status = `Not started`.

### Rule 1.7 — Approved (interim)
- **Condition:** `approval_flag = Yes` AND `completion_flag = No`
- **Output:** `Approved`
- **Rationale:** The plan is approved but execution steps are still in progress.
- **Example:** "Sample Co G" plan approved but rollout tasks remain open → status = `Approved`.

---

## 2. Risk Level Rules

Evaluated top-down; highest applicable risk wins.

### Rule 2.1 — Critical Risk
- **Condition:** Status = `Blocked` OR (`due_date` has passed AND status ≠ `Complete`)
- **Output:** `Critical`
- **Rationale:** A blocked workflow or a missed due date represents a direct threat to the quarterly plan.
- **Example:** "Fictional Corp A" due date passed 3 days ago and status is `Internal review` → risk = `Critical`.

### Rule 2.2 — High Risk
- **Condition:** Status = `Revision required` AND `feedback_status ≠ Received` for more than 5 days since revision was requested
  **OR** `priority_tier = High` AND `due_date` is within 5 days AND status ≠ `Approved`/`Complete`
- **Output:** `High`
- **Rationale:** Either feedback is stalled on a revision, or a high-priority account is approaching deadline without resolution.
- **Example:** "Sample Ventures B" is `High` priority with a due date in 3 days and status still `Internal review` → risk = `High`.

### Rule 2.3 — Medium Risk
- **Condition:** Status = `Waiting for external response` AND no response received within 7 days of `plan_sent_date`
- **Output:** `Medium`
- **Rationale:** A delayed external response is a moderate concern that may escalate if it continues.
- **Example:** Plan sent to "Placeholder Ltd D" 8 days ago with no response → risk = `Medium`.

### Rule 2.4 — Low Risk
- **Condition:** None of the above conditions apply
- **Output:** `Low`
- **Rationale:** The account is progressing on schedule with no identified concern.
- **Example:** "Test Group E" is in `Internal review` with a due date 20 days away → risk = `Low`.

---

## 3. Follow-Up Required Rules

### Rule 3.1 — Follow-Up Required: Yes (Non-Response)
- **Condition:** Status = `Waiting for external response` AND no response within 7 days
- **Output:** `Follow-up required = Yes` (reason: "No response after 7 days")
- **Rationale:** Silence beyond a defined window warrants proactive outreach.
- **Example:** "Placeholder Ltd D" — 8 days since plan sent, no response → follow-up required.

### Rule 3.2 — Follow-Up Required: Yes (Stalled Revision)
- **Condition:** Status = `Revision required` AND `feedback_status ≠ Received` for more than 5 days
- **Output:** `Follow-up required = Yes` (reason: "Revision feedback overdue")
- **Rationale:** Revisions that stall without returned feedback block quarterly completion.
- **Example:** "Demo Industries C" requested revision 6 days ago; no feedback returned → follow-up required.

### Rule 3.3 — Follow-Up Required: Yes (Blocked)
- **Condition:** Status = `Blocked`
- **Output:** `Follow-up required = Yes` (reason: "Unresolved blocker")
- **Rationale:** Blocked accounts require active intervention to resume progress.
- **Example:** "Sample Ventures B" blocked on dependency → follow-up required.

### Rule 3.4 — Follow-Up Required: No
- **Condition:** Status = `Complete`, `Approved`, or none of Rules 3.1–3.3 apply
- **Output:** `Follow-up required = No`
- **Rationale:** No unresolved condition currently demands action.
- **Example:** "Fictional Corp A" is `Complete` → no follow-up required.

---

## 4. Days Overdue Rules

### Rule 4.1 — Overdue Calculation
- **Condition:** `due_date` is earlier than `today` AND status ≠ `Complete`
- **Output:** `Days overdue = today − due_date` (in days)
- **Rationale:** Provides a precise, auditable measure of schedule slippage.
- **Example:** `due_date` = 5 days ago, status = `Internal review` → `Days overdue = 5`.

### Rule 4.2 — Not Overdue
- **Condition:** `due_date` is today or in the future, OR status = `Complete`
- **Output:** `Days overdue = 0`
- **Rationale:** An account with no passed deadline (or one already finished) has no overdue days.
- **Example:** "Test Group E" due date is in 20 days → `Days overdue = 0`.

---

## 5. Recommended Next Action Rules

Evaluated top-down; the first matching rule determines the action.

### Rule 5.1 — Resolve Blocker
- **Condition:** Status = `Blocked`
- **Output:** `"Escalate and resolve blocking dependency"`
- **Rationale:** No planning progress can occur until the blocker is cleared.
- **Example:** "Sample Ventures B" → recommended action: resolve blocker.

### Rule 5.2 — Escalate Overdue Item
- **Condition:** `Days overdue > 0`
- **Output:** `"Escalate to account owner — due date passed"`
- **Rationale:** Passed due dates require immediate attention to prevent further slippage.
- **Example:** "Fictional Corp A" 5 days overdue → recommended action: escalate to owner.

### Rule 5.3 — Expedite High-Priority Deadline
- **Condition:** `priority_tier = High` AND `due_date` within 5 days AND status ≠ `Approved`/`Complete`
- **Output:** `"Expedite review — high-priority due date approaching"`
- **Rationale:** High-priority accounts nearing deadline need to be fast-tracked ahead of standard items.
- **Example:** "Sample Ventures B" due in 3 days, `High` priority → recommended action: expedite review.

### Rule 5.4 — Send Reminder (Non-Response)
- **Condition:** Status = `Waiting for external response` AND no response within 7 days
- **Output:** `"Send follow-up reminder to account contact"`
- **Rationale:** A structured nudge is the appropriate next step after a defined silence period.
- **Example:** "Placeholder Ltd D" 8 days with no response → recommended action: send reminder.

### Rule 5.5 — Request Revision Feedback
- **Condition:** Status = `Revision required` AND `feedback_status ≠ Received` for more than 5 days
- **Output:** `"Request updated feedback on revision"`
- **Rationale:** Progress cannot resume until revised feedback is returned.
- **Example:** "Demo Industries C" — 6 days since revision requested, no feedback → recommended action: request feedback.

### Rule 5.6 — Proceed to Approval
- **Condition:** Status = `Internal review` AND `Days overdue = 0`
- **Output:** `"Proceed with internal approval review"`
- **Rationale:** The plan is on track and simply awaiting sign-off.
- **Example:** "Test Group E" in `Internal review`, on schedule → recommended action: proceed to approval.

### Rule 5.7 — No Action Needed
- **Condition:** Status = `Complete`, or (`Approved` AND `Days overdue = 0`)
- **Output:** `"No action needed"`
- **Rationale:** The account has reached a stable, resolved state.
- **Example:** "Fictional Corp A" — status `Complete` → recommended action: no action needed.

---

## Auditability Notes
- All rules are evaluated in a fixed, documented order per category (top-down, first match wins).
- No rule relies on probabilistic scoring, machine learning, or generative output — every result can be traced back to specific field values and thresholds.
- All account names and data referenced above are synthetic and fictional, used solely to illustrate rule behavior.
