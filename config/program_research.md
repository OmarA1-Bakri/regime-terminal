# RESEARCH CHECKLIST v2

Before any trade, Claude must check ALL of the following.
Skipping a check is not allowed. Log findings for each.

## 1. Regime State (Required)

- What is the 4h regime? What was it last period? Is this a TRANSITION?
- What is the 1h regime? Do they agree?
- What does the transition matrix say about where this regime goes next?
- For shorts: is the Bear regime sticky (>90% self-transition)? Good for holding shorts.

## 2. Volume Profile / POC (Required — MANDATORY GATE)

- What is the POC signal? (STRONG / MEDIUM / WEAK / MARGINAL / REJECT)
- If MARGINAL or REJECT: STOP. Do not trade. No exceptions.
- Where is price relative to POC? Above = bullish bias. Below = bearish bias.
- Where is price relative to VAH/VAL?
- Is POC shifting? Rising = accumulation (bullish). Falling = distribution (bearish).
- What is the nearest HVN (support/resistance)?
- What is the nearest LVN (breakout zone)?

Call: GET /volume-profile/{symbol}/analysis?timeframe=4h

## 3. ATR and Stop Placement (Required)

- What is the current 14-period ATR on 4h candles?
- Calculate stop distance based on symbol tier (2.0x / 2.5x / 3.0x ATR)
- Is the stop below the nearest HVN support? If not, widen to just below it.
- For shorts: is the stop above the nearest HVN resistance?

## 4. BTC Context (Required)

- What regime is BTC in? If Crash, do not go long on anything.
- Is BTC POC rising or falling? Falling = risk-off environment.
- BTC dominance trend: rising = alt weakness, falling = alt season.

## 5. Symbol Tier Check (Required)

- Is this a Tier A symbol (FET, SUI, TAO, SOL, BNB)? Trade normally.
- Is this a Tier B symbol? Only STRONG POC signals. Enhanced research needed.
- Is this a Tier C symbol? Need specific catalyst + STRONG POC + full conviction.

## 6. Catalyst Check (Required for Tier B and C)

- Any upcoming events? (upgrades, launches, partnerships)
- Any negative catalysts? (hacks, delistings, regulatory)
- For TAO: subnet launches, Bittensor upgrades, emission changes
- For shorts: any upcoming positive catalyst that could squeeze?

## 7. Correlation Check (Required)

- How correlated is this with existing positions?
- Correlation groups: {BTC, ETH, SOL, BNB}, {TAO, FET, RENDER, NEAR}, {DOGE, XRP, ADA}
- If adding same-group asset: count as same exposure
- For shorts: negative correlation with longs = good hedge

## 8. Thesis Formation (Required)

Write a 2-3 sentence thesis:
- WHY this trade (regime transition + POC confirmation + catalyst)
- WHAT is the expected move (target price or target regime)
- WHERE is the stop (ATR-based, below which support level)
- WHEN to exit (regime change, take profit ladder, or time-based)

Example long:
FET 4h flipped Bear to Neutral. POC signal is STRONG: price at VAL ($0.22) with POC rising +8%.
ATR(14) is $0.015, stop at $0.22 - 3x$0.015 = $0.175. Nearest HVN support at $0.19.
Tier A symbol, enter 8% position. Target: regime flip to Bull, exit at Neutral to Bear.

Example short:
ETH 4h flipped Bull to Neutral. POC signal MEDIUM (inverted): price above VAH, POC falling -4%.
ATR(14) is $85, stop at $2077 + 2x$85 = $2247. Distribution pattern confirms.
Tier C symbol but short thesis is strong. Enter 2% short. Cover on Neutral to Bull.

## 9. Anti-Checklist (Required)

Before confirming, ask yourself:
- Is the POC signal STRONG or MEDIUM? If not, why am I still considering this?
- What could go wrong? Where is the nearest HVN that could reverse this?
- Am I chasing price or reacting to a genuine regime transition?
- Would I take this trade if I had already lost money today?
- Is this FOMO or conviction?
- For shorts: is there a potential short squeeze risk (very negative funding)?

If any answer raises doubt, DO NOT ENTER. Cash is always a position.
