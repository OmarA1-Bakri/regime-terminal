# RISK MANAGEMENT

## Position Sizing

| Conviction | Size (% of book) | When |
|------------|-------------------|------|
| Low | 1% | Signal only, no catalyst, low confidence |
| Medium | 2-3% | Signal + moderate confidence + thesis |
| High | 5% | Signal + catalyst + high confidence |
| Max | 10% | Multiple converging signals, extremely rare |

## Drawdown Limits

| Rule | Threshold | Action |
|------|-----------|--------|
| Per-trade stop | -3% of position | Auto-close |
| Daily drawdown | -5% of total book | Stop trading for 24hrs |
| Weekly drawdown | -10% of total book | Close all positions, review |
| Max drawdown (KILL SWITCH) | -20% of book | Everything closed, system paused |
| BTC correlation breaker | BTC drops 10%+ in 1hr | Close all leveraged positions |

## Exposure Limits

| Rule | Limit |
|------|-------|
| Max open positions | 3 |
| Max single position | 10% of book |
| Max correlated exposure | 15% (BTC + ETH + SOL count together) |
| Max leveraged notional | 25% of book |
| Cash reserve minimum | 10% always in stables |

## Leverage Rules

| Asset | Max Leverage |
|-------|--------------|
| BTC, ETH | 5x |
| SOL, BNB, XRP | 3x |
| TAO (Kraken spot only) | 1x |
| All other alts | 3x |
| NEVER exceed | 5x on anything |

## Pre-Trade Checklist (Rules Engine)

Before ANY trade executes, these must ALL pass:
1. Balance sufficient for the trade
2. Position size within limits
3. Not at max positions (3)
4. Candle data is fresh (less than 30 minutes old)
5. Regime confidence above 0.5
6. Not a duplicate of existing open position
7. Symbol is in approved universe (18 symbols)
8. Not in daily drawdown cooldown
9. Not in weekly drawdown review
10. Kill switch is not active

## Risk Manager Review (Claude Opus)

After rules engine passes, a SEPARATE Claude Opus call reviews:
1. Is the thesis coherent?
2. Portfolio correlation check
3. Recent trade history (lost on this setup before?)
4. Timing (funding rates, macro events, etc)
5. Overall portfolio heat

Both must approve before execution.
