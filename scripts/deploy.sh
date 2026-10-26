#!/usr/bin/env bash
# Deploy FinSight by image tag, smoke-test it, and roll back to the previous tag if it fails.
#   scripts/deploy.sh v0.2.0        deploy that tag (pulled from the registry, or built locally)
#   scripts/deploy.sh --rollback    deploy the tag that ran before the current one
# Tags are remembered in deploy/.tags (current on the last line). Spec v1.1, 6.5 / PROD-03.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f deploy/docker-compose.deploy.yml)
TAGS=deploy/.tags
touch "$TAGS"

if [[ "${1:-}" == "--rollback" ]]; then
  tag=$(tail -n 2 "$TAGS" | head -n 1)
  [[ -n "$tag" && $(wc -l < "$TAGS") -ge 2 ]] || { echo "no previous tag to roll back to"; exit 1; }
else
  tag=${1:?usage: scripts/deploy.sh <tag> | --rollback}
fi
previous=$(tail -n 1 "$TAGS" || true)

echo "Deploying $tag (running now: ${previous:-nothing})"
export FINSIGHT_TAG=$tag
"${COMPOSE[@]}" pull api ui 2>/dev/null || echo "pull skipped: using local images for $tag"
"${COMPOSE[@]}" up -d --wait

# Smoke test inside the network: health, a refused request without the key, one real question.
smoke() {
  "${COMPOSE[@]}" exec -T api python - <<'PY'
import json, os, urllib.error, urllib.request
base = "http://localhost:8000"
assert urllib.request.urlopen(f"{base}/health", timeout=5).status == 200
try:
    urllib.request.urlopen(urllib.request.Request(f"{base}/usage/today"), timeout=5)
    raise SystemExit("a request without the key was accepted")
except urllib.error.HTTPError as err:
    assert err.code == 401, err.code
request = urllib.request.Request(
    f"{base}/usage/today", headers={"X-API-Key": os.environ["FINSIGHT_SERVICE_KEY"]}
)
print("usage:", json.load(urllib.request.urlopen(request, timeout=30)))
PY
}

if smoke; then
  [[ "$tag" == "$previous" ]] || echo "$tag" >> "$TAGS"
  echo "Deployed $tag"
else
  echo "Smoke test failed on $tag"
  if [[ -n "$previous" && "$previous" != "$tag" ]]; then
    echo "Rolling back to $previous"
    FINSIGHT_TAG=$previous "${COMPOSE[@]}" up -d --wait
  fi
  exit 1
fi
