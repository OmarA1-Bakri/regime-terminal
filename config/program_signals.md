# SIGNAL RULES v2

All signals based on 4-hour HMM regime classification.
1-hour used for confirmation. 1-minute used for execution timing.
Volume Profile POC used as confirmation filter on ALL entries.

## POC Signal Gating (MANDATORY)

Every HMM regime transition MUST be confirmed by Volume Profile before entry.

| POC Signal | Definition | Action |
|------------|------------|--------|
| STRONG | Price at or below VAL + POC rising | ENTER at full size |
| MEDIUM | Price inside Value Area + POC rising | ENTER at 75% size |
| WEAK | Price inside Value Area + POC stable | ENTER at 40% size, only with catalyst |
| MARGINAL | Everything else | DO NOT ENTER. Skip. |
| REJECT | POC falling >5% OR (falling >3% + price above VAH) | DO NOT ENTER. Skip. |

Backtest proof: STRONG signals win 60% of the time. MARGINAL wins 23%. Act accordingly.

## Long Entry Rules

| 4h Transition | POC Required | Size | Confirmation |
|---------------|-------------|------|--------------|
| Crash to Bear | N/A | 0% | WATCHLIST only |
| Bear to Neutral | STRONG or MEDIUM | See POC sizing | 1h must not be Crash |
| Neutral to Weak Bull | STRONG or MEDIUM | See POC sizing | 1h Neutral or better |
| Neutral to Bull | MEDIUM or better | See POC sizing | None needed |
| Any to Strong Bull | MEDIUM or better | See POC sizing | HOLD if already in, ENTER if not |

## Short Entry Rules (NEW)

Short selling turns bear markets into profit. The HMM detects Bear transitions — act on them.

| 4h Transition | POC Required | Size | Confirmation |
|---------------|-------------|------|--------------|
| Bull to Neutral | MEDIUM or better (inverted: price above VAH + POC falling) | See POC sizing | 1h must not be Strong Bull |
| Neutral to Weak Bear | MEDIUM or better (inverted) | See POC sizing | 1h Neutral or worse |
| Neutral to Bear | Any non-REJECT | See POC sizing | None needed |
| Any to Crash | EMERGENCY: short at market | Max allowed | None |

For shorts, POC signals are inverted:
- STRONG short: price above VAH + POC falling = distribution at resistance
- MEDIUM short: price inside VA + POC falling
- WEAK short: price inside VA + POC stable
- REJECT short: POC rising strongly = accumulation, do not short

## Exit Rules (Longs)

| 4h Transition | Action |
|---------------|--------|
| Bull to Neutral | CLOSE 50% |
| Neutral to Weak Bear | CLOSE 100% |
| Neutral to Bear | CLOSE 100% |
| Any to Crash | EMERGENCY EXIT 100% |
| Bull to Strong Bull | HOLD, activate trailing stop |

## Exit Rules (Shorts)

| 4h Transition | Action |
|---------------|--------|
| Bear to Neutral | CLOSE 50% of short |
| Neutral to Weak Bull | CLOSE 100% of short |
| Any to Bull or Strong Bull | CLOSE 100% of short |
| Crash to Bear | Tighten stop, prepare to cover |

## Stop Loss Rules — ATR-Based (REPLACES FIXED -3%)

Every position MUST have an ATR-based stop set at entry.

| Asset Tier | Stop Distance | How |
|-----------|--------------|-----|
| Tier 1 (BTC, ETH) | 2.0x ATR(14) | Lower volatility, tighter stops |
| Tier 2 (SOL, BNB, XRP) | 2.5x ATR(14) | Moderate volatility |
| Tier 3 (TAO, FET, SUI, etc) | 3.0x ATR(14) | Higher volatility, wider stops |
| Leveraged positions | 1.5x ATR(14) | Tighter due to amplification |

ATR is computed on 4h candles (14-period). Use GET /atr/{symbol}?timeframe=4h to get current ATR.
If ATR endpoint unavailable, fall back to: Tier 1: -2%, Tier 2: -3%, Tier 3: -5%.

## Trailing Stop Rules (NEW)

Once a position is profitable, the stop should trail to lock in gains.

| Condition | Trailing Stop |
|-----------|---------------|
| Position +1x ATR from entry | Move stop to breakeven |
| Position +2x ATR from entry | Trail at 2x ATR below highest price |
| Position +3x ATR from entry | Tighten trail to 1.5x ATR below highest |
| 4h regime is Strong Bull | Trail at 2x ATR below highest (let it run) |

## Take Profit Rules

- At +2x ATR: move stop to breakeven
- At +4x ATR: take 25% profit
- At +8x ATR: take another 25% profit
- Let remaining 50% ride with trailing stop

## Multi-Timeframe Confirmation

Best entry: 4h flips Bear to Neutral AND 1h is already Neutral or Weak Bull AND POC is STRONG
Worst entry: 4h flips to Neutral but 1h still Bear and POC is MARGINAL. Skip.

## What NOT to Trade

- Never enter when POC signal is MARGINAL or REJECT
- Never enter when 4h regime is Crash on BTC (correlation risk) unless shorting
- Never add to a losing position
- Never enter more than 3 positions simultaneously
- Never trade a symbol where regime confidence is below 0.5
- Never go long when BTC 4h POC is falling >5% (institutional distribution)
