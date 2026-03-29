"""
Securities Finance Pricer

Indicative desk prototype for Securities Lending and Repo.
Not a production pricer. All outputs are illustrative.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Try to import yfinance. The app works fine if it is not available.
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


# ============================================================
# BASE LAYER
# Shared reference data and helper functions used by both tabs.
# ============================================================

# Each instrument has a base sourcing ease score.
# High score = abundant, easy to source.
# Low score  = scarce, hard to find.
INSTRUMENT_BASE_SCORE = {
    "Sovereign core (US, DE, FR)": {"score": 85, "is_bond": True},
    "IG corporate bond":           {"score": 60, "is_bond": True},
    "HY corporate bond":           {"score": 28, "is_bond": True},
    "Large cap equity (index)":    {"score": 75, "is_bond": False},
    "Mid cap equity":              {"score": 48, "is_bond": False},
    "Small cap equity":            {"score": 20, "is_bond": False},
    "Liquid ETF":                  {"score": 80, "is_bond": False},
}

# Repo is economically most relevant for bond collateral.
# This list is used only inside the repo tab.
REPO_INSTRUMENTS = [
    "Sovereign core (US, DE, FR)",
    "IG corporate bond",
    "HY corporate bond",
]

# Market modifier: deeper markets are easier to source from.
MARKET_MODIFIER = {
    "US":                          10,
    "Europe core (DE, FR, NL)":     8,
    "UK":                           5,
    "Japan":                        3,
    "Europe periphery (IT, ES)":   -5,
    "Emerging markets":           -15,
}

# Size modifier: larger issues have more supply and are easier to source.
# Smaller issues are thinner and harder to find in size.
SIZE_MODIFIER = {
    "Large (> EUR 5bn / large cap)":    8,
    "Medium (EUR 1-5bn / mid cap)":     0,
    "Small (< EUR 1bn / small cap)":   -10,
}

# Borrow demand is the main driver of lending fee.
# Higher demand means the stock is scarcer and more expensive to borrow.
BORROW_DEMAND_MODIFIER = {
    "Low  (<20% utilisation)":          15,
    "Moderate (20-50% utilisation)":     0,
    "High (50-80% utilisation)":       -15,
    "Very high / Special (>80%)":      -30,
}

# Bond rating modifier on sourcing ease.
RATING_MODIFIER = {
    "AAA / AA":  10,
    "A":          5,
    "BBB":        0,
    "BB":        -8,
    "B / CCC":  -18,
    "NR":        -12,
}

# On-the-run bonds have more supply and are generally easier to source.
OTR_MODIFIER = {
    "On-the-run":      8,
    "Off-the-run":     0,
    "Old benchmark":  -5,
}

# Scarcity modifier for repo collateral.
# The more scarce the collateral, the more special the repo trade.
SCARCITY_MODIFIER = {
    "Not scarce (GC)":      0,
    "Slightly scarce":    -15,
    "Scarce (Special)":   -35,
    "Very scarce (HTB)":  -60,
}

# Lending fee bands (bps per year, annualised).
# Higher sourcing ease score => lower borrow fee.
# Lower sourcing ease score  => higher borrow fee.
LENDING_FEE_BANDS = [
    (80, 100,   5,   25, "General Collateral (GC)"),
    (65,  80,  25,   75, "Near GC"),
    (50,  65,  75,  150, "Warm"),
    (35,  50, 150,  350, "Special"),
    (15,  35, 350,  700, "Hard to Borrow"),
    ( 0,  15, 700, 1500, "HTB Extreme"),
]

# Repo specialness bands (bps below GC rate).
# Higher collateral score => close to GC rate, small specialness.
# Lower collateral score  => deep special, repo rate well below GC.
REPO_SPECIALNESS_BANDS = [
    (70, 100,   0,  10, "GC"),
    (45,  70,  10,  40, "Near Special"),
    (20,  45,  40, 150, "Special"),
    ( 0,  20, 150, 400, "Deep Special"),
]


# --- Helper functions -------------------------------------------------------

def fetch_yahoo_data(ticker):
    """
    Fetch basic market data from Yahoo Finance for a given ticker.
    Returns a dict with last price, average volume, and 20-day realised vol.
    Returns None if the fetch fails for any reason.
    Yahoo Finance data is only used here as a rough market proxy.
    """
    if not YFINANCE_AVAILABLE:
        return None
    try:
        hist = yf.Ticker(ticker).history(period="30d")
        if hist.empty:
            return None
        last_price    = round(hist["Close"].iloc[-1], 2)
        avg_volume    = int(hist["Volume"].mean())
        daily_returns = hist["Close"].pct_change().dropna()
        # Annualised realised volatility over the last 20 trading days
        realised_vol  = round(daily_returns.std() * (252 ** 0.5) * 100, 1)
        return {
            "price":   last_price,
            "avg_vol": avg_volume,
            "vol_pct": realised_vol,
        }
    except Exception:
        return None


def compute_sourcing_score(instrument, market, size, borrow_demand, rating=None, otr=None):
    """
    Compute a sourcing ease score from 0 to 100.
    High score = easy to source = GC profile = low borrow fee.
    Low score  = scarce / hard to borrow = Special or HTB = high borrow fee.
    This score is a simplified proxy, not calibrated to real market data.
    """
    score = INSTRUMENT_BASE_SCORE[instrument]["score"]
    score += MARKET_MODIFIER[market]
    # Larger issues have more supply, which makes them easier to source.
    score += SIZE_MODIFIER[size]
    score += BORROW_DEMAND_MODIFIER[borrow_demand]
    is_bond = INSTRUMENT_BASE_SCORE[instrument]["is_bond"]
    # Rating and on-the-run status only apply to bonds
    if is_bond and rating:
        score += RATING_MODIFIER[rating]
    if is_bond and otr:
        score += OTR_MODIFIER[otr]
    return max(0, min(100, score))


def get_lending_fee(score):
    """
    Map a sourcing ease score to an indicative borrow fee in bps per year.
    The fee is interpolated linearly within each band.
    Returns (fee_bps, category_label).
    """
    for lo, hi, fee_lo, fee_hi, label in LENDING_FEE_BANDS:
        if lo <= score <= hi:
            t   = (score - lo) / (hi - lo) if hi != lo else 0
            fee = fee_hi + (fee_lo - fee_hi) * t
            return round(fee, 1), label
    return 1500.0, "HTB Extreme"


def compute_collateral_score(instrument, market, size, scarcity, otr=None):
    """
    Compute a repo collateral quality score from 0 to 100.
    High score = high-quality / abundant collateral = close to GC rate.
    Low score  = scarce / special collateral = repo rate well below GC.
    """
    score = INSTRUMENT_BASE_SCORE[instrument]["score"]
    score += MARKET_MODIFIER[market]
    # Larger bond issues tend to have more lenders and deeper markets.
    score += SIZE_MODIFIER[size]
    if otr:
        score += OTR_MODIFIER[otr]
    # Scarcity is the main driver of specialness in repo
    score += SCARCITY_MODIFIER[scarcity]
    return max(0, min(100, score))


def get_repo_specialness(collateral_score):
    """
    Map a collateral score to a specialness adjustment in bps.
    This adjustment is subtracted from the GC benchmark rate.
    In repo, special collateral trades at a rate BELOW the GC rate.
    Returns (specialness_bps, category_label).
    """
    for lo, hi, adj_lo, adj_hi, label in REPO_SPECIALNESS_BANDS:
        if lo <= collateral_score <= hi:
            t   = (collateral_score - lo) / (hi - lo) if hi != lo else 0
            adj = adj_hi + (adj_lo - adj_hi) * t
            return round(adj, 1), label
    return 400.0, "Deep Special"


# ============================================================
# STREAMLIT APP
# ============================================================

st.set_page_config(page_title="Securities Finance Pricer", layout="wide")

st.title("Securities Finance Pricer")
st.caption("Indicative desk prototype | Not a production pricer")

# Keep Yahoo Finance data across reruns using session state
if "yahoo_data" not in st.session_state:
    st.session_state.yahoo_data = None


# --- SIDEBAR: common inputs shared by both tabs ----------------------------
with st.sidebar:
    st.header("Common Inputs")

    instrument = st.selectbox("Instrument type", list(INSTRUMENT_BASE_SCORE.keys()))
    market     = st.selectbox("Market", list(MARKET_MODIFIER.keys()))
    # Larger issues / larger caps have more supply and are easier to source.
    size       = st.selectbox("Issue size / market cap", list(SIZE_MODIFIER.keys()))
    notional   = st.number_input(
        "Notional (EUR)",
        min_value=100_000,
        max_value=500_000_000,
        value=10_000_000,
        step=1_000_000,
        format="%d",
    )
    tenor = st.slider("Tenor (days)", min_value=1, max_value=365, value=30)

    # Whether the selected instrument is a bond (used in both tabs)
    is_bond = INSTRUMENT_BASE_SCORE[instrument]["is_bond"]

    st.divider()
    st.subheader("Yahoo Finance (optional)")
    st.caption("Fetch basic market data as a liquidity proxy. The app works without it.")
    ticker = st.text_input("Ticker (e.g. AAPL, SIE.DE)", value="")

    if st.button("Fetch market data"):
        if ticker.strip():
            result = fetch_yahoo_data(ticker.strip().upper())
            if result:
                st.session_state.yahoo_data = result
                st.success(f"Data fetched for {ticker.strip().upper()}")
            else:
                st.session_state.yahoo_data = None
                st.warning("Could not fetch data. Using default values.")
        else:
            st.warning("Please enter a ticker first.")

    if st.session_state.yahoo_data:
        st.divider()
        d = st.session_state.yahoo_data
        st.caption("Yahoo Finance data (proxy only)")
        st.metric("Last price", f"{d['price']}")
        st.metric("Avg daily volume", f"{d['avg_vol']:,}")
        st.metric("20d realised vol", f"{d['vol_pct']}%")


yahoo_data = st.session_state.yahoo_data

# --- TABS ------------------------------------------------------------------
tab_lending, tab_repo = st.tabs(["Securities Lending", "Repo"])


# ============================================================
# TAB 1 -- SECURITIES LENDING
# ============================================================
with tab_lending:

    st.subheader("Securities Lending - Borrow Fee Pricer")
    st.caption(
        "Easy-to-source securities trade close to GC with a low borrow fee. "
        "Scarce or highly demanded securities become Special or HTB with a high borrow fee."
    )

    st.markdown("#### Lending inputs")
    col_a, col_b = st.columns(2)

    with col_a:
        borrow_demand = st.selectbox(
            "Borrow demand / utilisation",
            list(BORROW_DEMAND_MODIFIER.keys()),
            help="Higher borrow demand usually means the stock is scarcer and more expensive to borrow.",
        )
        if is_bond:
            rating = st.selectbox("Rating", list(RATING_MODIFIER.keys()))
        else:
            rating = None

    with col_b:
        if is_bond:
            otr = st.selectbox(
                "On-the-run status",
                list(OTR_MODIFIER.keys()),
                help="On-the-run bonds have more supply and are generally easier to source.",
            )
        else:
            otr = None

    # Compute sourcing ease score
    sourcing_score           = compute_sourcing_score(instrument, market, size, borrow_demand, rating, otr)
    borrow_fee_bps, category = get_lending_fee(sourcing_score)

    # Fee calculation: Notional x fee (bps) / 10000 x tenor / 360 (Act/360)
    total_fee     = notional * borrow_fee_bps / 10_000 * tenor / 360
    daily_accrual = notional * borrow_fee_bps / 10_000 / 360

    # Output metrics
    st.divider()
    st.markdown("#### Results")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Sourcing Ease Score", f"{sourcing_score} / 100")
    c2.metric("Category", category)
    c3.metric("Borrow Fee (bps/yr)", f"{borrow_fee_bps}")
    c4.metric("Total Fee", f"EUR {total_fee:,.0f}")
    c5.metric("Daily Accrual", f"EUR {daily_accrual:,.0f}")

    if yahoo_data:
        st.info(
            f"Yahoo Finance proxy -- "
            f"Last price: {yahoo_data['price']} | "
            f"Avg daily volume: {yahoo_data['avg_vol']:,} | "
            f"20d realised vol: {yahoo_data['vol_pct']}%  "
            f"(used as a rough liquidity indicator only)"
        )

    # Score breakdown table
    st.divider()
    st.markdown("#### Score breakdown")

    factors   = ["Instrument (base)", "Market", "Issue size / market cap", "Borrow demand"]
    modifiers = [
        INSTRUMENT_BASE_SCORE[instrument]["score"],
        MARKET_MODIFIER[market],
        SIZE_MODIFIER[size],
        BORROW_DEMAND_MODIFIER[borrow_demand],
    ]
    if is_bond and rating is not None and otr is not None:
        factors   += ["Rating", "On-the-run"]
        modifiers += [RATING_MODIFIER[rating], OTR_MODIFIER[otr]]

    factors.append("TOTAL SCORE (capped 0-100)")
    modifiers.append(sourcing_score)

    st.dataframe(
        pd.DataFrame({"Factor": factors, "Points": modifiers}),
        hide_index=True,
        use_container_width=False,
    )

    # Fee band chart -- active band highlighted in blue
    st.markdown("#### Fee band reference")

    band_labels   = [b[4] for b in LENDING_FEE_BANDS]
    band_mid_fees = [(b[2] + b[3]) / 2 for b in LENDING_FEE_BANDS]
    bar_colors    = ["#1f77b4" if lbl == category else "#d3d3d3" for lbl in band_labels]

    fig_lending = go.Figure(go.Bar(
        x=band_labels,
        y=band_mid_fees,
        marker_color=bar_colors,
        text=[f"{f:.0f} bps" for f in band_mid_fees],
        textposition="outside",
    ))
    fig_lending.update_layout(
        yaxis_title="Indicative mid borrow fee (bps/yr)",
        height=320,
        margin=dict(l=20, r=20, t=10, b=20),
        showlegend=False,
    )
    st.plotly_chart(fig_lending, use_container_width=True)
    st.caption("Active band highlighted in blue. Mid-point of each band shown. Illustrative only.")


# ============================================================
# TAB 2 -- REPO
# Repo is focused on bond collateral. Equity and ETF repo is not
# covered here because the pricing logic and collateral conventions
# are materially different and would require a separate framework.
# ============================================================
with tab_repo:

    st.subheader("Repo - Indicative Rate Pricer")
    st.caption(
        "Repo logic is different from lending logic. "
        "Indicative repo rate = GC benchmark rate - specialness adjustment. "
        "Special collateral trades at a repo rate BELOW the GC benchmark. "
        "This tab covers bond collateral only."
    )

    st.markdown("#### Repo inputs")
    col_r1, col_r2 = st.columns(2)

    with col_r1:
        # Repo uses its own instrument selector, restricted to bonds.
        # Equity and ETF repo has different conventions and is out of scope here.
        repo_instrument = st.selectbox(
            "Bond collateral type",
            REPO_INSTRUMENTS,
        )
        repo_market = st.selectbox("Collateral market", list(MARKET_MODIFIER.keys()), key="repo_market")
        repo_size   = st.selectbox("Issue size", list(SIZE_MODIFIER.keys()), key="repo_size")
        otr_repo    = st.selectbox("On-the-run status", list(OTR_MODIFIER.keys()), key="repo_otr")
        scarcity    = st.selectbox(
            "Collateral scarcity",
            list(SCARCITY_MODIFIER.keys()),
            help="Scarcity is the main driver of repo specialness. Scarce collateral = special repo.",
        )

    with col_r2:
        gc_rate = st.slider(
            "GC benchmark rate (%)",
            min_value=0.0,
            max_value=6.0,
            value=3.50,
            step=0.05,
            help="The GC rate is the starting point. Specialness is then subtracted from it.",
        )
        st.markdown("")
        st.info(
            "**How repo pricing works here:**\n\n"
            "When a borrower pledges scarce (special) collateral, "
            "the cash lender accepts a lower return because the collateral is hard to find elsewhere. "
            "This is why special collateral repos at a rate below GC."
        )

    # Compute collateral score and specialness
    collateral_score               = compute_collateral_score(repo_instrument, repo_market, repo_size, scarcity, otr_repo)
    specialness_bps, repo_category = get_repo_specialness(collateral_score)

    # Core repo pricing formula: repo rate = GC rate - specialness adjustment.
    # Floor at 0 as a demo safeguard -- in real markets, repo rates can go negative.
    repo_rate     = max(0.0, gc_rate - specialness_bps / 100)

    # Repo interest over tenor: Notional x rate x tenor / 360 (Act/360)
    repo_interest = notional * repo_rate / 100 * tenor / 360

    # Output metrics
    st.divider()
    st.markdown("#### Results")

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Collateral Score", f"{collateral_score} / 100")
    r2.metric("Collateral Category", repo_category)
    r3.metric("GC Benchmark Rate", f"{gc_rate:.2f}%")
    r4.metric("Specialness Adj.", f"-{specialness_bps} bps")

    r5, r6 = st.columns(2)
    r5.metric("Indicative Repo Rate", f"{repo_rate:.2f}%")
    r6.metric("Repo Interest (tenor)", f"EUR {repo_interest:,.0f}")

    if yahoo_data:
        st.info(
            f"Yahoo Finance proxy -- "
            f"Last price: {yahoo_data['price']} | "
            f"Avg daily volume: {yahoo_data['avg_vol']:,} | "
            f"20d realised vol: {yahoo_data['vol_pct']}%  "
            f"(used as a rough liquidity indicator only)"
        )

    # Pricing formula display
    st.divider()
    st.markdown("#### Pricing formula")
    st.markdown(
        f"**Indicative repo rate = GC rate - specialness adjustment**  \n"
        f"= {gc_rate:.2f}% - {specialness_bps} bps  \n"
        f"= **{repo_rate:.2f}%**"
    )

    # Collateral score breakdown
    st.markdown("#### Collateral score breakdown")

    repo_factors   = ["Instrument (base)", "Market", "Issue size", "On-the-run", "Scarcity"]
    repo_modifiers = [
        INSTRUMENT_BASE_SCORE[repo_instrument]["score"],
        MARKET_MODIFIER[repo_market],
        SIZE_MODIFIER[repo_size],
        OTR_MODIFIER[otr_repo],
        SCARCITY_MODIFIER[scarcity],
    ]
    repo_factors.append("TOTAL SCORE (capped 0-100)")
    repo_modifiers.append(collateral_score)

    st.dataframe(
        pd.DataFrame({"Factor": repo_factors, "Points": repo_modifiers}),
        hide_index=True,
        use_container_width=False,
    )

    # Specialness band reference table
    st.markdown("#### Specialness band reference")
    st.dataframe(
        pd.DataFrame([
            {
                "Category":               b[4],
                "Collateral score range": f"{b[0]} - {b[1]}",
                "Specialness adj. (bps)": f"{b[2]} - {b[3]}",
            }
            for b in REPO_SPECIALNESS_BANDS
        ]),
        hide_index=True,
        use_container_width=False,
    )
    st.caption("Active category: " + repo_category)


# --- FOOTER ----------------------------------------------------------------
st.divider()
st.caption(
    "Indicative desk prototype. Not a production pricer. "
    "Lending: borrow fee based on sourcing ease and borrow demand. "
    "Repo: repo rate = GC benchmark - specialness adjustment (bond collateral only). "
    "Yahoo Finance used only as a generic market proxy. Day count: Act/360."
)
