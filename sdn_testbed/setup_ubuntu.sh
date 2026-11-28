#!/usr/bin/env bash
# Turnkey Ubuntu 22.04 / 24.04 provisioning script for the Sintra Mininet + POX testbed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POX_DIR="${HOME}/pox"
VENV_DIR="${SINTRA_VENV:-${HOME}/sintra-venv}"

echo "=== Installing Mininet, Open vSwitch, iperf3, and Python tools ==="
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch iputils-ping iperf3 git python3-venv python3-pip

echo "=== Enabling Open vSwitch service ==="
sudo systemctl enable --now openvswitch-switch

echo "=== Cloning POX (gar-experimental Python 3 branch) ==="
if [ ! -d "${POX_DIR}" ]; then
    git clone -b gar-experimental https://github.com/noxrepo/pox.git "${POX_DIR}"
else
    echo "POX already exists at ${POX_DIR}"
fi

echo "=== Installing Sintra Python dependencies into ${VENV_DIR} (with system site-packages for Mininet) ==="
python3 -m venv --system-site-packages "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${REPO_DIR}/requirements.txt"

echo ""
echo "=== Setup Complete ==="
echo "Terminal 1 (Start POX controller):"
echo "  cd ${REPO_DIR} && PYTHONPATH=${REPO_DIR} python3 ${POX_DIR}/pox.py log.level --INFO sdn_testbed.pox_sintra_controller --rest_port=8080 --policy=sintra --cooldown=5"
echo ""
echo "Terminal 2 (Quick 1-trial sanity check):"
echo "  cd ${REPO_DIR} && sudo ${VENV_DIR}/bin/python -m sdn_testbed.run_experiments --mode mininet --trials 1 --scenarios latency_spike jitter_spike"
echo ""
echo "Terminal 2 (Full 5-trial paper dataset):"
echo "  cd ${REPO_DIR} && sudo ${VENV_DIR}/bin/python -m sdn_testbed.run_experiments --mode mininet --trials 5"
