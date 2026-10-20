import io
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "order_followup.db"

REQUIRED_COLUMNS = [
    "Order ID", "Order date", "Customer name", "Phone number", "Order value",
    "Payment type", "Order status", "Dispatch date", "Expected delivery date",
    "Assigned employee",
]
DATE_COLUMNS = ["Order date", "Dispatch date", "Expected delivery date"]
EXCEPTION_CATEGORIES = [
    "Unconfirmed order", "Dispatch delay", "Shipment delay", "Failed delivery",
    "High-value overdue order", "Data correction",
]

st.set_page_config(page_title="D2C Order Follow-up Automation", layout="wide")


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            order_date TEXT, customer_name TEXT, phone_number TEXT,
            order_value REAL, payment_type TEXT, order_status TEXT,
            dispatch_date TEXT, expected_delivery_date TEXT,
            assigned_employee TEXT, source_row INTEGER, imported_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            customer_name TEXT,
            phone_number TEXT,
            category TEXT NOT NULL,
            reason TEXT NOT NULL,
            priority TEXT NOT NULL,
            assigned_employee TEXT,
            action_required TEXT NOT NULL,
            deadline TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(order_id, category),
            FOREIGN KEY(order_id) REFERENCES orders(order_id)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            order_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            responsible_user TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );
        """)


def now():
    return datetime.now().replace(microsecond=0)


def iso(value):
    if pd.isna(value) or value is None or str(value).strip() == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def load_orders():
    with connect() as conn:
        return pd.read_sql_query("SELECT * FROM orders ORDER BY order_date DESC", conn)


def load_tasks():
    with connect() as conn:
        return pd.read_sql_query("""
            SELECT t.*, o.order_value, o.order_status, o.payment_type
            FROM tasks t LEFT JOIN orders o ON t.order_id=o.order_id
            ORDER BY CASE t.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                     t.deadline
        """, conn)


def audit(task_id, order_id, action, details, user):
    with connect() as conn:
        conn.execute(
            "INSERT INTO audit_log(task_id, order_id, action, details, responsible_user, timestamp) VALUES(?,?,?,?,?,?)",
            (task_id, str(order_id), action, details, user, now().isoformat(sep=" ", timespec="seconds")),
        )


def normalize_upload(raw):
    df = raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        return None, [f"Missing required columns: {', '.join(missing_columns)}"], pd.DataFrame()

    df = df[REQUIRED_COLUMNS].copy()
    df["Order ID"] = df["Order ID"].astype("string").str.strip()
    df["Customer name"] = df["Customer name"].astype("string").str.strip()
    df["Phone number"] = df["Phone number"].astype("string").str.strip()
    df["Assigned employee"] = df["Assigned employee"].astype("string").str.strip()
    df["Payment type"] = df["Payment type"].astype("string").str.strip().str.upper()
    df["Order status"] = df["Order status"].astype("string").str.strip().str.lower()
    df["Order value"] = pd.to_numeric(df["Order value"], errors="coerce")
    invalid_dates = {}
    for col in DATE_COLUMNS:
        parsed = pd.to_datetime(df[col], errors="coerce")
        invalid_dates[col] = df[col].notna() & df[col].astype(str).str.strip().ne("") & parsed.isna()
        df[col] = parsed
    issues = []
    for col, mask in invalid_dates.items():
        if mask.any():
            issues.append(f"{int(mask.sum())} invalid value(s) in {col}.")
    blank_ids = df["Order ID"].isna() | df["Order ID"].eq("")
    if blank_ids.any():
        issues.append(f"{int(blank_ids.sum())} row(s) have a missing Order ID.")
    duplicate_mask = df["Order ID"].duplicated(keep=False) & ~blank_ids
    if duplicate_mask.any():
        issues.append(f"{int(duplicate_mask.sum())} row(s) belong to duplicate Order IDs.")
    missing_fields = df[REQUIRED_COLUMNS].isna().sum()
    empty_strings = df[REQUIRED_COLUMNS].astype("string").apply(lambda s: s.str.strip().eq("").sum())
    missing_summary = (missing_fields + empty_strings).to_dict()
    issue_rows = []
    for idx, row in df.iterrows():
        row_issues = []
        if pd.isna(row["Order ID"]) or str(row["Order ID"]).strip() == "":
            row_issues.append("Missing Order ID")
        if pd.isna(row["Customer name"]) or str(row["Customer name"]).strip() == "":
            row_issues.append("Missing customer name")
        if pd.isna(row["Order date"]):
            row_issues.append("Missing or invalid order date")
        if pd.isna(row["Order value"]):
            row_issues.append("Missing or invalid order value")
        for col in DATE_COLUMNS[1:]:
            original = raw.iloc[idx][col] if col in raw.columns else None
            if pd.notna(original) and str(original).strip() and pd.isna(row[col]):
                row_issues.append(f"Invalid {col}")
        if duplicate_mask.iloc[idx]:
            row_issues.append("Duplicate Order ID")
        if row_issues:
            issue_rows.append({"CSV row": idx + 2, "Order ID": row["Order ID"], "Issues": "; ".join(row_issues)})
    issue_df = pd.DataFrame(issue_rows)
    return df, issues, issue_df


def make_exceptions(df, unconfirmed_hours=2, dispatch_hours=24):
    exceptions = []
    current = now()
    for _, r in df.iterrows():
        oid = str(r.get("order_id", r.get("Order ID", ""))).strip()
        if not oid or oid.lower() == "nan":
            continue
        get = lambda snake, title: r.get(snake, r.get(title))
        order_date = pd.to_datetime(get("order_date", "Order date"), errors="coerce")
        dispatch_date = pd.to_datetime(get("dispatch_date", "Dispatch date"), errors="coerce")
        expected = pd.to_datetime(get("expected_delivery_date", "Expected delivery date"), errors="coerce")
        status = str(get("order_status", "Order status") or "").lower()
        customer = str(get("customer_name", "Customer name") or "")
        phone = str(get("phone_number", "Phone number") or "")
        employee = str(get("assigned_employee", "Assigned employee") or "")
        value = pd.to_numeric(get("order_value", "Order value"), errors="coerce")
        if status == "nan": status = ""
        if not status or pd.isna(order_date) or pd.isna(value):
            exceptions.append((oid, customer, phone, "Data correction",
                "Required status, valid order date, or order value is missing/invalid.",
                "Medium", employee, "Correct the source order record before processing.", current + timedelta(hours=4)))
            continue

        delivered = "deliver" in status and "undeliver" not in status and "failed" not in status
        failed = "fail" in status or "delivery attempted" in status or "attempt failed" in status
        dispatched = pd.notna(dispatch_date) or "dispatch" in status or "shipped" in status or "in transit" in status
        confirmed = any(x in status for x in ["confirm", "dispatch", "shipped", "in transit", "deliver"]) and "unconfirm" not in status

        if failed:
            exceptions.append((oid, customer, phone, "Failed delivery",
                "A delivery attempt failed and needs immediate follow-up.", "High", employee,
                "Contact the customer/carrier and schedule another delivery attempt.", current + timedelta(hours=2)))
        elif not confirmed and not dispatched and not delivered:
            if current - order_date.to_pydatetime() > timedelta(hours=unconfirmed_hours):
                exceptions.append((oid, customer, phone, "Unconfirmed order",
                    f"Order has remained unconfirmed for more than {unconfirmed_hours} hours.", "Medium", employee,
                    "Contact the customer and confirm the order.", current + timedelta(hours=4)))
        if confirmed and not dispatched and not delivered:
            if current - order_date.to_pydatetime() > timedelta(hours=dispatch_hours):
                exceptions.append((oid, customer, phone, "Dispatch delay",
                    f"Confirmed order has not been dispatched within {dispatch_hours} hours.", "High", employee,
                    "Check inventory and dispatch the order or update the customer.", current + timedelta(hours=4)))
        if dispatched and not delivered and pd.isna(expected):
            exceptions.append((oid, customer, phone, "Data correction",
                "Expected delivery date is missing for a dispatched order.", "Medium", employee,
                "Update the expected delivery date from the shipping record.", current + timedelta(hours=4)))
        elif dispatched and not delivered and pd.notna(expected) and expected.to_pydatetime() < current:
            exceptions.append((oid, customer, phone, "Shipment delay",
                "Expected delivery date has passed and the order is not delivered.", "High", employee,
                "Check tracking status and contact the carrier/customer.", current + timedelta(hours=4)))
            if pd.notna(value) and value > 5000:
                exceptions.append((oid, customer, phone, "High-value overdue order",
                    "Order value exceeds ₹5,000 and delivery is overdue.", "High", employee,
                    "Escalate to the manager and contact the carrier/customer.", current + timedelta(hours=2)))
    return exceptions


def persist_upload(df, actor):
    imported = 0
    with connect() as conn:
        for _, r in df.iterrows():
            oid = str(r["Order ID"]).strip()
            if not oid or oid.lower() == "nan":
                continue
            if pd.isna(r["Order date"]) or pd.isna(r["Order value"]) or pd.isna(r["Order status"]) or str(r["Order status"]).strip() == "":
                continue
            vals = (
                oid, iso(r["Order date"]), text(r["Customer name"]),
                text(r["Phone number"]), float(r["Order value"]), text(r["Payment type"]),
                text(r["Order status"]), iso(r["Dispatch date"]), iso(r["Expected delivery date"]),
                text(r["Assigned employee"]), int(r.name) + 2,
                now().isoformat(sep=" ", timespec="seconds")
            )
            conn.execute("""
                INSERT INTO orders(order_id,order_date,customer_name,phone_number,order_value,payment_type,
                    order_status,dispatch_date,expected_delivery_date,assigned_employee,source_row,imported_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(order_id) DO UPDATE SET
                    order_date=excluded.order_date, customer_name=excluded.customer_name,
                    phone_number=excluded.phone_number, order_value=excluded.order_value,
                    payment_type=excluded.payment_type, order_status=excluded.order_status,
                    dispatch_date=excluded.dispatch_date, expected_delivery_date=excluded.expected_delivery_date,
                    assigned_employee=excluded.assigned_employee, source_row=excluded.source_row,
                    imported_at=excluded.imported_at
            """, vals)
            imported += 1
    return imported


def generate_tasks(actor, unconfirmed_hours, dispatch_hours):
    orders = load_orders()
    if orders.empty:
        return 0
    exceptions = make_exceptions(orders, unconfirmed_hours, dispatch_hours)
    created = 0
    for item in exceptions:
        oid, customer, phone, category, reason, priority, employee, action, deadline = item
        with connect() as conn:
            before = conn.total_changes
            conn.execute("""
                INSERT OR IGNORE INTO tasks(order_id,customer_name,phone_number,category,reason,priority,
                    assigned_employee,action_required,deadline,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,'Open',?,?)
            """, (oid, customer, phone, category, reason, priority, employee, action,
                  deadline.isoformat(sep=" ", timespec="seconds"),
                  now().isoformat(sep=" ", timespec="seconds"),
                  now().isoformat(sep=" ", timespec="seconds")))
            inserted = conn.total_changes > before
            task = conn.execute("SELECT id FROM tasks WHERE order_id=? AND category=?", (oid, category)).fetchone()
        if inserted:
            created += 1
            audit(task[0], oid, "Task created", f"{category}: {reason}", actor)
    return created


def sample_data():
    import random
    random.seed(42)
    current = now()
    rows = []
    statuses = ["unconfirmed", "confirmed", "dispatched", "in transit", "delivered", "failed delivery"]
    for i in range(1, 121):
        status = random.choices(statuses, weights=[12, 20, 18, 20, 22, 8])[0]
        age = random.randint(1, 96)
        order_date = current - timedelta(hours=age)
        dispatch = None
        expected = current - timedelta(days=random.randint(1, 4)) if status in ["dispatched", "in transit", "failed delivery"] and random.random() < .55 else current + timedelta(days=random.randint(1, 5))
        if status in ["dispatched", "in transit", "delivered", "failed delivery"]:
            dispatch = order_date + timedelta(hours=random.randint(2, 30))
        if status == "delivered":
            expected = order_date + timedelta(days=random.randint(1, 5))
        rows.append({
            "Order ID": f"NX-{1000+i}", "Order date": order_date.strftime("%Y-%m-%d %H:%M:%S"),
            "Customer name": f"Customer {i:03d}", "Phone number": f"9{random.randint(100000000,999999999)}",
            "Order value": random.choice([499, 899, 1499, 2499, 5499, 7999, 12499]),
            "Payment type": random.choice(["Prepaid", "COD"]), "Order status": status,
            "Dispatch date": dispatch.strftime("%Y-%m-%d %H:%M:%S") if dispatch else "",
            "Expected delivery date": expected.strftime("%Y-%m-%d %H:%M:%S"),
            "Assigned employee": random.choice(["Asha", "Rahul", "Priya", "Kiran", "Unassigned"]),
        })
    # Deliberate data-quality examples
    rows[5]["Customer name"] = ""
    rows[9]["Order ID"] = rows[8]["Order ID"]  # duplicate
    rows[14]["Expected delivery date"] = "not-a-date"
    return pd.DataFrame(rows)


init_db()
st.title("D2C Order Follow-up Automation")
st.caption("Assessment prototype · Demo data only · No live courier, WhatsApp, or production integrations")

with st.sidebar:
    st.header("Controls")
    actor = st.text_input("Responsible user", value="Demo Manager")
    unconfirmed_hours = st.number_input("Unconfirmed threshold (hours)", min_value=1, max_value=72, value=2)
    dispatch_hours = st.number_input("Dispatch deadline (hours)", min_value=1, max_value=96, value=24)
    st.caption("Changing thresholds affects the next rule-engine run.")
    if st.button("Load 120-order demo dataset", use_container_width=True):
        demo = sample_data()
        persist_upload(demo, actor)
        st.session_state["last_import"] = f"Loaded demo data. Data-quality examples are included."
        st.rerun()

pages = st.tabs(["Overview", "Import & Rules", "Task Management", "Daily Report", "Audit Trail"])

with pages[0]:
    orders = load_orders()
    tasks = load_tasks()
    open_tasks = tasks[tasks["status"].isin(["Open", "In Progress"])] if not tasks.empty else tasks
    overdue = tasks[(tasks["status"] != "Resolved") & (pd.to_datetime(tasks["deadline"], errors="coerce") < pd.Timestamp.now())] if not tasks.empty else tasks
    high = tasks[(tasks["priority"] == "High") & (tasks["status"] != "Resolved")] if not tasks.empty else tasks
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Orders stored", len(orders))
    c2.metric("Tasks requiring attention", len(open_tasks))
    c3.metric("Overdue tasks", len(overdue))
    c4.metric("High-priority open", len(high))
    if not tasks.empty:
        st.subheader("Exceptions by category")
        st.bar_chart(tasks.groupby("category").size().rename("Tasks"))
        st.subheader("Pending tasks by employee")
        pending = open_tasks.copy()
        pending["assigned_employee"] = pending["assigned_employee"].replace("", "Unassigned").fillna("Unassigned")
        st.bar_chart(pending.groupby("assigned_employee").size().rename("Pending tasks"))
        st.subheader("High-priority cases")
        st.dataframe(high[["order_id","customer_name","category","reason","assigned_employee","deadline","status"]], use_container_width=True, hide_index=True)
    else:
        st.info("No tasks yet. Import a dataset or load the 120-order demo dataset from the sidebar.")

with pages[1]:
    st.subheader("Import orders")
    st.write("Upload a CSV or Excel workbook. Column names must match the assessment's required fields.")
    uploaded = st.file_uploader("Choose CSV or Excel file", type=["csv","xlsx","xls"])
    if uploaded:
        try:
            raw = pd.read_csv(uploaded) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded)
            st.write("Preview")
            st.dataframe(raw.head(10), use_container_width=True)
            normalized, warnings, issue_df = normalize_upload(raw)
            if normalized is None:
                for warning in warnings: st.error(warning)
            else:
                if warnings:
                    for warning in warnings: st.warning(warning)
                if not issue_df.empty:
                    st.warning("Data-quality review: rows below need correction. Duplicate IDs are not imported twice.")
                    st.dataframe(issue_df, use_container_width=True, hide_index=True)
                if st.button("Validate and import valid orders", type="primary"):
                    count = persist_upload(normalized, actor)
                    st.success(f"Imported/updated {count} valid orders. Existing order IDs are updated, not duplicated.")
                    st.session_state["last_import"] = f"Imported/updated {count} orders."
        except Exception as e:
            st.error(f"Could not read the file: {e}")
    st.divider()
    st.subheader("Run exception rule engine")
    st.write("Creates one task per order and exception category. Re-running will not create duplicate tasks for the same pair.")
    if st.button("Run rules and create tasks", type="primary"):
        count = generate_tasks(actor, unconfirmed_hours, dispatch_hours)
        st.success(f"Rule run complete. {count} new task(s) created; existing tasks were not duplicated.")

with pages[2]:
    st.subheader("Task management")
    tasks = load_tasks()
    if tasks.empty:
        st.info("No tasks yet. Import orders and run the rule engine.")
    else:
        f1,f2,f3,f4 = st.columns(4)
        cat_options = ["All"] + sorted(tasks["category"].dropna().unique().tolist())
        employee_options = ["All"] + sorted(set(tasks["assigned_employee"].fillna("").replace("", "Unassigned").tolist()))
        status_options = ["All", "Open", "In Progress", "Resolved"]
        priority_options = ["All", "High", "Medium", "Low"]
        category_filter = f1.selectbox("Exception type", cat_options)
        employee_filter = f2.selectbox("Employee", employee_options)
        priority_filter = f3.selectbox("Priority", priority_options)
        status_filter = f4.selectbox("Status", status_options)
        filtered = tasks.copy()
        if category_filter != "All": filtered = filtered[filtered["category"] == category_filter]
        if employee_filter != "All": filtered = filtered[filtered["assigned_employee"].fillna("").replace("", "Unassigned") == employee_filter]
        if priority_filter != "All": filtered = filtered[filtered["priority"] == priority_filter]
        if status_filter != "All": filtered = filtered[filtered["status"] == status_filter]
        st.dataframe(filtered[["id","order_id","customer_name","category","reason","priority","assigned_employee","action_required","deadline","status"]], use_container_width=True, hide_index=True)
        st.divider()
        st.subheader("Update or reassign a task")
        task_ids = filtered["id"].astype(int).tolist()
        if task_ids:
            task_id = st.selectbox("Task ID", task_ids)
            selected = tasks[tasks["id"] == task_id].iloc[0]
            with st.form("update_task_form"):
                new_employee = st.text_input("Assigned employee", value=str(selected["assigned_employee"] or ""))
                new_status = st.selectbox("Task status", ["Open","In Progress","Resolved"], index=["Open","In Progress","Resolved"].index(selected["status"]))
                reason_note = st.text_input("Update note (optional)")
                submitted = st.form_submit_button("Save task update")
            if submitted:
                changes = []
                if new_employee != str(selected["assigned_employee"] or ""):
                    changes.append(f"Assignee: {selected['assigned_employee']} → {new_employee}")
                if new_status != selected["status"]:
                    changes.append(f"Status: {selected['status']} → {new_status}")
                if reason_note.strip(): changes.append(f"Note: {reason_note.strip()}")
                with connect() as conn:
                    conn.execute("UPDATE tasks SET assigned_employee=?, status=?, updated_at=? WHERE id=?",
                                 (new_employee.strip(), new_status, now().isoformat(sep=" ", timespec="seconds"), int(task_id)))
                if changes:
                    audit(int(task_id), selected["order_id"], "Task updated", " | ".join(changes), actor)
                st.success("Task updated and audit event recorded.")
                st.rerun()

with pages[3]:
    st.subheader("Daily exception report")
    tasks = load_tasks()
    if tasks.empty:
        st.info("No tasks to report yet.")
    else:
        today = now().date()
        created_dates = pd.to_datetime(tasks["created_at"], errors="coerce").dt.date
        unresolved = tasks[tasks["status"] != "Resolved"]
        overdue = unresolved[pd.to_datetime(unresolved["deadline"], errors="coerce") < pd.Timestamp.now()]
        high = unresolved[unresolved["priority"] == "High"]
        report = tasks.copy()
        report["Report group"] = "Unresolved exception"
        report.loc[created_dates == today, "Report group"] = "New exception today"
        report.loc[report["status"] == "Resolved", "Report group"] = "Resolved"
        report.loc[report["id"].isin(overdue["id"]), "Report group"] = "Overdue task"
        report.loc[report["id"].isin(high["id"]), "Report group"] = "High-priority case"
        st.metric("New exceptions today", int((created_dates == today).sum()))
        st.metric("Unresolved exceptions", len(unresolved))
        st.metric("Overdue tasks", len(overdue))
        st.metric("High-priority unresolved", len(high))
        st.dataframe(report[["Report group","order_id","customer_name","category","priority","assigned_employee","action_required","deadline","status"]], use_container_width=True, hide_index=True)
        csv_bytes = report.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Download daily exception report (CSV)", csv_bytes,
                           file_name=f"order_followup_exception_report_{today.isoformat()}.csv", mime="text/csv")

with pages[4]:
    st.subheader("Audit trail")
    with connect() as conn:
        logs = pd.read_sql_query("SELECT * FROM audit_log ORDER BY timestamp DESC", conn)
    if logs.empty:
        st.info("No audit events yet. Create or update tasks to populate the audit trail.")
    else:
        st.dataframe(logs, use_container_width=True, hide_index=True)
        st.download_button("Download audit trail CSV", logs.to_csv(index=False).encode("utf-8-sig"),
                           file_name="order_followup_audit_trail.csv", mime="text/csv")

st.divider()
st.caption("Prototype note: This application uses a local SQLite database and simulated data. It does not connect to real customer, courier, CRM, WhatsApp, or payment systems.")
