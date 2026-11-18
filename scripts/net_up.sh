#!/usr/bin/env bash
# Bring up the two allowlist proxies on an INTERNAL docker network (no route out except via proxy).
#   scb-egress-agent: Anthropic API + PyPI      scb-egress-eval: PyPI only
set -euo pipefail
HERE=$(realpath "$(dirname "$0")")
docker network inspect scb-cellnet   >/dev/null 2>&1 || docker network create --internal scb-cellnet >/dev/null
docker network inspect scb-egressnet >/dev/null 2>&1 || docker network create scb-egressnet >/dev/null
for k in agent eval; do
  img="scb-egress-$k:1"
  docker image inspect "$img" >/dev/null 2>&1 || docker build -q -t "$img" "$HERE/instruments/egress-$k" >/dev/null
  if [ "$(docker inspect -f '{{.State.Running}} {{.Config.Image}}' scb-egress-$k 2>/dev/null)" != "true $img" ]; then
    docker rm -f scb-egress-$k >/dev/null 2>&1 || true
    docker run -d --name scb-egress-$k --network scb-cellnet "$img" >/dev/null
    docker network connect scb-egressnet scb-egress-$k
  fi
done
echo "proxies up: $(docker ps --filter name=scb-egress --format '{{.Names}}' | tr '\n' ' ')"
