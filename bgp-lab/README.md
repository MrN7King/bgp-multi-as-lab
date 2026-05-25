# BGP Multi-AS Lab v2

> Four autonomous systems · FRRouting · iBGP Route Reflector · Prometheus · Grafana · Python Alerter · Ansible (Docker-based, Windows-safe)

```
  AS65001        AS65002 (transit)              AS65003
  R1             R2 ←──iBGP──→ R4-RR            R3
  10.0.12.2 ─── 10.0.12.3   10.0.24.2─10.0.24.3  10.0.23.3
       eBGP                               eBGP
```

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

## Clean up

```powershell
docker compose down
```
