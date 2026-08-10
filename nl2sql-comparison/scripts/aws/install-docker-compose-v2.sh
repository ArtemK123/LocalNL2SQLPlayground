#!/bin/bash
# Amazon Linux 2023: docker-compose-plugin is often missing from dnf.
# Installs Docker Compose v2 CLI plugin to /usr/local/lib/docker/cli-plugins/

set -euo pipefail

if docker compose version >/dev/null 2>&1; then
  echo "docker compose already available: $(docker compose version)"
  exit 0
fi

COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-v2.32.4}"
ARCH="$(uname -m)"
case "${ARCH}" in
  x86_64) COMPOSE_ARCH="x86_64" ;;
  aarch64) COMPOSE_ARCH="aarch64" ;;
  *)
    echo "Unsupported arch for compose install: ${ARCH}" >&2
    exit 1
    ;;
esac

mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${COMPOSE_ARCH}" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
