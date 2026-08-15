#!/bin/bash
# Host bootstrap for analytics EC2 (vm.max_map_count for Doris BE).
set -euo pipefail
sysctl -w vm.max_map_count=2000000
grep -q vm.max_map_count /etc/sysctl.conf || echo "vm.max_map_count=2000000" >> /etc/sysctl.conf
echo "Analytics host ready for docker compose."
