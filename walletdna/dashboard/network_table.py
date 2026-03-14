"""
WalletDNA — Network Table Renderer
===================================
Renders the full cluster network table from a list of analysed profiles.

Output format:
    NETWORK ANALYSIS — BDAG-Investigation-01 — 12 wallets

    #  ADDRESS          CHAIN  TXS    VOLUME        CLASS         CLUSTER    SIM
    1  0x4c39...b2d3    ETH    10000  $15.2M        LIKELY_HUMAN  CLUSTER-A  0.94
    2  TVM6Ku...fRr     TRX    5486   $847K         LIKELY_HUMAN  CLUSTER-A  0.91  ← SAME OPERATOR
    ...

    12 wallets · 3 clusters · CLUSTER-A: 5 wallets · $28.4M total volume
"""

from __future__ import annotations

from typing import Optional

from rich import box
from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ─── Colour Palette (matches terminal.py) ─────────────────────────────────────
BLUE  = "#2D7DD2"
DARK  = "#1E3A5F"
GREEN = "#39D353"
AMBER = "#F4A261"
RED   = "#E76F51"
GREY  = "#888888"
DIM   = "#444444"
WHITE = "white"


def _class_colour(wallet_class: str) -> str:
    wc = wallet_class.upper()
    if "BOT" in wc and "LIKELY" not in wc:
        return RED
    if "LIKELY_BOT" in wc:
        return AMBER
    if "LIKELY_HUMAN" in wc:
        return "#90EE90"
    if wc == "HUMAN":
        return GREEN
    return GREY


def _sim_colour(sim: float) -> str:
    if sim >= 0.92:
        return RED
    if sim >= 0.75:
        return AMBER
    if sim >= 0.50:
        return WHITE
    return GREEN


def _fmt_volume(total_usd: float, total_native: float, chain: str) -> str:
    if total_usd >= 1_000_000_000:
        return f"${total_usd / 1_000_000_000:.1f}B"
    if total_usd >= 1_000_000:
        return f"${total_usd / 1_000_000:.1f}M"
    if total_usd >= 1_000:
        return f"${total_usd / 1_000:.1f}K"
    if total_usd > 0:
        return f"${total_usd:.0f}"
    if total_native > 0:
        return f"{total_native:.4f} {chain}"
    return "—"


def _avg_sim(profile: dict, all_profiles: list[dict]) -> float:
    """
    Compute average similarity of this profile against all others that have vectors.
    Falls back to 0.0 if no vectors available.
    """
    sim_row = profile.get("_sim_row")
    if not sim_row:
        return 0.0
    idx = next(
        (i for i, p in enumerate(all_profiles) if p["address"].lower() == profile["address"].lower()),
        None,
    )
    if idx is None:
        return 0.0
    scores = [s for i, s in enumerate(sim_row) if i != idx and s > 0]
    return sum(scores) / len(scores) if scores else 0.0


def render_network_table(
    case_name: str,
    profiles: list[dict],
    clusters: Optional[list[dict]] = None,
) -> Panel:
    """
    Render the full network analysis table panel.

    Args:
        case_name: Display name for panel title.
        profiles:  List of profile dicts (from CaseAnalyser.run()).
        clusters:  Optional pre-computed cluster list (from compute_clusters()).
    """
    if not profiles:
        return Panel(
            Text("No profiles loaded.", style=GREY),
            title=f"[bold {RED}]🌐  NETWORK ANALYSIS[/bold {RED}]",
            border_style=RED, style="on #0D1117",
        )

    # Build row table
    t = Table(
        show_header=True,
        header_style=f"bold white on {DARK}",
        box=box.SIMPLE_HEAVY,
        border_style=DARK,
        padding=(0, 1),
        expand=True,
    )
    t.add_column("#",         style=f"bold {GREY}", width=4,  justify="right")
    t.add_column("ADDRESS",   style=f"bold {BLUE}", width=18)
    t.add_column("CHAIN",     style=GREY,           width=6)
    t.add_column("TXS",       style=WHITE,          width=7,  justify="right")
    t.add_column("VOLUME",    style=WHITE,          width=12, justify="right")
    t.add_column("CLASS",     style=WHITE,          width=14)
    t.add_column("TYPE",      style=GREY,           width=22)
    t.add_column("CLUSTER",   style=WHITE,          width=12)
    t.add_column("SIM",       style=WHITE,          width=8,  justify="right")
    t.add_column("",          style=AMBER,          width=18)  # SAME OPERATOR flag

    total_volume_usd = 0.0
    rows_data = []

    for i, p in enumerate(profiles):
        addr       = p["address"]
        chain      = p.get("chain", "ETH")
        tx_count   = p.get("tx_count", 0)
        total_usd  = float(p.get("total_usd", 0))
        native     = float(p.get("total_native", 0))
        wc         = p.get("wallet_class", "UNKNOWN")
        wtype      = p.get("wallet_type") or ""
        cluster_lbl= p.get("cluster_label", "—")
        avg        = _avg_sim(p, profiles)
        source     = p.get("source", "")

        total_volume_usd += total_usd

        short     = f"{addr[:8]}...{addr[-6:]}"
        vol_str   = _fmt_volume(total_usd, native, chain)
        class_col = _class_colour(wc)
        sim_col   = _sim_colour(avg)
        clust_col = RED if cluster_lbl != "—" else GREY

        # SAME OPERATOR flag
        flag = ""
        if avg >= 0.92 and cluster_lbl != "—":
            flag = "← SAME OPERATOR"

        # INSUFFICIENT DATA row style
        if source == "insufficient_data":
            wc      = "INSUFFICIENT"
            class_col = GREY
            vol_str = "—"
            avg     = 0.0
            cluster_lbl = "—"

        # API limit warning
        api_warn = p.get("api_limit_hit", False)
        tx_str = f"{'≥' if api_warn else ''}{tx_count}" if tx_count else "—"

        rows_data.append((
            str(i + 1), short, chain,
            tx_str, vol_str,
            wc, class_col,
            wtype,
            cluster_lbl, clust_col,
            f"{avg:.2f}" if avg > 0 else "—", sim_col,
            flag,
        ))

    for rd in rows_data:
        (num, addr, chain, txs, vol,
         wc, class_col, wtype,
         cluster_lbl, clust_col,
         sim_str, sim_col,
         flag) = rd

        t.add_row(
            Text(num,          style=GREY),
            Text(addr,         style=f"bold {BLUE}"),
            Text(chain,        style=GREY),
            Text(txs,          style=WHITE),
            Text(vol,          style=WHITE),
            Text(wc,           style=f"bold {class_col}"),
            Text(wtype,        style=GREY),
            Text(cluster_lbl,  style=f"bold {clust_col}"),
            Text(sim_str,      style=f"bold {sim_col}"),
            Text(flag,         style=f"bold {AMBER}"),
        )

    # Build summary footer
    summary = _render_summary(profiles, clusters, total_volume_usd)

    # Panel subtitle
    n_wallets  = len(profiles)
    n_clusters = len(clusters) if clusters else 0
    n_cached   = sum(1 for p in profiles if p.get("source") == "cache")
    n_live     = sum(1 for p in profiles if p.get("source") == "live")
    subtitle   = (
        f"[{GREY}]{n_wallets} wallets  ·  "
        f"{n_clusters} clusters  ·  "
        f"{n_cached} cached  ·  {n_live} live[/{GREY}]"
    )

    return Panel(
        Group(t, Rule(style=DARK), summary),
        title=(
            f"[bold {RED}]🌐  NETWORK ANALYSIS[/bold {RED}]  "
            f"[{GREY}]{case_name}[/{GREY}]"
        ),
        subtitle=subtitle,
        border_style=RED,
        style="on #0D1117",
        padding=(0, 1),
    )


def _render_summary(
    profiles: list[dict],
    clusters: Optional[list[dict]],
    total_volume_usd: float,
) -> Text:
    t = Text()

    n = len(profiles)
    n_bot         = sum(1 for p in profiles if "BOT" in p.get("wallet_class", "") and "HUMAN" not in p.get("wallet_class", ""))
    n_insufficient= sum(1 for p in profiles if p.get("source") == "insufficient_data")

    t.append("\n  ◆ CLUSTER SUMMARY\n\n", style=f"bold {GREEN}")

    if clusters:
        for cl in clusters:
            interp_col = RED if cl["avg_similarity"] >= 0.92 else AMBER
            t.append(f"  {cl['label']:<14}", style=f"bold {RED}")
            t.append(
                f"{cl['member_count']} wallets  ·  "
                f"avg sim {cl['avg_similarity']:.3f}  ·  "
                f"{cl['interpretation']}\n",
                style=interp_col,
            )
    else:
        t.append("  No clusters detected above threshold 0.75\n", style=GREY)

    t.append("\n")

    stats = [
        ("Wallets analysed",  str(n),                            WHITE),
        ("Bot / suspicious",  f"{n_bot}  ({int(n_bot/max(n,1)*100)}%)",  RED   if n_bot > 0 else GREEN),
        ("Insufficient data", str(n_insufficient),               GREY),
        ("Total volume",      f"${total_volume_usd:,.0f} USD" if total_volume_usd > 0 else "—", WHITE),
    ]

    if clusters:
        largest = max(clusters, key=lambda c: c["member_count"])
        stats.append(("Largest cluster",
                       f"{largest['label']}  ·  {largest['member_count']} wallets",
                       RED))

    for label, value, col in stats:
        t.append(f"  {label:<24}", style=GREY)
        t.append(f"{value}\n",     style=f"bold {col}")

    t.append(
        f"\n  {n} different addresses.  Identical behaviour.  One operator.\n",
        style=f"bold {AMBER}",
    )
    t.append(
        "  A wallet can change its address — it cannot change its behaviour.\n",
        style=GREY,
    )

    return t
