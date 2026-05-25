<img width="1059" height="713" alt="image" src="https://github.com/user-attachments/assets/25e39950-4569-4091-ac85-3fa866d4f163" /><div align="center">

# 🌐 BGP Multi-AS Lab

### A Real-World ISP-Style BGP Simulation with FRRouting, Route Reflectors & Full Observability

<p>
  <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/FRRouting-FF6B6B?logo=linux&logoColor=white" />
  <img src="https://img.shields.io/badge/Prometheus-E6522C?logo=prometheus&logoColor=white" />
  <img src="https://img.shields.io/badge/Grafana-F46800?logo=grafana&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Ansible-EE0000?logo=ansible&logoColor=white" />
</p>

<p>
  <img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Platform-Docker%20Desktop%20(Windows)-blue?style=for-the-badge&logo=docker" />
  <img src="https://img.shields.io/badge/Architecture-Multi--AS%20BGP-informational?style=for-the-badge" />
</p>

</div>

---

## Overview

A production-style **multi–Autonomous System (AS) BGP lab** built using FRRouting inside Docker containers.

This project simulates how real ISPs exchange routes using **eBGP and iBGP with a Route Reflector**, while exposing full observability via Prometheus, Grafana, and a Python-based BGP alerting engine.


### What it demonstrates:
- Multi-AS BGP topology design (ISP-style)
- eBGP peering between autonomous systems
- iBGP Route Reflector architecture (AS65002 core)
- Real FRRouting (not simulated CLI outputs)
- Network telemetry via Prometheus metrics exporter
- Real-time alerting on BGP session state changes
- Container-based network emulation (Windows-safe)
- Infrastructure-as-code + automation with Ansible

---

## Architecture

![BGP Multi-AS Lab Topology](https://raw.githubusercontent.com/MrN7King/bgp-multi-as-lab/main/topology.png)                    
---

## Stack

| Component | Role |
|-----------|------|
| FRRouting ×4 | Real BGP daemons — eBGP + iBGP |
| R4-RR | iBGP Route Reflector inside AS65002 |
| Prometheus | Scrapes BGP metrics every 15s |
| Grafana | Live dashboard at localhost:3000 |
| bgp-alerter | Polls sessions, fires Slack/Discord alerts |
| Ansible (Docker) | Windows-safe — runs inside Alpine Linux container |

---

## Key Features

- BGP session state monitoring (Established / Down)
- Prefix tracking per peer
- Session uptime calculation
- Flap detection + MTTR tracking
- Prometheus metrics endpoint (`/metrics`)
- Slack / Discord webhook alert support
- Auto-discovery of router peers via FRR JSON output
- Stateful monitoring across restarts

---

## Quick start

```powershell
# 1. Copy env file
copy .env.example .env

# 2. Start all 7 services
docker compose up -d

# 3. Wait 25 seconds, then verify
python3 scripts/bgp_verify.py
```

Open Grafana: http://localhost:3000 — admin / bgplab123

---

## Ansible playbooks (Windows PowerShell)

Ansible runs inside an Alpine Linux container so it works on Windows.
No WSL2 needed. Just make sure the lab is up first.

```powershell
# Check all BGP sessions are Established
docker compose run --rm ansible verify_bgp.yml

# Push FRR config to all routers (idempotent — safe to run anytime)
docker compose run --rm ansible push_config.yml

# Security audit — checks MD5 auth, TTL security, max-prefix
docker compose run --rm ansible harden_bgp.yml

# Full automated failover test (takes ~45s)
docker compose run --rm ansible failover_test.yml
```

The `--rm` flag removes the Ansible container after each run.
The router containers stay running.

---

## Alerting

Edit `.env` and add your webhook URL:

```
WEBHOOK_URL=https://discord.com/api/webhooks/YOUR/WEBHOOK
```

Then restart the alerter:

```powershell
docker compose up -d bgp-alerter
```

Test it manually:

```powershell
# Trigger alert (session goes down within 30s)
docker exec bgp-r1 ip link set eth0 down

# Watch alerter
docker logs -f bgp-alerter

# Restore (recovery alert fires)
docker exec bgp-r1 ip link set eth0 up
```

---

## Route Reflector

```powershell
docker exec bgp-r4-rr vtysh -c "show bgp summary"
docker exec bgp-r4-rr vtysh -c "show bgp neighbors 10.0.24.2"
```

Look for `Route-Reflector Client` in the neighbor output.

---

## IP plan

| Network | Subnet | Hosts |
|---------|--------|-------|
| R1-R2 link | 10.0.12.0/29 | R1=.2, R2=.3 |
| R2-R3 link | 10.0.23.0/29 | R2=.2, R3=.3 |
| R2-R4 link | 10.0.24.0/29 | R2=.2, R4=.3 |
| Management | 172.30.0.0/24 | R1=.11 R2=.12 R3=.13 R4=.14 Prometheus=.20 Grafana=.21 Alerter=.40 |

---

## Useful vtysh commands

```
docker exec -it bgp-r1 vtysh

show bgp summary
show ip bgp
show ip bgp community 65001:100
show bgp neighbors 10.0.12.3
show route-map
show ip prefix-list
```
---
Project Structure

```

bgp-multi-as-lab/
├── docker-compose.yml
├── .env.example
├── configs/
│   ├── r1/frr.conf
│   ├── r2/frr.conf
│   ├── r3/frr.conf
│   └── r4-rr/frr.conf
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   ├── provisioning/
│   └── dashboards/
├── scripts/
│   ├── bgp_verify.py
│   └── bgp_alerter.py
├── ansible/
│   ├── inventory/hosts.yml
│   ├── verify_bgp.yml
│   ├── push_config.yml
│   ├── harden_bgp.yml
│   └── failover_test.yml
└── wireshark/
    └── capture_filters.txt

```
---

## Clean up

```powershell
docker compose down
```

---
License
MIT – free to use, modify, and share.

Happy routing!
Built for networking students and NOC engineers – to turn BGP theory into observable reality.

---

<div align="center">
<sub>A project made during my free time · V.Gurunivasan BSc · (Hons) Computer Networking · CCNA in progress</sub>
</div>
