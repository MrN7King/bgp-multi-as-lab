#!/bin/sh
# ============================================================
#  Ansible entrypoint — BGP Lab Docker runner
#  Alpine Linux container with ansible + docker-cli
#
#  Usage (from bgp-lab folder in PowerShell):
#    docker compose run --rm ansible verify_bgp.yml
#    docker compose run --rm ansible push_config.yml
#    docker compose run --rm ansible harden_bgp.yml
#    docker compose run --rm ansible failover_test.yml
# ============================================================
set -e

# Install on first run (subsequent runs are fast — apk cache is warm)
if ! command -v ansible-playbook > /dev/null 2>&1; then
    echo ">>> First run: installing Ansible + Docker CLI (once only)..."
    apk add --no-cache ansible docker-cli 2>&1 | tail -3
fi

PLAYBOOK="${1:-verify_bgp.yml}"
PLAYBOOK_PATH="/ansible/${PLAYBOOK}"

if [ ! -f "${PLAYBOOK_PATH}" ]; then
    echo ""
    echo "ERROR: '${PLAYBOOK}' not found. Available playbooks:"
    ls /ansible/*.yml | xargs -I{} basename {}
    exit 1
fi

echo ""
echo "======================================================"
echo "  BGP Lab Ansible Runner"
echo "  Playbook: ${PLAYBOOK}"
echo "======================================================"
echo ""

exec ansible-playbook \
    -i /ansible/inventory/hosts.yml \
    "${PLAYBOOK_PATH}" \
    "${@:2}"
