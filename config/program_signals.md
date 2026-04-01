# SIGNAL RULES

All signals based on 4-hour HMM regime classification.
1-hour used for confirmation. 1-minute used for execution timing.

## Entry Rules

| 4h Transition | Action | Size | Confirmation Required |
|---------------|--------|------|-----------------------|
| Crash to Bear | WATCHLIST only | 0% | None |
| Bear to Neutral | ENTER 50% of allocation | 50% | 1h must not be Crash |
| Neutral to Weak Bull | ENTER remaining 50% | Full | 1h must be Neutral or better |
| Neutral to Bull | ENTER remaining 50% | Full | None needed |
| Any to Strong Bull | HOLD if already in. ENTER if not. | Full | None |

## Exit Rules

| 4h Transition | Action | Notes |
|---------------|--------|-------|
| Bull to Neutral | CLOSE 50% | Momentum fading, take partial profit |
| Neutral to Weak Bear | CLOSE 100% | Trend reversing |
| Neutral to Bear | CLOSE 100% | Clear reversal |
| Any to Crash | EMERGENCY EXIT 100% | Capital preservation, no exceptions |
| Bull to Strong Bull | HOLD | Trail stop at 20% from peak |

## Stop Loss Rules

Every position MUST have a stop loss set at entry:
- Default: -3% from entry price
- High conviction with catalyst: -5% allowed
- Leveraged positions: -2% (tighter due to amplification)

## Take Profit Rules

- At +10%: move stop to breakeven
- At +20%: take 25% profit
- At +50%: take another 25% profit
- Let remaining 50% ride with trailing stop at 20% from peak

## Multi-Timeframe Confirmation

Best entry: 4h flips Bear to Neutral AND 1h is already Neutral or Weak Bull
Worst entry: 4h flips to Neutral but 1h still shows Bear or Crash. Wait.

If 4h and 1h disagree, trust 4h for direction but wait for 1h to confirm before entering.

## What NOT to Trade

- Never enter when 4h regime is Crash on BTC (correlation risk)
- Never add to a losing position
- Never enter more than 3 positions simultaneously
- Never trade a symbol where confidence is below 0.5
