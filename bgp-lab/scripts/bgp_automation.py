#!/usr/bin/env python3
"""
BGP Multi-AS Lab — Automation & Verification Script
====================================================
Uses Netmiko (SSH via vtysh) to:
  1. Check BGP neighbour adjacency on all routers
  2. Capture routing tables (BEFORE state)
  3. Simulate a failover (shut R1-R2 link on R1)
  4. Capture routing tables (AFTER state)
  5. Generate a before/after diff report

Usage:
    pip install netmiko rich
    python3 scripts/bgp_automation.py
"""

import time
import json
import difflib
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

try:
    from netmiko import ConnectHandler
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import print as rprint
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("[WARNING] Install rich for coloured output: pip install netmiko rich")

# ── Router inventory ─────────────────────────────────────────────────────────
ROUTERS = [
    {
        "name":        "R1-AS65001",
        "host":        "172.20.0.11",
        "port":        22,
        "device_type": "linux",          # Netmiko connects to Linux; we call vtysh
        "username":    "frr",
        "password":    "frr",
        "use_keys":    False,
    },
    {
        "name":        "R2-AS65002",
        "host":        "172.20.0.12",
        "port":        22,
        "device_type": "linux",
        "username":    "frr",
        "password":    "frr",
        "use_keys":    False,
    },
    {
        "name":        "R3-AS65003",
        "host":        "172.20.0.13",
        "port":        22,
        "device_type": "linux",
        "username":    "frr",
        "password":    "frr",
        "use_keys":    False,
    },
]

console = Console() if RICH_AVAILABLE else None


# ── Helpers ──────────────────────────────────────────────────────────────────
def vtysh_cmd(connection, command: str) -> str:
    """Run a vtysh command via the Linux shell."""
    output = connection.send_command(
        f'vtysh -c "{command}"',
        expect_string=r"\$",
        read_timeout=15,
    )
    return output


def connect(router: dict):
    """Return an active Netmiko connection."""
    cfg = {k: v for k, v in router.items() if k != "name"}
    return ConnectHandler(**cfg)


def section(title: str):
    if RICH_AVAILABLE:
        console.rule(f"[bold cyan]{title}[/bold cyan]")
    else:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print('='*60)


# ── Core checks ──────────────────────────────────────────────────────────────
def check_bgp_neighbors(router: dict) -> dict:
    """
    Returns dict with 'router', 'neighbors', 'all_established' keys.
    neighbor_state is parsed from 'show bgp summary json'.
    """
    result = {"router": router["name"], "neighbors": [], "all_established": False}
    try:
        conn = connect(router)
        raw = vtysh_cmd(conn, "show bgp summary json")
        conn.disconnect()

        data = json.loads(raw)
        peers = data.get("ipv4Unicast", {}).get("peers", {})
        established_count = 0
        for peer_ip, info in peers.items():
            state = info.get("state", "Unknown")
            pfx_rcvd = info.get("pfxRcd", 0)
            result["neighbors"].append({
                "peer": peer_ip,
                "state": state,
                "prefixes_received": pfx_rcvd,
            })
            if state == "Established":
                established_count += 1

        result["all_established"] = (established_count == len(peers) and len(peers) > 0)

    except Exception as e:
        result["error"] = str(e)

    return result


def get_routing_table(router: dict) -> str:
    """Return the BGP RIB as a string."""
    try:
        conn = connect(router)
        output = vtysh_cmd(conn, "show ip bgp")
        conn.disconnect()
        return output
    except Exception as e:
        return f"ERROR: {e}"


def get_bgp_communities(router: dict) -> str:
    """Show prefixes with communities attached."""
    try:
        conn = connect(router)
        output = vtysh_cmd(conn, "show ip bgp community-info")
        conn.disconnect()
        return output
    except Exception as e:
        return f"ERROR: {e}"


# ── Failover simulation ───────────────────────────────────────────────────────
def simulate_failover():
    """
    Administratively shut down R1's uplink to R2,
    wait for BGP to converge, capture tables,
    then restore the link.
    """
    section("FAILOVER SIMULATION — Shutting R1 eth0")

    r1 = ROUTERS[0]
    conn = connect(r1)

    # Shut the interface
    shut_cmds = [
        "conf t",
        "interface eth0",
        "shutdown",
        "end",
    ]
    for cmd in shut_cmds:
        vtysh_cmd(conn, cmd)
    conn.disconnect()

    print("  ✓ R1 eth0 shut — waiting 20s for BGP convergence...")
    time.sleep(20)


def restore_link():
    """Restore R1 eth0 after failover test."""
    section("RESTORING LINK — Bringing R1 eth0 back up")

    r1 = ROUTERS[0]
    conn = connect(r1)

    restore_cmds = [
        "conf t",
        "interface eth0",
        "no shutdown",
        "end",
    ]
    for cmd in restore_cmds:
        vtysh_cmd(conn, cmd)
    conn.disconnect()

    print("  ✓ R1 eth0 restored — waiting 15s for BGP re-convergence...")
    time.sleep(15)


# ── Reporting ─────────────────────────────────────────────────────────────────
def print_neighbor_table(results: list):
    if RICH_AVAILABLE:
        table = Table(title="BGP Neighbour Adjacency Check", show_lines=True)
        table.add_column("Router",   style="bold white")
        table.add_column("Peer",     style="cyan")
        table.add_column("State",    style="bold")
        table.add_column("Pfx Rcvd")

        for r in results:
            rname = r["router"]
            if "error" in r:
                table.add_row(rname, "—", f"[red]ERROR: {r['error']}[/red]", "—")
                continue
            for nbr in r["neighbors"]:
                state_str = nbr["state"]
                colour = "green" if state_str == "Established" else "red"
                table.add_row(
                    rname,
                    nbr["peer"],
                    f"[{colour}]{state_str}[/{colour}]",
                    str(nbr["prefixes_received"]),
                )

        console.print(table)
    else:
        print(f"\n{'Router':<20} {'Peer':<15} {'State':<15} {'Pfx Rcvd'}")
        print("-"*60)
        for r in results:
            for nbr in r.get("neighbors", []):
                print(f"{r['router']:<20} {nbr['peer']:<15} {nbr['state']:<15} {nbr['prefixes_received']}")


def generate_diff_report(before: dict, after: dict) -> str:
    """Produce a unified diff of routing tables before vs after failover."""
    lines = [
        "=" * 70,
        "BGP ROUTING TABLE DIFF — Before vs After Failover",
        f"Generated: {datetime.now().isoformat()}",
        "=" * 70,
        "",
    ]

    for rname in before:
        before_lines = before[rname].splitlines(keepends=True)
        after_lines  = after[rname].splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"{rname} BEFORE",
            tofile=f"{rname} AFTER",
            lineterm="",
        ))

        lines.append(f"\n--- {rname} ---")
        if diff:
            lines.extend(diff)
        else:
            lines.append("  (no change)")

    report = "\n".join(lines)

    # Save to file
    report_path = f"bgp_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_path, "w") as f:
        f.write(report)

    return report_path


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    section("BGP MULTI-AS LAB — Automation Script Starting")
    print(f"  Timestamp: {datetime.now()}")
    print(f"  Routers  : {[r['name'] for r in ROUTERS]}\n")

    # ── Step 1: Neighbour check ───────────────────────────────────────────────
    section("STEP 1 — BGP Neighbour Adjacency")
    neighbor_results = []
    for router in ROUTERS:
        print(f"  Checking {router['name']}...")
        result = check_bgp_neighbors(router)
        neighbor_results.append(result)

    print_neighbor_table(neighbor_results)

    all_up = all(r.get("all_established", False) for r in neighbor_results)
    if not all_up:
        print("\n[WARNING] Not all BGP sessions are Established.")
        print("  → Lab may still be converging. Wait 30s and re-run.")
        return

    # ── Step 2: Capture BEFORE routing tables ─────────────────────────────────
    section("STEP 2 — Capturing BEFORE Routing Tables")
    before_tables = {}
    for router in ROUTERS:
        print(f"  Fetching RIB from {router['name']}...")
        before_tables[router["name"]] = get_routing_table(router)
        print(f"    {len(before_tables[router['name']].splitlines())} lines captured")

    # ── Step 3: Failover ──────────────────────────────────────────────────────
    simulate_failover()

    # ── Step 4: Capture AFTER routing tables ──────────────────────────────────
    section("STEP 4 — Capturing AFTER Routing Tables")
    after_tables = {}
    for router in ROUTERS:
        print(f"  Fetching RIB from {router['name']}...")
        after_tables[router["name"]] = get_routing_table(router)

    # ── Step 5: Restore ───────────────────────────────────────────────────────
    restore_link()

    # ── Step 6: Generate diff report ─────────────────────────────────────────
    section("STEP 6 — Generating Diff Report")
    report_file = generate_diff_report(before_tables, after_tables)
    print(f"\n  ✓ Diff report saved to: {report_file}")

    # ── Summary ───────────────────────────────────────────────────────────────
    section("COMPLETE")
    print("  BGP lab verification finished successfully.")
    print(f"  Report: {report_file}")
    print("\n  Useful vtysh commands to explore manually:")
    print("    docker exec -it bgp-r1 vtysh")
    print("    show bgp summary")
    print("    show ip bgp")
    print("    show ip bgp community 65001:100")
    print("    show ip route")


if __name__ == "__main__":
    main()
