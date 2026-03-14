"""
WalletDNA — CLI Entrypoint
"""

from __future__ import annotations

import os
import sys

import structlog
from dotenv import load_dotenv

load_dotenv()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)


def cmd_health() -> None:
    print("\nWalletDNA — Health Check")
    print("─" * 40)
    eth_key = os.getenv("ETHERSCAN_API_KEY", "")
    print(f"{'✓' if eth_key else '!'} Etherscan    {'API key set' if eth_key else 'No API key — rate limited'}")
    print("✓ Dashboard   python3 -m walletdna.dashboard.terminal")
    print("✓ Docker      docker compose up -d postgres")
    print("─" * 40)


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] == "health":
        cmd_health()

    elif args[0] == "dashboard":
        from walletdna.dashboard.terminal import main as run_dashboard
        run_dashboard()

    else:
        print("""
WalletDNA — Behavioural Wallet Intelligence

Commands:
  health       Check system health
  dashboard    Launch terminal dashboard

Usage:
  python3 -m walletdna dashboard
  python3 -m walletdna health
        """)


if __name__ == "__main__":
    main()
