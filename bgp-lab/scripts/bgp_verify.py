#!/usr/bin/env python3
"""
bgp_verify.py — Quick verification WITHOUT SSH/Netmiko
=======================================================
Uses 'docker exec' subprocess calls instead of SSH,
so it works even before you set up SSH on the containers.

Usage:
    python3 scripts/bgp_verify.py
"""

import subprocess
import sys
import time
from datetime import datetime

CONTAINERS = {
    "R1-AS65001": "bgp-r1",
    "R2-AS65002": "bgp-r2",
    "R3-AS65003": "bgp-r3",
}

SEPARATOR = "─" * 65


def vtysh(container: str, command: str) -> str:
    """Run a vtysh command in a container via docker exec."""
    result = subprocess.run(
        ["docker", "exec", container, "vtysh", "-c", command],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return f"[ERROR] {result.stderr.strip()}"
    return result.stdout.strip()


def docker_exec(container: str, *args) -> str:
    """Run arbitrary command in container."""
    result = subprocess.run(
        ["docker", "exec", container] + list(args),
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


def header(title: str):
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def check_containers():
    """Verify all containers are running."""
    header("1. Container Status")
    all_ok = True
    for name, cname in CONTAINERS.items():
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", cname],
            capture_output=True, text=True,
        )
        status = result.stdout.strip()
        ok = status == "running"
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name} ({cname}): {status}")
        if not ok:
            all_ok = False
    return all_ok


def check_bgp_summary():
    """Show BGP summary from each router."""
    header("2. BGP Summary (all routers)")
    for name, cname in CONTAINERS.items():
        print(f"\n  [{name}]")
        output = vtysh(cname, "show bgp summary")
        for line in output.splitlines():
            print(f"    {line}")


def check_routing_tables() -> dict:
    """Capture and display routing tables."""
    header("3. BGP Routing Tables")
    tables = {}
    for name, cname in CONTAINERS.items():
        print(f"\n  [{name}] — ip bgp table")
        output = vtysh(cname, "show ip bgp")
        tables[name] = output
        for line in output.splitlines()[:20]:   # trim for display
            print(f"    {line}")
        if len(output.splitlines()) > 20:
            print(f"    ... ({len(output.splitlines())} total lines)")
    return tables


def check_communities():
    """Show BGP community attributes."""
    header("4. BGP Community Tags")
    for name, cname in CONTAINERS.items():
        print(f"\n  [{name}] — communities on received prefixes")
        output = vtysh(cname, "show ip bgp community 65001:100")
        if "Network" in output:
            for line in output.splitlines():
                print(f"    {line}")
        else:
            # Try transit community
            output2 = vtysh(cname, "show ip bgp community 65002:100")
            for line in output2.splitlines()[:10]:
                print(f"    {line}")


def check_route_maps():
    """Confirm route-maps are applied."""
    header("5. Route-Map Configuration Check")
    for name, cname in CONTAINERS.items():
        print(f"\n  [{name}]")
        output = vtysh(cname, "show route-map")
        for line in output.splitlines()[:15]:
            print(f"    {line}")


def simulate_failover(before_tables: dict):
    """Shutdown R1's uplink and show routing change."""
    header("6. FAILOVER SIMULATION — Shutting R1 ↔ R2 link")

    print("  Shutting interface eth0 on R1...")
    # Use ip link down via docker exec (simpler than vtysh shutdown)
    subprocess.run(
        ["docker", "exec", "bgp-r1", "ip", "link", "set", "eth0", "down"],
        capture_output=True,
    )
    print("  ✓ eth0 down on R1")
    print("  Waiting 20s for BGP hold-timer to expire and converge...")
    time.sleep(20)

    print("\n  BGP summary on R2 after R1 link down:")
    output = vtysh("bgp-r2", "show bgp summary")
    for line in output.splitlines():
        print(f"    {line}")

    print("\n  BGP summary on R3 after R1 link down:")
    output = vtysh("bgp-r3", "show bgp summary")
    for line in output.splitlines():
        print(f"    {line}")

    print("\n  Capturing AFTER routing tables...")
    after_tables = {}
    for name, cname in CONTAINERS.items():
        after_tables[name] = vtysh(cname, "show ip bgp")

    # Restore
    header("7. RESTORING LINK")
    print("  Bringing eth0 back up on R1...")
    subprocess.run(
        ["docker", "exec", "bgp-r1", "ip", "link", "set", "eth0", "up"],
        capture_output=True,
    )
    print("  ✓ eth0 restored — waiting 15s for BGP re-convergence...")
    time.sleep(15)

    return after_tables


def generate_report(before: dict, after: dict):
    """Write diff report to file."""
    import difflib

    header("8. DIFF REPORT")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bgp_diff_{timestamp}.txt"

    with open(filename, "w") as f:
        f.write("BGP ROUTING TABLE — BEFORE / AFTER FAILOVER\n")
        f.write(f"Generated: {datetime.now()}\n")
        f.write("=" * 70 + "\n\n")

        for rname in before:
            f.write(f"\n=== {rname} ===\n")
            diff = difflib.unified_diff(
                before[rname].splitlines(keepends=True),
                after[rname].splitlines(keepends=True),
                fromfile="BEFORE",
                tofile="AFTER",
                lineterm="\n",
            )
            diff_text = "".join(diff)
            if diff_text:
                f.write(diff_text)
                # Print diff summary to console
                added = diff_text.count("\n+")
                removed = diff_text.count("\n-")
                print(f"  {rname}: +{added} lines added, -{removed} lines removed")
            else:
                f.write("(no change)\n")
                print(f"  {rname}: no change")

    print(f"\n  ✓ Report saved: {filename}")
    return filename


def main():
    print("\n" + "=" * 65)
    print("  BGP MULTI-AS LAB — Verification Script")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # Container health check
    if not check_containers():
        print("\n[FATAL] One or more containers not running.")
        print("  Run: docker compose up -d")
        sys.exit(1)

    # Give FRR a moment if just started
    print("\n  Waiting 5s for FRR daemons to settle...")
    time.sleep(5)

    # Checks
    check_bgp_summary()
    before_tables = check_routing_tables()
    check_communities()
    check_route_maps()

    # Failover
    print("\n  Run failover simulation? (y/N): ", end="")
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "n"

    if answer == "y":
        after_tables = simulate_failover(before_tables)
        report_file = generate_report(before_tables, after_tables)
    else:
        print("  Skipping failover. Run again and type 'y' when ready.")

    header("DONE")
    print("  Useful manual commands:")
    print("    docker exec -it bgp-r1 vtysh")
    print("    docker exec -it bgp-r2 vtysh")
    print("    docker exec -it bgp-r3 vtysh")
    print("\n  Inside vtysh:")
    print("    show bgp summary")
    print("    show ip bgp")
    print("    show ip bgp community 65001:100")
    print("    show ip route")
    print("    show route-map")
    print("    show bgp neighbors 10.0.12.1")


if __name__ == "__main__":
    main()
