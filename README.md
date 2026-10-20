# D2C Order Follow-up Automation

A Streamlit application for direct-to-consumer (D2C) operations teams that turns imported order data into **prioritized follow-up tasks**. It spots order exceptions automatically (unconfirmed orders, dispatch delays, overdue shipments, failed deliveries, high-value overdue orders, and data-quality problems), assigns each exception an owner, priority, action, and deadline, tracks resolution, keeps a full audit trail, and exports a daily exception report.

Built as a local, single-user prototype: no live courier, CRM, WhatsApp, or payment integrations — all data is simulated or imported by you.

## Features

- **CSV & Excel import** — required-column checks, date validation, duplicate-ID detection, and a row-level data-quality report before anything is stored.
- **Automatic exception rule engine** — creates tasks for unconfirmed orders, dispatch delays, overdue shipments, failed delivery attempts, high-value overdue orders, and data corrections.
- **Configurable thresholds** — unconfirmed-order and dispatch-deadline windows are adjustable in the sidebar (defaults: 2 h and 24 h).
- **Task management** — reassign tasks, change status (Open / In Progress / Resolved), and attach update notes.
- **Duplicate-task prevention** — tasks are unique per `(order_id, category)`, so re-imports and re-runs never create duplicates.
- **Dashboard** — order/task/overdue/high-priority metrics plus charts by exception category and employee.
- **Daily report** — one-click CSV export of the day's exceptions, grouped by urgency.
- **Audit trail** — every task creation and update is logged with user, action, details, and timestamp; exportable as CSV.
- **SQLite persistence** — all data survives app restarts.

## Tech stack

| Layer | Choice |
|---|---|
| UI | [Streamlit](https://streamlit.io/) |
| Data handling | pandas |
| Storage | SQLite (single file, no server) |
| Excel support | openpyxl |

## Prerequisites

- **Python 3.10 or newer** — check with `python --version` (Windows) or `python3 --version` (macOS/Linux)
- Internet access for the first dependency installation

## How to run the project

### 1. Get the code

```bash
git clone https://github.com/basavarajmg450-oss/D2C-Order-Follow-up-Automation.git
cd D2C-Order-Follow-up-Automation
```

(Or download and extract the ZIP, then open a terminal in the project folder.)

### 2. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```bat
py -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

> If PowerShell blocks the activation script, run once as administrator:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs `streamlit`, `pandas`, and `openpyxl`.

### 4. Start the app

```bash
streamlit run app.py
```

The app opens automatically at **http://localhost:8501**. If it doesn't, open that URL in your browser.

To stop the app, press `Ctrl+C` in the terminal.

### 5. Load demo data and run the rules (first run)

1. In the left sidebar, click **Load 120-order demo dataset** (120 fictional orders, including deliberate data-quality edge cases).
2. Open the **Import & Rules** tab and click **Run rules and create tasks**.
3. Explore the generated tasks in **Task Management**, the summary in **Daily Report**, and the logged events in **Audit Trail**.

The SQLite database file `order_followup.db` is created automatically beside `app.py` on first run.

## Using your own data

Go to the **Import & Rules** tab and upload a CSV or Excel file (`.csv`, `.xlsx`, `.xls`) with **exactly these column headers**:

| Column | Example | Notes |
|---|---|---|
| `Order ID` | `NX-1042` | Unique per order; duplicates are reported and imported once |
| `Order date` | `2026-10-20 10:30:00` | Any pandas-parseable date |
| `Customer name` | `Customer 042` | |
| `Phone number` | `9876543210` | |
| `Order value` | `2499` | Numeric, in rupees |
| `Payment type` | `Prepaid` / `COD` | |
| `Order status` | `unconfirmed`, `confirmed`, `dispatched`, `in transit`, `delivered`, `failed delivery` | |
| `Dispatch date` | `2026-10-20 18:00:00` | Blank if not yet dispatched |
| `Expected delivery date` | `2026-10-23 18:00:00` | |
| `Assigned employee` | `Asha` | Use `Unassigned` if none |

Before importing you'll see a **preview** and a **data-quality report** listing problem rows (missing order IDs, invalid dates, duplicate IDs, missing names/values). Click **Validate and import valid orders** to store the valid rows — existing order IDs are updated, never duplicated.

A ready-made example file, `sample_orders.csv` (120 rows), is included.

## The tabs

### Overview
Headline metrics — orders stored, tasks requiring attention, overdue tasks, high-priority open — plus charts of exceptions by category and pending tasks by employee, and a table of high-priority cases.

### Import & Rules
Upload files, review the data-quality report, import valid orders, and run the exception rule engine. Re-running never duplicates existing tasks.

### Task Management
Filter tasks by exception type, employee, priority, and status. Select any task to reassign it, change its status, and add an update note — every change is written to the audit trail.

### Daily Report
Today's exceptions grouped into New / Unresolved / Overdue / High-priority, with counts and a CSV download (`order_followup_exception_report_YYYY-MM-DD.csv`).

### Audit Trail
A chronological log of every task creation and update (who, what, when), exportable as `order_followup_audit_trail.csv`.

## How the rule engine works

The engine scans every stored order on each run and raises tasks using these rules:

| Exception category | Trigger | Priority | Default deadline |
|---|---|---|---|
| Unconfirmed order | Status is unconfirmed more than *N* hours after the order (default 2 h, configurable) | Medium | +4 h |
| Dispatch delay | Confirmed but not dispatched within the dispatch window (default 24 h, configurable) | High | +4 h |
| Shipment delay | Dispatched, expected delivery date has passed, not delivered | High | +4 h |
| Failed delivery | Status indicates a failed/attempted delivery | High | +2 h |
| High-value overdue order | Order value > ₹5,000 and delivery overdue | High | +2 h |
| Data correction | Missing/invalid status, order date, order value, or missing expected delivery for a dispatched order | Medium | +4 h |

Thresholds are changed in the sidebar and apply to the **next** rule run. Because tasks are unique per `(order_id, category)`, changing thresholds and re-running only adds genuinely new exceptions — it never duplicates existing ones.

## Project structure

```
.
├── app.py               # Streamlit application (UI, rule engine, storage)
├── sample_orders.csv    # 120-row fictional sample dataset with edge cases
├── requirements.txt     # Python dependencies
├── DEMO_SCRIPT.md       # 5-minute live demo script
├── README.md            # This file
└── order_followup.db    # SQLite database (created automatically on first run)
```

## Design choices and known limitations

- **One task per order + exception category.** Repeated imports and rule runs are idempotent. An existing task is not automatically reopened or refreshed if the underlying order later changes.
- **Defective rows are surfaced, not silently dropped.** Blank/invalid order date, order value, or status appear in the import quality report and are skipped; other data issues become a *Data correction* task when the order is otherwise usable.
- **Local prototype.** No live courier, CRM, WhatsApp, or payment integrations; rules operate only on the statuses and timestamps you import. No login/permissions or deployment hardening — suitable for evaluation and demos, not production customer data.
- **Demo data only.** Use fictional data; do not upload real customer personal data to an unapproved environment.

## Suggested demo flow (5 minutes)

1. Load the demo dataset from the sidebar.
2. Show the **Overview** metrics.
3. Run the rule engine in **Import & Rules**.
4. In **Task Management**, filter to High priority, reassign a task, and set it In Progress.
5. Show the update in **Audit Trail**.
6. Download the CSV from **Daily Report**.
7. Change the dispatch threshold from 24 h to 12 h in the sidebar, re-run the rules, and show that no duplicate tasks appear.
