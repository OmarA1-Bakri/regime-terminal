# TAO / BITTENSOR STRATEGY

## Overview

TAO allocation: 30% of book (GBP 300 at start, approximately 1 TAO).
Split between spot holding and subnet staking.

## Spot Trading

Same regime transition rules as other assets (see program_signals.md).
TAO is MORE volatile than BTC. Swings of 20-50% in a week are normal.

### TAO-Specific Signals

| Signal | Action |
|--------|--------|
| 4h Bear to Neutral + subnet activity spike | Strong buy |
| 4h Bear to Neutral, no catalyst | Standard buy |
| New major subnet launch announced | Add to watchlist |
| BTC crashes 10%+ in 1hr | Close all TAO positions |
| TAO +50% from entry | Take 50% profit |

### TAO Catalysts to Monitor

- New subnet launches (check bittensor.com, taostats.io)
- SN64 (Chutes) activity — AI inference demand indicator
- SN62 (Ridges) performance — financial prediction subnet
- Bittensor core protocol upgrades
- Exchange listings (new exchange = 15-25% pump typically)
- Emissions schedule changes

## Staking Strategy (Lewis Jackson Model)

Once we hold TAO spot, stake across subnets:

| Subnet | What | % of TAO Allocation |
|--------|------|---------------------|
| SN0 (Root) | Base yield | 50% |
| SN64 (Chutes) | AI inference | 16.5% |
| SN62 (Ridges) | Financial prediction | 11% |
| SN4 (Targon) | Text generation | 9.5% |
| SN75 (Hippius) | Decentralised cloud | 7% |
| SN68 (Nova) | Data pipelines | 3.5% |
| SN55 (Ko/Precog) | Market prediction | 2.5% |

## Staking Execution

1. Buy TAO on Kraken (spot, TAO/USD pair)
2. Withdraw to Bittensor wallet (SS58 address)
3. Stake via btcli or Bittensor dashboard
4. Monitor positions via tao_monitor.py

## TAO Risk Management

- TAO is Kraken spot only. No margin/leverage available on Kraken for TAO.
- For leveraged TAO: use Binance Futures (TAOUSDT perp)
- Max TAO leverage: 3x
- TAO stop loss: -5% (wider than standard -3% due to higher volatility)
- If TAO 4h regime goes to Crash: exit ALL TAO including staked positions

## TAO on Exchanges

| Exchange | Spot | Margin | Futures | Staking |
|----------|------|--------|---------|---------|
| Kraken | Yes (TAO/USD, TAO/USDC) | No | No | Yes |
| Binance | Yes | No | Yes (TAOUSDT perp) | No |
