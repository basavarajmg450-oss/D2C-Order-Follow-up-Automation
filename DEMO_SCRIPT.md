# Five-minute demonstration script

**0:00–0:30 — Introduce the problem**
“Manual order follow-up across spreadsheets and chat messages can cause unconfirmed, delayed, and failed orders to be missed. This prototype turns imported order data into prioritized follow-up tasks.”

**0:30–1:15 — Load data**
Show the sidebar and click “Load 120-order demo dataset.” Explain that the sample includes normal orders and deliberate data-quality examples.

**1:15–2:00 — Run rules**
Open Import & Rules and click “Run rules and create tasks.” Explain the rule thresholds: unconfirmed over 2 hours, confirmed but not dispatched within the configured dispatch window, overdue shipments, failed deliveries, and high-value overdue orders.

**2:00–3:00 — Task handling**
Open Task Management. Filter to High priority, choose a task, reassign it, and change status to In Progress. Explain that each task has an owner, reason, action, priority, and deadline.

**3:00–3:40 — Audit and report**
Open Audit Trail to show the recorded update. Open Daily Report and download the CSV.

**3:40–4:30 — Live change challenge**
Change the dispatch threshold in the sidebar from 24 hours to 12 hours, rerun the rule engine, and explain that the unique order/category key prevents duplicate task creation. Existing tasks are not automatically refreshed or reopened in this prototype.

**4:30–5:00 — Impact and limitations**
Metrics include open/overdue tasks, high-priority cases, and pending work by employee. State that time savings must be measured in a pilot. Limitations: local prototype, simulated data, no live courier/CRM/WhatsApp integrations, and no multi-user authentication.
