#!/usr/bin/env bash
# End-to-end smoke test against a running GigSim instance.
# Requires: curl, jq, a seeded DB, and a running API (`make gigsim`).
# Set SMOKE_SUBMIT=1 to submit a real proposal and verify idempotent replay,
# and SMOKE_WAIT_REPLY=1 to wait (up to 40s) for the simulated client reply.
set -euo pipefail

BASE="${GIGSIM_BASE_URL:-http://localhost:8081}"
TOKEN="${GIGSIM_SMOKE_TOKEN:-test-token-ml-engineer}"
ADMIN="${GIGSIM_ADMIN_TOKEN:-gigsim-admin-token}"

pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

api() {
  local method=$1 path=$2 token=$3 body=${4:-}
  local attempt response code payload args headers retry_after waited=0
  for attempt in 1 2 3 4 5 6; do
    headers=$(mktemp)
    args=(-sS -X "$method" -H "Authorization: Bearer $token" -H "Content-Type: application/json"
      -D "$headers" -w $'\n%{http_code}')
    if [ -n "$body" ]; then args+=(-d "$body"); fi
    response=$(curl "${args[@]}" "$BASE$path") || { rm -f "$headers"; sleep 0.5; continue; }
    code=${response##*$'\n'}
    payload=${response%$'\n'*}
    if [ "$code" = "429" ]; then
      retry_after=$(awk 'tolower($1)=="retry-after:" {gsub("\r","",$2); print $2}' "$headers")
      rm -f "$headers"
      if [ "$waited" = "0" ]; then
        sleep "${retry_after:-2}"
        waited=1
      else
        sleep 2
      fi
      continue
    fi
    rm -f "$headers"
    if [ "$code" -ge 500 ]; then sleep 0.5; continue; fi
    printf '%s' "$payload"
    return 0
  done
  printf '%s' "$payload"
  echo "FAIL: repeated server errors on $method $path (last HTTP $code);" \
    "for 429 wait 60s or raise GIGSIM_RATE_LIMIT_PER_MINUTE" >&2
  return 1
}

for attempt in 1 2 3 4 5; do
  curl -fsS "$BASE/health" >/dev/null 2>&1 && break
  [ "$attempt" = 5 ] && fail "GigSim not reachable at $BASE (start it with: make gigsim)"
  sleep 1
done
curl -fsS "$BASE/health" | jq -e '.status == "ok"' >/dev/null || fail "health"
pass "health"

JOBS=$(api GET "/jobs?page=1" "$TOKEN")
echo "$JOBS" | jq -e '.total > 0 and (.items | length) > 0' >/dev/null || fail "jobs search"
JOB_ID=$(echo "$JOBS" | jq -r '.items[0].id')
CLIENT_ID=$(echo "$JOBS" | jq -r '.items[0].client_id // empty')
JOB_SKILLS=$(echo "$JOBS" | jq -c '.items[0].skills')
pass "jobs search ($(echo "$JOBS" | jq -r '.total') jobs, id=$JOB_ID)"

api GET "/jobs/$JOB_ID" "$TOKEN" | jq -e --arg id "$JOB_ID" '.id == $id' >/dev/null \
  || fail "job detail"
pass "job detail"

api GET "/connects" "$TOKEN" | jq -e '.balance >= 0' >/dev/null || fail "connects"
pass "connects balance"

if [ -n "$CLIENT_ID" ]; then
  api GET "/clients/$CLIENT_ID/history" "$TOKEN" | jq -e --arg id "$CLIENT_ID" '.client.id == $id' >/dev/null \
    || fail "client history"
  pass "client history ($CLIENT_ID)"
fi

DRY=$(api POST "/proposals" "$TOKEN" \
  "$(jq -nc --arg job "$JOB_ID" '{job_id:$job,cover_letter:"Smoke test cover letter.",idempotency_key:"smoke-dry-run",dry_run:true}')")
echo "$DRY" | jq -e '.status == "dry_run"' >/dev/null || fail "proposal dry run"
pass "proposal dry run (no connects spent)"

if [ "${SMOKE_SUBMIT:-0}" = "1" ]; then
  KEY="smoke-$(date +%s)-$$"
  BODY=$(jq -nc --arg job "$JOB_ID" --arg key "$KEY" --argjson skills "$JOB_SKILLS" \
    '{job_id:$job,cover_letter:"Smoke test proposal with relevant skills.",skills_mentioned:$skills,idempotency_key:$key,dry_run:false}')
  FIRST=$(api POST "/proposals" "$TOKEN" "$BODY")
  echo "$FIRST" | jq -e '.status == "submitted"' >/dev/null \
    || fail "proposal submit failed (insufficient connects? run: make seed-reset): $FIRST"
  REPLAY=$(api POST "/proposals" "$TOKEN" "$BODY")
  echo "$REPLAY" | jq -e '.idempotent_replay == true' >/dev/null || fail "idempotent replay"
  pass "proposal submit + idempotent replay"

  if [ "${SMOKE_WAIT_REPLY:-0}" = "1" ]; then
    PROPOSAL_ID=$(echo "$FIRST" | jq -r '.id')
    CONVERSATION_ID=$(echo "$FIRST" | jq -r '.conversation_id')
    for attempt in $(seq 1 20); do
      PROPOSALS=$(api GET "/proposals" "$TOKEN")
      echo "$PROPOSALS" | jq -e 'type == "array"' >/dev/null 2>&1 \
        || fail "GET /proposals returned unexpected payload: $PROPOSALS"
      STATUS=$(echo "$PROPOSALS" | jq -r --argjson id "$PROPOSAL_ID" \
        '.[] | select(.id == $id) | .status' | head -1)
      if [ -n "$STATUS" ] && [ "$STATUS" != "submitted" ]; then
        pass "simulated outcome: $STATUS"
        if [ "$STATUS" != "no_reply" ]; then
          MESSAGES=$(api GET "/messages?conversation_id=$CONVERSATION_ID" "$TOKEN")
          [ "$(echo "$MESSAGES" | jq 'length')" -gt 0 ] || fail "outcome $STATUS but no message"
        fi
        break
      fi
      [ "$attempt" = 20 ] && fail "no reply simulation within 40s"
      sleep 2
    done
  fi
fi

STATS=$(api GET "/admin/stats" "$ADMIN")
echo "$STATS" | jq -e '.jobs_total > 0 and .clients > 0' >/dev/null || fail "admin stats"
pass "admin stats (jobs=$(echo "$STATS" | jq -r '.jobs_total'), clients=$(echo "$STATS" | jq -r '.clients'), bad_actors=$(echo "$STATS" | jq -r '.bad_actors'))"

echo "OK: GigSim smoke test passed"
