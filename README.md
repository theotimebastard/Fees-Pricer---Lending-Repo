# Securities Finance Pricer

A simple desk prototype for Securities Lending and Repo pricing.

---

## Project structure

```
app.py            Streamlit application
requirements.txt  Python dependencies
README.md         This file
```

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Opens at `https://fees-pricer---lending-repo-xfsylb9b3tsvfp5ncwjhz8.streamlit.app/`.


## What the app shows

**Sidebar -- common inputs**

Instrument type, market, issue size / market cap, notional, tenor.
Optional Yahoo Finance ticker to fetch basic market data as a proxy.

**Tab 1 -- Securities Lending**

Computes a sourcing ease score and maps it to an indicative borrow fee bucket.

Inputs: instrument, market, issue size, borrow demand / utilisation, rating (bonds), on-the-run status (bonds).

Outputs: sourcing ease score, category (GC to HTB Extreme), borrow fee in bps, total fee over tenor, daily accrual.

Also shows a score breakdown table and a fee band bar chart.

**Tab 2 -- Repo**

Computes a collateral quality score and derives an indicative repo rate.
This tab is restricted to bond collateral (sovereign and corporate), which is the standard context for repo pricing.

Inputs: bond collateral type, market, issue size, on-the-run status, scarcity level, GC benchmark rate.

Outputs: collateral score, category (GC to Deep Special), GC rate, specialness adjustment, indicative repo rate, repo interest over tenor.

Also shows the pricing formula, a score breakdown table, and a specialness band reference.


## Economic logic

### Securities Lending

The key idea: the harder a security is to find and borrow, the higher the borrow fee.

- Abundant supply, low demand => GC profile => low borrow fee (5-25 bps)
- Scarce, high demand, short pressure => Special or HTB => high borrow fee (up to 1500 bps)

The main driver is borrow demand and utilisation. Issue size also matters: smaller issues have less supply and are harder to source in size.

Fee formula:
```
Total fee = Notional x Borrow fee (bps) / 10000 x Tenor / 360
```

### Repo

The key idea: special collateral trades at a repo rate below the GC benchmark.

When a borrower pledges scarce collateral, the cash lender accepts a lower return because the collateral is hard to find elsewhere. The more special the collateral, the bigger the discount below GC.

Pricing formula:
```
Indicative repo rate = GC benchmark rate - specialness adjustment (bps)
```

This logic is kept completely separate from the lending borrow fee logic.


## Limitations

- This is an indicative prototype, not a production pricer.
- The scoring weights and fee bands are illustrative, not market-calibrated.
- In a real desk context, lending data (utilisation, inventory, specials) comes from dedicated sources.
- Repo pricing in production requires real market quotes, precise collateral inputs, and funding curves.
- Yahoo Finance is used only for generic price, volume, and volatility proxies. It is not a source for lending or repo data.
- Day count convention: Act/360.
