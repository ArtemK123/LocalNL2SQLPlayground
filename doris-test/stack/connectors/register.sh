#!/bin/sh
set -eu
CONNECT_URL="${CONNECT_URL:-http://connect:8083}"
CONNECTOR_JSON="${CONNECTOR_JSON:-/connectors/bird-postgres-source.json}"
TMP="/tmp/bird-postgres-source.resolved.json"

echo "Waiting for Kafka Connect at ${CONNECT_URL}..."
for i in $(seq 1 90); do
  if curl -sf "${CONNECT_URL}/" >/dev/null 2>&1; then break; fi
  sleep 2
done

HOST="${BIRD_PG_HOST:-bird-postgres}"
sed "s/BIRD_PG_HOST_PLACEHOLDER/${HOST}/g" "${CONNECTOR_JSON}" > "${TMP}"

NAME=$(sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${TMP}" | head -1)
curl -sf -X DELETE "${CONNECT_URL}/connectors/${NAME}" >/dev/null 2>&1 || true
curl -sf -X POST -H "Content-Type: application/json" --data @"${TMP}" "${CONNECT_URL}/connectors"
echo "Registered connector ${NAME} -> PG host ${HOST}"
sleep 45
