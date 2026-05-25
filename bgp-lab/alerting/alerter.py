#!/usr/bin/env python3
"""
BGP Session Alerter v2
======================
Polls all routers via the Docker SDK (docker socket) — no CLI needed.
Works inside a container as long as /var/run/docker.sock is mounted.

On session state change → fires webhook (Slack / Discord / generic).
Exposes Prometheus metrics on :8000/metrics.

Environment variables:
  WEBHOOK_URL     Slack/Discord webhook URL (optional — alerts go to log if unset)
  POLL_INTERVAL   seconds between polls (default 30)
  METRICS_PORT    port for Prometheus scrape endpoint (default 8000)
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from dataclasses import dataclass, field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bgp-alerter")

# ── Config ────────────────────────────────────────────────────────────────────
WEBHOOK_URL   = os.getenv("WEBHOOK_URL", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))
METRICS_PORT  = int(os.getenv("METRICS_PORT", "8000"))

ROUTERS = [
    {"container": "bgp-r1",    "label": "R1-AS65001"},
    {"container": "bgp-r2",    "label": "R2-AS65002"},
    {"container": "bgp-r3",    "label": "R3-AS65003"},
    {"container": "bgp-r4-rr", "label": "R4-RR-AS65002"},
]

# ── State ─────────────────────────────────────────────────────────────────────
@dataclass
class SessionState:
    router:      str
    peer:        str
    state:       str
    pfx_rcvd:    int = 0
    uptime_sec:  int = 0
    flaps:       int = 0
    last_change: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

sessions: dict[tuple, SessionState] = {}
sessions_lock = threading.Lock()
down_since: dict[tuple, datetime] = {}
up_since: dict[tuple, datetime] = {}
mttr_log: dict[tuple, list] = {}

# Docker client (lazy init after deps install)
docker_client = None


def get_docker_client():
    global docker_client
    if docker_client is None:
        import docker
        docker_client = docker.from_env()
    return docker_client


# ── vtysh via Docker SDK ───────────────────────────────────────────────────────
def vtysh(container_name: str, command: str) -> str:
    """Run vtysh command inside container via Docker SDK exec_run."""
    try:
        client = get_docker_client()
        container = client.containers.get(container_name)
        exit_code, output = container.exec_run(
            f'vtysh -c "{command}"',
            demux=False
        )
        raw = output.decode("utf-8", errors="replace") if output else ""
        # Strip the vtysh.conf warning — it's harmless
        lines = [l for l in raw.splitlines()
                 if "vtysh.conf" not in l and l.strip()]
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"{container_name}: exec_run error — {e}")
        return ""

def poll_router(container: str, label: str) -> list[SessionState]:
    raw = vtysh(container, "show bgp summary json")
    if not raw:
        return []

    try:
        json_start = raw.find("{")
        if json_start == -1:
            return []

        data = json.loads(raw[json_start:])
        peers = data.get("ipv4Unicast", {}).get("peers", {})

        results = []
        now = datetime.now(timezone.utc)

        for peer_ip, info in peers.items():
            state = info.get("state", "Unknown")
            key = (label, peer_ip)

        
            if state == "Established":
                if key not in up_since:
                    up_since[key] = now
                uptime_sec = int((now - up_since[key]).total_seconds())
            else:
                up_since.pop(key, None)
                uptime_sec = 0

            results.append(SessionState(
                router=label,
                peer=peer_ip,
                state=state,
                pfx_rcvd=info.get("pfxRcd", 0),
                uptime_sec=uptime_sec,
            ))

        return results

    except json.JSONDecodeError as e:
        log.warning(f"{label}: JSON parse error — {e} | raw: {raw[:120]}")
        return []

# ── Webhook ───────────────────────────────────────────────────────────────────
def send_alert(title: str, message: str, is_recovery: bool = False):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if not WEBHOOK_URL:
        level = "RECOVERY" if is_recovery else "ALERT"
        log.info(f"[{level}] {title} | {message}")
        return
    try:
        import requests
        color = "#2eb886" if is_recovery else "#e01e5a"
        emoji = ":white_check_mark:" if is_recovery else ":rotating_light:"
        if "hooks.slack.com" in WEBHOOK_URL:
            payload = {"attachments": [{"color": color, "title": f"{emoji} {title}",
                        "text": message, "footer": f"BGP Alerter • {ts}"}]}
        elif "discord.com/api/webhooks" in WEBHOOK_URL:
            payload = {"embeds": [{"title": title, "description": message,
                        "color": 0x2eb886 if is_recovery else 0xe01e5a,
                        "footer": {"text": f"BGP Alerter • {ts}"}}]}
        else:
            payload = {"title": title, "message": message, "recovery": is_recovery}
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        log.info(f"Webhook sent ({resp.status_code}): {title}")
    except Exception as e:
        log.error(f"Webhook failed: {e}")


# ── State machine ─────────────────────────────────────────────────────────────
def process_session(new: SessionState):
    key = (new.router, new.peer)
    now = datetime.now(timezone.utc)
    with sessions_lock:
        old = sessions.get(key)
        if old is None:
            sessions[key] = new
            log.info(f"Discovered: {new.router} → {new.peer} [{new.state}]")
            return

        was_up = old.state == "Established"
        is_up  = new.state == "Established"
        new.flaps = old.flaps

        if was_up and not is_up:
            new.flaps += 1
            new.last_change = now
            down_since[key] = now
            log.warning(f"SESSION DOWN: {new.router} → {new.peer} "
                        f"(was up {old.uptime_sec}s, flap #{new.flaps})")
            send_alert(
                f"BGP Session DOWN: {new.router} → {new.peer}",
                f"Router: {new.router}\nPeer: {new.peer}\n"
                f"State: {new.state}\nFlap count: {new.flaps}\n"
                f"Was up: {old.uptime_sec}s",
                is_recovery=False,
            )

        elif not was_up and is_up:
            new.last_change = now
            if key in down_since:
                recovery_s = (now - down_since.pop(key)).total_seconds()
                mttr_log.setdefault(key, []).append(recovery_s)
                avg = sum(mttr_log[key]) / len(mttr_log[key])
                log.info(f"SESSION RECOVERED: {new.router} → {new.peer} "
                         f"(recovery {recovery_s:.0f}s, avg MTTR {avg:.0f}s)")
                send_alert(
                    f"BGP Session RECOVERED: {new.router} → {new.peer}",
                    f"Router: {new.router}\nPeer: {new.peer}\n"
                    f"Recovery time: {recovery_s:.0f}s\nAvg MTTR: {avg:.0f}s\n"
                    f"Prefixes received: {new.pfx_rcvd}",
                    is_recovery=True,
                )
        else:
            new.last_change = old.last_change

        sessions[key] = new


# ── Prometheus metrics ─────────────────────────────────────────────────────────
def build_metrics() -> str:
    with sessions_lock:
        snap = dict(sessions)
    lines = [
        "# HELP bgp_session_up BGP session state (1=Established 0=down)",
        "# TYPE bgp_session_up gauge",
    ]
    for (router, peer), s in snap.items():
        up = 1 if s.state == "Established" else 0
        lines.append(f'bgp_session_up{{router="{router}",peer="{peer}",state="{s.state}"}} {up}')
    lines += [
        "",
        "# HELP bgp_prefixes_received Prefixes received from peer",
        "# TYPE bgp_prefixes_received gauge",
    ]
    for (router, peer), s in snap.items():
        lines.append(f'bgp_prefixes_received{{router="{router}",peer="{peer}"}} {s.pfx_rcvd}')
    lines += [
        "",
        "# HELP bgp_session_uptime_seconds Session uptime in seconds",
        "# TYPE bgp_session_uptime_seconds gauge",
    ]
    for (router, peer), s in snap.items():
        lines.append(f'bgp_session_uptime_seconds{{router="{router}",peer="{peer}"}} {s.uptime_sec}')
    lines += [
        "",
        "# HELP bgp_session_flaps_total Session flap count since alerter start",
        "# TYPE bgp_session_flaps_total counter",
    ]
    for (router, peer), s in snap.items():
        lines.append(f'bgp_session_flaps_total{{router="{router}",peer="{peer}"}} {s.flaps}')
    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/metrics", "/"):
            body = build_metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_metrics_server():
    server = HTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
    log.info(f"Metrics endpoint: http://0.0.0.0:{METRICS_PORT}/metrics")
    server.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────────────
def install_deps():
    import subprocess, sys
    log.info("Installing Python dependencies...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "requests", "docker", "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log.info("Dependencies installed.")


def main():
    install_deps()

    threading.Thread(target=start_metrics_server, daemon=True).start()

    log.info(f"BGP Alerter starting — polling every {POLL_INTERVAL}s")
    log.info(f"Webhook: {'configured (' + WEBHOOK_URL[:30] + '...)' if WEBHOOK_URL else 'not set (console only)'}")
    log.info("Waiting 25s for routers to boot and BGP to converge...")
    time.sleep(25)

    while True:
        up_count = 0
        total_count = 0
        for r in ROUTERS:
            found = poll_router(r["container"], r["label"])
            for s in found:
                process_session(s)
                total_count += 1
                if s.state == "Established":
                    up_count += 1

        log.info(f"Poll complete — {up_count}/{total_count} sessions Established")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
