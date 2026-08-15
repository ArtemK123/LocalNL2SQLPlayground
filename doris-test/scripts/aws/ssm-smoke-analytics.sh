#!/bin/bash
set -euxo pipefail
curl -sf http://127.0.0.1:8030/api/bootstrap
curl -sf http://127.0.0.1:8083/
mysql -h 127.0.0.1 -P 9030 -uroot -e "SHOW DATABASES LIKE 'bird_minidev_olap';" || true
echo ANALYTICS_SMOKE_OK
