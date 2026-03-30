#!/usr/bin/env python3
"""
TAO Deploy — Stakes TAO across subnets based on configured allocation.
Usage: python3 tao_deploy.py --amount 100 --wallet tao_main
"""
import os
import sys
import argparse
import subprocess
import time
from dotenv import load_dotenv

load_dotenv()

SUBNET_VALIDATORS = {
    0:  ("Root -> TAO.com", "root",  "5HK5tp6t2S59DywmHRWPBVJeJ86T61KjurYqeooqj8sREpeN", 0.500),
    64: ("Chutes",          "alpha", "5Dt7HZ7Zpw4DppPxFM7Ke3Cm7sDAWhsZXmM5ZAmE7dSVJbcQ", 0.165),
    62: ("Ridges",          "alpha", "5Djyacas3eWLPhCKsS3neNSJonzfxJmD3gcrMTFDc4eHsn62", 0.110),
    4:  ("Targon",          "alpha", "5Hp18g9P8hLGKp9W3ZDr4bvJwba6b6bY3P2u3VdYf8yMR8FM", 0.095),
    75: ("Hippius",         "alpha", "5G1Qj93Fy22grpiGKq6BEvqqmS2HVRs3jaEdMhq9absQzs6g", 0.070),
    68: ("Nova",            "alpha", "5F1tQr8K2VfBr2pG5MpAQf62n5xSAsjuCZheQUy82csaPavg", 0.035),
    55: ("Ko/Precog",       "alpha", "5CzSYnS88EpVv7Kve7U1VCYKjCbtKpxZNHMacAy3BkfCsn55", 0.025),
}


def main():
    parser = argparse.ArgumentParser(description="Deploy TAO across subnets")
    parser.add_argument("--amount", type=float, required=True, help="Total TAO to deploy")
    parser.add_argument("--wallet", type=str, default=os.environ.get("WALLET_NAME", "tao_main"))
    parser.add_argument("--execute", action="store_true", help="Actually execute (default is dry-run)")
    args = parser.parse_args()

    total = args.amount
    wallet = args.wallet

    print(f"\n{'='*60}")
    print(f"TAO DEPLOYMENT PLAN")
    print(f"{'='*60}")
    print(f"Wallet:      {wallet}")
    print(f"Total TAO:   {total:.4f}")
    print(f"{'='*60}\n")

    allocations = []
    for netuid, (name, stake_type, hotkey, pct) in SUBNET_VALIDATORS.items():
        amount = round(total * pct, 4)
        allocations.append((netuid, name, stake_type, hotkey, pct, amount))
        print(f"  SN{netuid:<3d} {name:<20s} {pct*100:5.1f}%  ->  {amount:>10.4f} TAO")

    allocated = sum(a[5] for a in allocations)
    print(f"\n  Total allocated: {allocated:.4f} TAO")

    if not args.execute:
        print(f"\n  DRY RUN - no transactions submitted.")
        print(f"  Run with --execute to deploy for real.")
        print(f"  VERIFY validator hotkeys on taostats.io before deploying.")
        return

    print(f"\n  REAL DEPLOYMENT - transactions will be submitted.")
    confirm = input("  Type CONFIRM to proceed: ")
    if confirm.strip() != "CONFIRM":
        print("  Aborted.")
        return

    for netuid, name, stake_type, hotkey, pct, amount in allocations:
        if amount < 0.001:
            print(f"\n  Skipping SN{netuid} ({name}) - amount too small")
            continue

        print(f"\n  Staking {amount:.4f} TAO to SN{netuid} ({name})...")
        cmd = [
            "btcli", "stake", "add",
            "--netuid", str(netuid),
            "--wallet-name", wallet,
            "--include-hotkeys", hotkey,
            "--amount", str(amount),
        ]

        try:
            result = subprocess.run(cmd, timeout=300)
            if result.returncode == 0:
                print(f"  Done: SN{netuid} ({name}) - staked {amount:.4f} TAO")
            else:
                print(f"  FAILED: SN{netuid} ({name}) - exit code {result.returncode}")
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT: SN{netuid} ({name})")
        except FileNotFoundError:
            print(f"  btcli not found. Install: pip3 install bittensor-cli")
            sys.exit(1)

        time.sleep(2)

    print(f"\nDEPLOYMENT COMPLETE")
    print(f"Run 'python3 tao_monitor.py' to check your positions.")


if __name__ == "__main__":
    main()
