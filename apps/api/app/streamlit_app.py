"""RunwayKeeper — Autonomous Cash-Flow Operations Streamlit Application.

A complete, self-contained, interactive frontend replicating all RunwayKeeper capabilities:
1. Overview: 30-day deterministic Monte Carlo forecast chart (P10/P50/P90), breach risk,
   cash buffer threshold, day contributors inspector, actionable follow-up queue, and Strands check.
2. Cases: Invoice cases, recipient permissions, chronological message logs, and audit timeline.
3. Decisions: Exception cards for owner approval/rejection (disputes, allocations).
4. Data & Settings: Workspace buffer tuning, resettable simulation controls, and inbound email tests.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from typing import Any

# Ensure apps/api and packages are in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
API_DIR = os.path.join(BASE_DIR, "apps", "api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)
FORECAST_DIR = os.path.join(BASE_DIR, "packages", "forecasting")
if FORECAST_DIR not in sys.path:
    sys.path.insert(0, FORECAST_DIR)
AGENT_DIR = os.path.join(BASE_DIR, "packages", "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.audit import record_audit, utcnow
from app.cases import apply_state
from app.config import settings
from app.db import SessionLocal, init_db
from app.deps import get_workspace
from app.email_adapter import persist_inbound
from app.ledger import create_allocation, invoice_outstanding, payment_status
from app.models import (
    Approval,
    ApprovalStatus,
    AuditEvent,
    CollectionCase,
    CollectionState,
    Customer,
    ForecastRun,
    ImportBatch,
    Invoice,
    Job,
    Message,
    Payment,
    ProvenanceType,
    Workspace,
    WorkspaceMode,
)
from app.seed import seed_workspace
from app.services.forecast_service import latest_snapshot
from app.services.orchestration import run_workspace_agent
from app.services.ranking import rank_followups, refresh_cases

st.set_page_config(
    page_title="RunwayKeeper — Cash-Flow Operations Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom minimal theme styling matching Call-E aesthetic
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #0f172a;
    }
    
    .stMetric {
        background-color: #ffffff;
        border: 1px solid #f1f5f9;
        padding: 14px 18px;
        border-radius: 12px;
        box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.03);
    }
    .stMetric label {
        font-size: 11px !important;
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 0.04em;
        color: #64748b !important;
    }
    .stMetric [data-testid="stMetricValue"] {
        font-size: 26px !important;
        font-weight: 700;
        color: #0f172a;
        font-family: 'JetBrains Mono', monospace;
    }
    
    .status-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 9999px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: -0.01em;
    }
    .status-sim {
        background-color: #fef3c7;
        color: #92400e;
        border: 1px solid #fde68a;
    }
    .status-conn {
        background-color: #f0fdfa;
        color: #115e59;
        border: 1px solid #ccfbf1;
    }
    .card-box {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def format_money(minor: int | None, currency: str = "USD") -> str:
    if minor is None:
        return "—"
    sign = "-" if minor < 0 else ""
    val = abs(minor) / 100.0
    return f"{sign}${val:,.2f}"


def get_db_session():
    init_db()
    db = SessionLocal()
    seed_workspace(db, reset=False)
    return db


def get_demo_workspace(db) -> Workspace:
    ws = (
        db.query(Workspace)
        .filter(Workspace.api_key == settings.demo_api_key)
        .first()
    )
    if ws is None:
        ws = db.query(Workspace).first()
    return ws


# ==========================================
# SIDEBAR NAVIGATION & RUNWAY SUMMARY
# ==========================================
db = get_db_session()
try:
    workspace = get_demo_workspace(db)

    with st.sidebar:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                <div style="width: 10px; height: 10px; border-radius: 50%; background-color: #0d9488;"></div>
                <span style="font-weight: 700; font-size: 17px; letter-spacing: -0.02em;">RunwayKeeper</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        mode_badge = "status-sim" if workspace.mode == "simulation" else "status-conn"
        mode_label = "SIMULATION MODE" if workspace.mode == "simulation" else "CONNECTED"
        st.markdown(
            f'<span class="status-pill {mode_badge}">{mode_label}</span>',
            unsafe_allow_html=True,
        )
        st.caption(f"Workspace: **{workspace.name}**")

        st.divider()

        view = st.radio(
            "Navigate",
            ["Overview", "Invoice Cases", "Decisions & Approvals", "Data & Settings"],
            index=0,
            label_visibility="collapsed",
        )

        st.divider()

        st.caption("**Autonomous Strands Check**")
        if st.button("⚡ Run Autonomous Agent", use_container_width=True, type="primary"):
            with st.spinner("Strands executing decision tools..."):
                res = run_workspace_agent(db, workspace, trigger="manual")
                db.commit()
                st.session_state["last_agent_run"] = res
            st.success(f"Executed: {res.get('action')}")
            st.rerun()

        if "last_agent_run" in st.session_state:
            last_run = st.session_state["last_agent_run"]
            with st.expander("Recent Agent Audit", expanded=False):
                st.caption(f"Action: `{last_run.get('action')}`")
                st.caption(f"Requires Owner: `{last_run.get('requires_owner')}`")
                st.caption(f"Tools invoked: {len(last_run.get('tool_calls', []))}")
                if last_run.get("rationale"):
                    st.write(last_run.get("rationale"))

# ==========================================
# PAGE 1: OVERVIEW & FORECAST
# ==========================================
    if view == "Overview":
        snap = latest_snapshot(db, workspace)
        forecast_run = (
            db.query(ForecastRun)
            .filter(ForecastRun.workspace_id == workspace.id, ForecastRun.is_what_if.is_(False))
            .order_by(ForecastRun.created_at.desc())
            .first()
        )
        forecast_res = forecast_run.result if forecast_run else None

        outstanding = sum(
            invoice_outstanding(db, inv)
            for inv in db.query(Invoice).filter(Invoice.workspace_id == workspace.id)
        )
        current_cash = snap.balance_minor if snap else 0
        buffer_minor = workspace.buffer_minor
        breach_prob = forecast_res.get("breach_probability", 0) if forecast_res else 0
        path_min = forecast_res.get("median_path_minimum_minor", 0) if forecast_res else 0

        # Top 4 Metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Current Cash Balance", format_money(current_cash))
        with col2:
            st.metric(
                "Projected Path Min (30d)",
                format_money(path_min),
                delta=f"Buffer: {format_money(buffer_minor)}",
                delta_color="normal" if path_min >= buffer_minor else "inverse",
            )
        with col3:
            st.metric("Buffer Shortfall Risk", f"{breach_prob * 100:.1f}%")
        with col4:
            st.metric("Outstanding Invoices", format_money(outstanding))

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        # Main Forecast Interactive Chart
        st.subheader("30-Day Daily Cash Forecast")
        st.caption(
            "Deterministic numerical simulation (2,000 scenarios with empirical Kaplan–Meier survival arrivals). "
            "Hover or click points to inspect daily inflows and expenses."
        )

        if forecast_res and "days" in forecast_res and forecast_res["days"]:
            days_data = forecast_res["days"]
            df = pd.DataFrame(days_data)
            x = df["day"].tolist()
            p10 = [v / 100.0 for v in df["p10_minor"]]
            p50 = [v / 100.0 for v in df["p50_minor"]]
            p90 = [v / 100.0 for v in df["p90_minor"]]
            buffer_line = [buffer_minor / 100.0] * len(x)

            fig = go.Figure()

            # P90 line
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=p90,
                    mode="lines",
                    line=dict(width=0),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            # P10 with fill to P90
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=p10,
                    mode="lines",
                    fill="tonexty",
                    fillcolor="rgba(13, 148, 136, 0.12)",
                    line=dict(width=0),
                    name="P10 – P90 Confidence Band",
                    hoverinfo="skip",
                )
            )
            # P50 Median Line
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=p50,
                    mode="lines",
                    line=dict(color="#0f172a", width=2.5),
                    name="Median Cash Path (P50)",
                    hovertemplate="%{x}<br>Median: $%{y:,.0f}<extra></extra>",
                )
            )
            # Required Buffer Line
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=buffer_line,
                    mode="lines",
                    line=dict(color="#dc2626", width=1.5, dash="dot"),
                    name="Required Buffer Threshold",
                    hovertemplate="Buffer: $%{y:,.0f}<extra></extra>",
                )
            )

            # Shared delay path if available
            if "shared_delay_path" in forecast_res and len(forecast_res["shared_delay_path"]) == len(x):
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=[v / 100.0 for v in forecast_res["shared_delay_path"]],
                        mode="lines",
                        line=dict(color="#ea580c", width=1.5, dash="dash"),
                        name="Correlated Delay Stress Path",
                        hovertemplate="Late Arrival Stress: $%{y:,.0f}<extra></extra>",
                    )
                )

            fig.update_layout(
                height=340,
                margin=dict(l=20, r=20, t=10, b=30),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11, color="#64748b")),
                yaxis=dict(showgrid=True, gridcolor="#f1f5f9", tickfont=dict(size=11, color="#64748b"), tickprefix="$"),
                legend=dict(orientation="h", y=-0.2, x=0, font=dict(size=11, color="#475569")),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

            # Day breakdown selector
            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            col_sel, col_detail = st.columns([1, 3])
            with col_sel:
                selected_day = st.selectbox("Inspect Contributors for Date", x, index=min(4, len(x) - 1))
            with col_detail:
                day_row = next((d for d in days_data if d["day"] == selected_day), None)
                if day_row and day_row.get("contributors"):
                    st.caption(f"**Scheduled Flows for {selected_day} (Median Projected: {format_money(day_row['p50_minor'])})**")
                    for c in day_row["contributors"]:
                        color = "#0d9488" if c["amount_minor"] > 0 else "#dc2626"
                        st.markdown(
                            f"<div style='font-size: 13px; margin-bottom: 4px; display: flex; justify-content: space-between;'>"
                            f"<span>• {c['label']} <span style='color: #94a3b8;'>({c['timing_note']})</span></span>"
                            f"<span style='font-family: monospace; font-weight: 600; color: {color};'>{format_money(c['amount_minor'])}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info(f"No explicit inflows or expenses scheduled on {selected_day}.")

            if "scenario_disclaimer" in forecast_res:
                st.caption(forecast_res["scenario_disclaimer"])
        else:
            st.info("No forecast runs found. Click 'Run Autonomous Agent' to compute.")

        st.divider()

        # Prioritized Follow-up Queue
        st.subheader("Actionable Follow-up Queue")
        st.caption("Ranked by cash-gap sensitivity (impact on maximum projected cash deficit), then days overdue.")

        ranked_cases = rank_followups(db, workspace)
        if ranked_cases:
            for item in ranked_cases:
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(
                            f"**`{item['external_reference']}`** — {item['customer_name']} "
                            f"<span class='status-pill status-sim'>{item['collection_state']}</span>",
                            unsafe_allow_html=True,
                        )
                        st.caption(f"{item['priority_reason']}")
                    with c2:
                        st.markdown(
                            f"<div style='text-align: right;'>"
                            f"<div style='font-family: monospace; font-weight: 700; font-size: 16px;'>{format_money(item['outstanding_minor'])}</div>"
                            f"<div style='color: #0d9488; font-size: 12px; font-weight: 600;'>+{format_money(item['cash_gap_sensitivity_minor'])} sensitivity</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    st.markdown("<div style='height: 4px; border-bottom: 1px solid #f1f5f9; margin-bottom: 8px;'></div>", unsafe_allow_html=True)
        else:
            st.info("No eligible overdue cases after cooldown and recipient verification filters.")

# ==========================================
# PAGE 2: INVOICE CASES & PROVENANCE
# ==========================================
    elif view == "Invoice Cases":
        st.subheader("Invoice Cases & Auditable Provenance")
        st.caption("Inspect live collection states, recipient verification guards, chronological messages, and immutable ledger balance.")

        refresh_cases(db, workspace)
        db.commit()

        cases = (
            db.query(CollectionCase)
            .filter(CollectionCase.workspace_id == workspace.id)
            .all()
        )
        case_options = {}
        for c in cases:
            inv = db.get(Invoice, c.invoice_id)
            cust = db.get(Customer, inv.customer_id) if inv else None
            label = f"{inv.external_reference} — {cust.display_name if cust else 'Unknown'} ({c.collection_state})"
            case_options[label] = c.id

        if not case_options:
            st.info("No collection cases in this workspace.")
        else:
            col_list, col_view = st.columns([1, 2])
            with col_list:
                selected_label = st.radio("Select Case", list(case_options.keys()))
                selected_case_id = case_options[selected_label]

            with col_view:
                case = db.get(CollectionCase, selected_case_id)
                inv = db.get(Invoice, case.invoice_id)
                cust = db.get(Customer, inv.customer_id)
                outstanding = invoice_outstanding(db, inv)
                status = payment_status(db, inv)

                st.markdown(f"### `{inv.external_reference}`")
                st.caption(f"Customer: **{cust.display_name}** (`{cust.email}`)")

                # Metric cards
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Outstanding Balance", format_money(outstanding))
                with m2:
                    st.metric("Payment Status", status.upper())
                with m3:
                    st.metric("Cash-Gap Sensitivity", f"+{format_money(case.cash_gap_sensitivity_minor)}")

                # Recipient permission card
                is_opted_in = cust.email_verified and cust.contact_permission
                perm_badge = "✅ Verified & Opted-In" if is_opted_in else "⚠️ Unverified or Opt-Out"
                st.markdown(
                    f"<div class='card-box'><strong>Recipient Permissions:</strong> {perm_badge} "
                    f"<span style='color: #64748b; font-size: 12px;'>(Reminders sent: {case.reminder_count}/{workspace.max_reminders_per_case})</span></div>",
                    unsafe_allow_html=True,
                )

                # Chronological Messages
                st.markdown("#### Message Thread & Captures")
                msgs = (
                    db.query(Message)
                    .filter(Message.workspace_id == workspace.id, Message.case_id == case.id)
                    .order_by(Message.source_ts.desc())
                    .all()
                )
                if msgs:
                    for m in msgs:
                        badge = "Outbound Reminder" if m.direction == "outbound" else "Inbound Reply"
                        sim_label = " (Simulated Capture — Not Real Delivery)" if m.is_simulation else ""
                        with st.container():
                            st.markdown(
                                f"**{badge}**: `{m.subject}` <span style='font-size: 11px; color: #64748b;'>{sim_label}</span>",
                                unsafe_allow_html=True,
                            )
                            st.code(m.body_excerpt, language="text")
                            st.caption(f"Status: `{m.delivery_status}` | At: `{m.source_ts}`")
                else:
                    st.caption("No messages captured on this case.")

                # Audit Timeline
                st.markdown("#### Audit Event Timeline")
                audits = (
                    db.query(AuditEvent)
                    .filter(AuditEvent.workspace_id == workspace.id, AuditEvent.entity_id == case.id)
                    .order_by(AuditEvent.created_at.desc())
                    .all()
                )
                if audits:
                    for a in audits:
                        st.markdown(
                            f"• **`{a.event_type}`** (v{a.case_version or 1}) — `{a.created_at}`<br>"
                            f"<span style='font-size: 12px; color: #64748b;'>Payload: {a.payload}</span>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption("No audit entries yet.")

# ==========================================
# PAGE 3: DECISIONS & APPROVALS
# ==========================================
    elif view == "Decisions & Approvals":
        st.subheader("Owner Decisions & Approvals")
        st.caption(
            "RunwayKeeper isolates exceptions requiring owner judgment: disputed balances, amount or term adjustments, and ambiguous payment matches."
        )

        approvals = (
            db.query(Approval)
            .filter(Approval.workspace_id == workspace.id)
            .order_by(Approval.created_at.desc())
            .all()
        )

        if not approvals:
            st.info("No approval cards currently pending. Standard follow-ups operate autonomously under strict policy bounds.")
        else:
            for apprv in approvals:
                with st.container():
                    st.markdown(f"<div class='card-box'>", unsafe_allow_html=True)
                    col_info, col_status = st.columns([3, 1])
                    with col_info:
                        st.markdown(f"**[{apprv.kind.upper()}] {apprv.title}**")
                        st.write(apprv.summary)
                    with col_status:
                        st.markdown(
                            f"<div style='text-align: right;'>"
                            f"<span class='status-pill status-sim'>{apprv.status.upper()}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                    if apprv.proposed_payload:
                        st.caption("Proposed Action Payload:")
                        st.json(apprv.proposed_payload)

                    if apprv.status == ApprovalStatus.PENDING.value:
                        col_rej, col_app = st.columns([1, 1])
                        with col_rej:
                            if st.button("❌ Reject", key=f"rej_{apprv.id}", use_container_width=True):
                                apprv.status = ApprovalStatus.REJECTED.value
                                apprv.decided_at = utcnow()
                                db.commit()
                                st.success("Rejected card.")
                                st.rerun()
                        with col_app:
                            if st.button("✅ Approve", key=f"app_{apprv.id}", type="primary", use_container_width=True):
                                apprv.status = ApprovalStatus.APPROVED.value
                                apprv.decided_at = utcnow()
                                # Handle approval action (e.g. disputed_balance)
                                if apprv.kind == "disputed_balance" and apprv.case_id:
                                    c = db.get(CollectionCase, apprv.case_id)
                                    if c:
                                        apply_state(db, workspace, c, CollectionState.CLOSED.value, reason="owner approved dispute resolution")
                                db.commit()
                                st.success("Approved card.")
                                st.rerun()

                    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# PAGE 4: DATA, SETTINGS & SIMULATION
# ==========================================
    elif view == "Data & Settings":
        st.subheader("Data, Imports & Settings")
        st.caption("Tune required cash buffers, test inbound simulation events, and review durable job logs.")

        col_left, col_right = st.columns(2)

        # Policy Controls
        with col_left:
            st.markdown("#### Workspace Policy")
            curr_buffer_dollars = (workspace.buffer_minor or 0) / 100.0
            new_buffer = st.number_input(
                "Required Cash Buffer ($)",
                min_value=0.0,
                value=float(curr_buffer_dollars),
                step=1000.0,
            )
            if st.button("Save Buffer Requirement"):
                workspace.buffer_minor = int(round(new_buffer * 100))
                db.commit()
                st.success(f"Updated cash buffer to ${new_buffer:,.2f}")
                st.rerun()

            st.caption(f"Reminder Cooldown: `{workspace.reminder_cooldown_hours}h` (Max `{workspace.max_reminders_per_case}` reminders per case)")
            st.caption(f"Email Mode: **{workspace.mode.upper()}**")

            st.divider()

            st.markdown("#### Resettable Simulation")
            st.caption("Reset database state back to the fictional Harbour Studio demo seed.")
            if st.button("🔄 Reset Seed Agency", type="secondary"):
                seed_workspace(db, reset=True)
                st.success("Successfully reset workspace to initial demo seed.")
                st.rerun()

        # Inbound Simulation Tester
        with col_right:
            st.markdown("#### Inbound Email Simulator")
            st.caption("Simulate an inbound email reply to trigger Strands triage without live webhooks.")

            with st.form("inbound_sim_form"):
                from_email = st.text_input("From Email", value="ap@northwind.test")
                inv_ref = st.text_input("Invoice Reference", value="INV-1042")
                email_body = st.text_area(
                    "Message Body",
                    value="This invoice was already paid. Reference INV-1042.",
                    height=100,
                )
                submitted = st.form_submit_button("Send Inbound Event", type="primary")

            if submitted:
                with st.spinner("Processing inbound message through Strands..."):
                    # Resolve case
                    inv_match = db.query(Invoice).filter(Invoice.workspace_id == workspace.id, Invoice.external_reference == inv_ref.strip()).first()
                    case_match = db.query(CollectionCase).filter(CollectionCase.invoice_id == inv_match.id).first() if inv_match else None
                    case_id = case_match.id if case_match else None

                    # Persist message
                    persist_inbound(
                        db,
                        workspace,
                        from_email=from_email,
                        to_email="inbox@harbor.simulation",
                        subject=f"Re: {inv_ref}",
                        body=email_body,
                        provider_message_id=f"sim-{utcnow().timestamp()}",
                        case_id=case_id,
                    )

                    # Trigger Strands agent
                    agent_res = run_workspace_agent(
                        db,
                        workspace,
                        trigger="inbound_email",
                        case_id=case_id,
                        inbound_excerpt=email_body[:400],
                    )

                    # Check unambiguous already paid
                    if "already paid" in email_body.lower() and case_id:
                        from app.ledger import find_unambiguous_match
                        payment, matched, reason = find_unambiguous_match(
                            db,
                            workspace,
                            customer_id=inv_match.customer_id,
                            currency=inv_match.currency,
                            amount_minor=invoice_outstanding(db, inv_match) or inv_match.gross_amount_minor,
                            reference=inv_match.external_reference,
                        )
                        if payment and matched:
                            create_allocation(
                                db,
                                workspace,
                                payment=payment,
                                invoice=matched,
                                amount_minor=min(payment.amount_minor, invoice_outstanding(db, matched) or payment.amount_minor),
                                evidence={"rule": "unambiguous_already_paid", "reason": reason},
                                source_id=f"inbound-alloc:{payment.id}",
                                source_ts=utcnow(),
                                provenance=ProvenanceType.SIMULATED.value,
                            )
                            agent_res["reconciled"] = True
                    db.commit()

                st.success(f"Agent Action: {agent_res.get('action')}")
                st.json(agent_res)

        st.divider()

        # Recent Background Jobs
        st.markdown("#### Durable Background Jobs")
        recent_jobs = (
            db.query(Job)
            .filter(Job.workspace_id == workspace.id)
            .order_by(Job.created_at.desc())
            .limit(10)
            .all()
        )
        if recent_jobs:
            job_rows = [
                {
                    "Type": j.job_type,
                    "Status": j.status,
                    "Attempts": f"{j.attempts}/{j.max_attempts}",
                    "Run After": str(j.run_after),
                    "Created": str(j.created_at),
                }
                for j in recent_jobs
            ]
            st.dataframe(pd.DataFrame(job_rows), use_container_width=True)
        else:
            st.caption("No jobs queued.")

finally:
    db.close()
