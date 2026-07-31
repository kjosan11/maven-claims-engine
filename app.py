"""Maven Claims Engine — Streamlit portfolio app.

Three pages, navigated from the sidebar:
  1. Adjudication Dashboard — Phase 1 rules-engine output
  2. Reconciliation Dashboard — Phase 2 payment reconciliation output
  3. Claims Explorer — filterable merged claim detail
"""

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Maven Claims Engine", layout="wide")

# ---------------------------------------------------------------------------
# Maven Clinic brand colors.
# ---------------------------------------------------------------------------
CHART_SURFACE = "#fcfcfb"
GRIDLINE = "#e1e0d9"
INK_PRIMARY = "#0b0b0b"

BRAND_PRIMARY = "#1B5E3B"
BRAND_ERROR = "#E8534A"
BRAND_AMBER = "#F59E0B"
BRAND_BLUE = "#3B82F6"

# Reason codes chart intentionally excludes APPROVED — this chart is about
# denial/discrepancy drivers, not the approval baseline.
REASON_CODE_COLORS = {
    "DEDUCTIBLE_NOT_MET": BRAND_PRIMARY,
    "OUT_OF_NETWORK": BRAND_PRIMARY,
    "UNCOVERED_SERVICE": BRAND_ERROR,
    "MISSING_PRIOR_AUTH": BRAND_ERROR,
}

DECISION_COLORS = {"approve": BRAND_PRIMARY, "partial": BRAND_PRIMARY, "deny": BRAND_ERROR}

RECON_STATUS_COLORS = {
    "reconciled": BRAND_PRIMARY,
    "underpayment": BRAND_AMBER,
    "missing_payment": BRAND_BLUE,
    "duplicate_payment": BRAND_ERROR,
    "erroneous_payment": BRAND_ERROR,
}

ROW_HIGHLIGHT_COLORS = {"approve": "#E8F5E9", "partial": "#FFF3E0", "deny": "#FFEBEE"}

MAVEN_LOGO_URL = "https://cdn.prod.website-files.com/5fb2b678e994739660d95086/68128420e1f9aec4f84cd81c_img-maven-true-green-logo.svg"

st.markdown(
    """
    <style>
    html, body, [class*="css"]  {
        font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    }

    /* Sidebar branding */
    [data-testid="stSidebar"] {
        background-color: #1B5E3B;
    }
    [data-testid="stSidebar"] * {
        color: #FFFFFF;
    }
    .sidebar-header-title {
        color: #FFFFFF;
        font-weight: 700;
        font-size: 1.3rem;
        margin-bottom: 0.1rem;
    }
    .sidebar-header-subtitle {
        color: rgba(255, 255, 255, 0.75);
        font-size: 0.8rem;
        margin-bottom: 1rem;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        padding: 0.5rem 0;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
        font-weight: 700;
    }

    /* Headings */
    h1, h2, h3 {
        color: #1B5E3B;
        font-weight: 700;
    }
    .page-subtitle {
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.75rem;
        color: #6B7280;
        margin-top: -0.5rem;
        margin-bottom: 0.5rem;
    }
    .page-title-rule {
        border: none;
        border-top: 2px solid #1B5E3B;
        margin: 0.5rem 0 0.25rem 0;
    }

    /* Metric cards */
    [data-testid="stMetricLabel"] {
        color: #1B5E3B;
    }
    [data-testid="stMetricValue"] {
        color: #1B5E3B;
        font-size: 2rem;
        font-weight: 700;
    }

    /* Card-style section containers (targeted via st.container(key=...)) */
    [class*="st-key-card_"] {
        background: #FFFFFF;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        border: none;
    }

    /* AI Operational Briefing callout */
    .ai-briefing {
        background: #F0F7F4;
        border-left: 4px solid #1B5E3B;
        border-radius: 4px;
        padding: 1rem;
        margin-top: 0.5rem;
        margin-bottom: 1rem;
    }
    .ai-briefing-label {
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: #1B5E3B;
        text-transform: uppercase;
        margin-bottom: 0.4rem;
    }
    .ai-briefing-text {
        font-size: 0.95rem;
        line-height: 1.55;
        color: #0b0b0b;
        font-style: italic;
    }

    .app-footer {
        text-align: center;
        font-size: 0.8rem;
        color: #9CA3AF;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def spacer():
    st.markdown('<div style="margin: 2rem 0"></div>', unsafe_allow_html=True)


def page_header(title, subtitle):
    st.title(title)
    st.markdown(f'<div class="page-subtitle">{subtitle}</div>', unsafe_allow_html=True)
    st.markdown('<hr class="page-title-rule" />', unsafe_allow_html=True)


def footer():
    spacer()
    st.markdown(
        '<div class="app-footer">Maven Claims Engine &middot; Internal Operations Platform &middot; Built with Claude</div>',
        unsafe_allow_html=True,
    )


def style_bar_chart(fig, y_title=""):
    """Apply consistent chrome to every bar chart in the app."""
    fig.update_traces(textposition="outside", marker_line_width=0, cliponaxis=False)
    fig.update_layout(
        plot_bgcolor=CHART_SURFACE,
        paper_bgcolor=CHART_SURFACE,
        font_color=INK_PRIMARY,
        showlegend=False,
        margin=dict(t=20, b=10, l=10, r=10),
        xaxis=dict(title="", showgrid=False, linecolor=GRIDLINE),
        yaxis=dict(title=y_title, gridcolor=GRIDLINE, zerolinecolor=GRIDLINE),
    )
    return fig


def ai_briefing_box(text):
    st.markdown(
        f"""
        <div class="ai-briefing">
            <div class="ai-briefing-label">AI Operational Briefing</div>
            <div class="ai-briefing-text">{text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data
def load_csv(path):
    return pd.read_csv(path)


@st.cache_data
def load_text(path):
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Page 1: Adjudication Dashboard
# ---------------------------------------------------------------------------
def render_adjudication_dashboard():
    page_header("Adjudication Dashboard", "Phase 1 — rules-engine claim decisions")

    df = load_csv("output/adjudication_results.csv")

    with st.container(border=True, key="card_p1_metrics"):
        total_claims = len(df)
        approval_rate = (df["decision"] == "approve").mean()
        total_approved = df["approved_amount"].sum()
        total_member_resp = df["member_responsibility"].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Claims", f"{total_claims:,}")
        c2.metric("Approval Rate", f"{approval_rate:.1%}")
        c3.metric("Total Approved Amount", f"${total_approved:,.2f}")
        c4.metric("Total Member Responsibility", f"${total_member_resp:,.2f}")

    spacer()

    with st.container(border=True, key="card_p1_charts"):
        st.divider()
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Claims by Decision")
            decision_counts = (
                df["decision"].value_counts()
                .reindex(["approve", "partial", "deny"]).fillna(0).astype(int).reset_index()
            )
            decision_counts.columns = ["decision", "count"]
            fig = px.bar(
                decision_counts, x="decision", y="count", text="count",
                color="decision", color_discrete_map=DECISION_COLORS,
            )
            st.plotly_chart(style_bar_chart(fig, "Claims"))

        with col_b:
            st.subheader("Top Reason Codes by Volume")
            reason_counts = (
                df[df["reason_code"] != "APPROVED"]["reason_code"]
                .value_counts().reset_index()
            )
            reason_counts.columns = ["reason_code", "count"]
            fig = px.bar(
                reason_counts, x="reason_code", y="count", text="count",
                color="reason_code", color_discrete_map=REASON_CODE_COLORS,
            )
            st.plotly_chart(style_bar_chart(fig, "Claims"))

    spacer()

    with st.container(border=True, key="card_p1_briefing"):
        ai_briefing_box(load_text("output/adjudication_summary.txt"))

    footer()


# ---------------------------------------------------------------------------
# Page 2: Reconciliation Dashboard
# ---------------------------------------------------------------------------
def render_reconciliation_dashboard():
    page_header("Reconciliation Dashboard", "Phase 2 — payment reconciliation against adjudicated claims")

    df = load_csv("output/reconciliation_results.csv")

    with st.container(border=True, key="card_p2_metrics"):
        total = len(df)
        total_reconciled = (df["reconciliation_status"] == "reconciled").sum()
        total_discrepancies = total - total_reconciled
        total_underpayments = (df["reconciliation_status"] == "underpayment").sum()
        total_clawbacks = df["reconciliation_status"].isin(["duplicate_payment", "erroneous_payment"]).sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Reconciled", f"{total_reconciled:,}")
        c2.metric("Total Discrepancies", f"{total_discrepancies:,}")
        c3.metric("Total Underpayments", f"{total_underpayments:,}")
        c4.metric("Total Clawbacks Needed", f"{total_clawbacks:,}")

    spacer()

    with st.container(border=True, key="card_p2_charts"):
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Reconciliation Status by Count")
            status_order = ["reconciled", "underpayment", "missing_payment", "duplicate_payment", "erroneous_payment"]
            status_counts = (
                df["reconciliation_status"].value_counts()
                .reindex(status_order).fillna(0).astype(int).reset_index()
            )
            status_counts.columns = ["reconciliation_status", "count"]
            fig = px.bar(
                status_counts, x="reconciliation_status", y="count", text="count",
                color="reconciliation_status", color_discrete_map=RECON_STATUS_COLORS,
            )
            st.plotly_chart(style_bar_chart(fig, "Claims"))

        with col_b:
            st.subheader("Dollar Variance by Discrepancy Type")
            discrepancy_order = ["underpayment", "missing_payment", "duplicate_payment", "erroneous_payment"]
            variance = (
                df[df["reconciliation_status"] != "reconciled"]
                .groupby("reconciliation_status")["dollar_variance"].sum()
                .reindex(discrepancy_order).fillna(0.0).reset_index()
            )
            # Diverging encoding: positive variance is still owed to the payer
            # side, negative variance is an overpayment that needs recovery.
            variance["direction"] = variance["dollar_variance"].apply(
                lambda v: "Owed to Payer" if v >= 0 else "Overpaid (Recover)"
            )
            variance["label"] = variance["dollar_variance"].apply(lambda v: f"${v:,.2f}")
            fig = px.bar(
                variance, x="reconciliation_status", y="dollar_variance", text="label",
                color="direction",
                color_discrete_map={"Owed to Payer": BRAND_PRIMARY, "Overpaid (Recover)": BRAND_ERROR},
            )
            fig.add_hline(y=0, line_color=GRIDLINE)
            styled = style_bar_chart(fig, "Dollar Variance ($)")
            styled.update_layout(showlegend=True, legend_title_text="")
            st.plotly_chart(styled)

    spacer()

    with st.container(border=True, key="card_p2_queue"):
        st.subheader("\U0001F534 Priority Action Queue")
        st.caption("Claims that are not fully reconciled, ranked by dollar impact")

        action_queue = (
            df[df["reconciliation_status"] != "reconciled"]
            .sort_values("dollar_variance", ascending=False)
            [["claim_id", "reconciliation_status", "approved_amount", "payment_amount", "dollar_variance", "recommended_action"]]
        )
        total_action_variance = action_queue["dollar_variance"].abs().sum()
        st.markdown(
            f'<div style="color:#E8534A; font-weight:700; margin-bottom:0.75rem;">'
            f'{len(action_queue)} claims require immediate action totaling ${total_action_variance:,.2f} in variance</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(action_queue, use_container_width=True, hide_index=True)

    spacer()

    with st.container(border=True, key="card_p2_briefing"):
        ai_briefing_box(load_text("output/reconciliation_summary.txt"))

    footer()


# ---------------------------------------------------------------------------
# Page 3: Claims Explorer
# ---------------------------------------------------------------------------
EXPLORER_PRIORITY_COLUMNS = [
    "claim_id", "member_id", "employer_id", "payer_id", "decision",
    "reason_code", "approved_amount", "member_responsibility", "billed_amount",
]

EXPLORER_WIDGET_KEYS = [
    "explorer_member_search", "explorer_plan_type", "explorer_decision",
    "explorer_network_status", "explorer_employer", "explorer_payer",
]


def highlight_by_decision(row):
    color = ROW_HIGHLIGHT_COLORS.get(row["decision"], "")
    return [f"background-color: {color}"] * len(row)


def render_claims_explorer():
    page_header("Claims Explorer", "Full claim detail — adjudication results merged with raw claim attributes")

    adjudication_df = load_csv("output/adjudication_results.csv")
    claims_df = load_csv("data/claims.csv")
    # Both files share member_id/employer_id/payer_id/billed_amount since
    # adjudication_results was derived from claims.csv — drop the duplicates
    # from the raw side rather than carry two copies of the same values.
    merged = adjudication_df.merge(claims_df, on="claim_id", suffixes=("", "_raw"))
    merged = merged.drop(columns=[c for c in merged.columns if c.endswith("_raw")])
    remaining_columns = [c for c in merged.columns if c not in EXPLORER_PRIORITY_COLUMNS]
    merged = merged[EXPLORER_PRIORITY_COLUMNS + remaining_columns]

    with st.container(border=True, key="card_p3_filters"):
        st.subheader("Filters")

        header_col, reset_col = st.columns([5, 1])
        with reset_col:
            if st.button("Reset Filters"):
                for key in EXPLORER_WIDGET_KEYS:
                    st.session_state.pop(key, None)
                st.rerun()

        member_search = st.text_input("Search by Member ID", key="explorer_member_search")

        f1, f2, f3, f4, f5 = st.columns(5)
        plan_types = f1.multiselect(
            "Plan Type", sorted(merged["plan_type"].unique()),
            default=sorted(merged["plan_type"].unique()), key="explorer_plan_type",
        )
        decisions = f2.multiselect(
            "Decision", sorted(merged["decision"].unique()),
            default=sorted(merged["decision"].unique()), key="explorer_decision",
        )
        network_status = f3.multiselect(
            "Network Status", sorted(merged["provider_network_status"].unique()),
            default=sorted(merged["provider_network_status"].unique()), key="explorer_network_status",
        )
        employers = f4.multiselect(
            "Employer", sorted(merged["employer_id"].unique()),
            default=sorted(merged["employer_id"].unique()), key="explorer_employer",
        )
        payers = f5.multiselect(
            "Payer", sorted(merged["payer_id"].unique()),
            default=sorted(merged["payer_id"].unique()), key="explorer_payer",
        )

    filtered = merged[
        merged["plan_type"].isin(plan_types)
        & merged["decision"].isin(decisions)
        & merged["provider_network_status"].isin(network_status)
        & merged["employer_id"].isin(employers)
        & merged["payer_id"].isin(payers)
    ]
    if member_search:
        filtered = filtered[filtered["member_id"].str.contains(member_search, case=False, na=False)]

    spacer()

    with st.container(border=True, key="card_p3_table"):
        st.markdown(
            f'<div style="color:#1B5E3B; font-weight:700; font-size:1.1rem; margin-bottom:0.75rem;">'
            f'Showing {len(filtered):,} of {len(merged):,} claims</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(filtered.style.apply(highlight_by_decision, axis=1), use_container_width=True, hide_index=True)

    footer()


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.markdown(
    f"""
    <img src="{MAVEN_LOGO_URL}" style="width: 140px; filter: invert(1) brightness(2); margin-bottom: 0.75rem;" />
    <div class="sidebar-header-title">Maven Claims Engine</div>
    <div class="sidebar-header-subtitle">Internal Operations Platform</div>
    """,
    unsafe_allow_html=True,
)
page = st.sidebar.radio(
    "Navigate", ["Adjudication Dashboard", "Reconciliation Dashboard", "Claims Explorer"]
)

if page == "Adjudication Dashboard":
    render_adjudication_dashboard()
elif page == "Reconciliation Dashboard":
    render_reconciliation_dashboard()
else:
    render_claims_explorer()
