# RISK MANAGEMENT v2

## Symbol Tiers

Not all symbols are equal. Backtest showed 6/18 profitable. Trade accordingly.

| Tier | Symbols | Mechanical Trading | Research Required |
|------|---------|-------------------|------------------|
| A (Proven) | FET, SUI, TAO, SOL, BNB | Yes — trade all valid signals | Standard checklist |
| B (Conditional) | AVAX, LINK, RENDER, NEAR, XRP | Only STRONG POC signals | Enhanced research + catalyst |
| C (Research Only) | BTC, ETH, ADA, DOGE, DOT, INJ, PENDLE, AR | Only with specific catalyst + STRONG POC | Full research + Claude conviction |

Tier A symbols showed positive returns in backtest with fees. Tier B were near breakeven. Tier C lost money mechanically.

## Position Sizing — Asymmetric by POC Strength

| POC Signal | Size (% of book) | When |
|------------|-------------------|------|
| STRONG | 8-10% | Best signal quality, proven setup |
| MEDIUM | 4-5% | Good signal, standard conviction |
| WEAK | 2% | Only with catalyst, Tier A symbols only |
| MARGINAL | 0% | DO NOT TRADE |

Modifiers:
- Tier A symbol: use full size above
- Tier B symbol: use 50% of size above
- Tier C symbol: use 25% of size above (research-only trades)
- Leveraged: halve the size (leverage provides the exposure)

## ATR-Based Stop Losses

All stops are now based on Average True Range, not fixed percentages.
ATR adapts to each symbols actual volatility.

| Asset Tier | Long Stop | Short Stop |
|-----------|-----------|------------|
| Tier 1 (BTC, ETH) | Entry - 2.0x ATR(14) | Entry + 2.0x ATR(14) |
| Tier 2 (SOL, BNB, XRP) | Entry - 2.5x ATR(14) | Entry + 2.5x ATR(14) |
| Tier 3 (all others) | Entry - 3.0x ATR(14) | Entry + 3.0x ATR(14) |
| Leveraged | Entry - 1.5x ATR(14) | Entry + 1.5x ATR(14) |

## Drawdown Limits

| Rule | Threshold | Action |
|------|-----------|--------|
| Per-trade stop | ATR-based (see above) | Auto-close |
| Daily drawdown | -5% of total book | Stop trading for 24hrs |
| Weekly drawdown | -10% of total book | Close all positions, review |
| Max drawdown (KILL SWITCH) | -20% of book | Everything closed, system paused |
| BTC correlation breaker | BTC drops 10%+ in 1hr | Close all leveraged positions |

## Exposure Limits

| Rule | Limit |
|------|-------|
| Max open positions | 3 (longs) + 2 (shorts) = 5 total |
| Max single position | 10% of book |
| Max correlated exposure | 15% (BTC + ETH + SOL count together) |
| Max leveraged notional | 25% of book |
| Cash reserve minimum | 10% always in stables |
| Max short exposure | 20% of book |

## Leverage Rules

| Asset | Max Long Leverage | Max Short Leverage |
|-------|-------------------|--------------------|
| BTC, ETH | 5x | 3x |
| SOL, BNB, XRP | 3x | 2x |
| TAO (Kraken spot only) | 1x | N/A (use Binance for short) |
| All other alts | 3x | 2x |

## Pre-Trade Checklist (Rules Engine)

Before ANY trade, ALL must pass:
1. Symbol is in approved universe and meets tier requirements
2. POC signal is not MARGINAL or REJECT
3. Position size matches POC signal strength x tier modifier
4. ATR-based stop loss is calculated and set
5. Not at max positions (3 long + 2 short)
6. Candle data is fresh (less than 30 minutes old)
7. Regime confidence above 0.5
8. Not a duplicate of existing open position on same side
9. Not in daily/weekly drawdown cooldown
10. Kill switch is not active
11. BTC is not in Crash regime (unless this IS a short trade)
12. Total exposure within limits

## Risk Manager Review (Claude Opus)

After rules engine passes, a SEPARATE review checks:
1. Is the thesis coherent with the regime + POC reading?
2. Portfolio correlation check (not doubling up on correlated assets)
3. Recent trade history (lost on this exact setup before?)
4. Symbol tier check (is research sufficient for this tier?)
5. Overall portfolio heat

Both must approve before execution.
