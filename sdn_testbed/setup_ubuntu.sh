#!/usr/bin/env bash
# Turnkey Ubuntu 22.04 / 24.04 provisioning script for the Sintra Mininet + POX testbed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POX_DIR="${HOME}/pox"

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

echo "=== Installing Sintra Python dependencies into .venv ==="
cd "${REPO_DIR}"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo ""
echo "=== Setup Complete ==="
echo "Terminal 1 (Start POX controller):"
echo "  PYTHONPATH=${REPO_DIR} python3 ${POX_DIR}/pox.py log.level --INFO sdn_testbed.pox_sintra_controller --rest_port=8080 --policy=sintra --cooldown=5"
echo ""
echo "Terminal 2 (Run automated Mininet closed-loop experiments):"
echo "  sudo ${REPO_DIR}/.venv/bin/python ${REPO_DIR}/sdn_testbed/run_experiments.py --mode mininet --trials 5"
