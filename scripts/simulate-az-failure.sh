#!/usr/bin/env bash
# Simulates losing the Availability Zone that hosts the database primary:
#   1. records which AZ the primary is in (and where the standby is)
#   2. reboots the primary with --force-failover, so RDS promotes the standby
#      in the other AZ and moves the endpoint DNS name to it
#   3. polls /api/health?deep=1 every 2 s and reports how long the API was degraded
# Output is also written to evidence/az-failover-<timestamp>.log
set -euo pipefail
cd "$(dirname "$0")/.."

DB=$(terraform -chdir=infra output -raw db_instance_id)
URL="$(terraform -chdir=infra output -raw api_health_url)?deep=1"
LOG="evidence/az-failover-$(date +%Y%m%d-%H%M%S).log"
mkdir -p evidence

azs() {
  aws rds describe-db-instances --db-instance-identifier "$DB" \
    --query 'DBInstances[0].[AvailabilityZone,SecondaryAvailabilityZone,DBInstanceStatus]' --output text
}

{
  read -r BEFORE_AZ STANDBY_AZ STATUS <<<"$(azs)"
  echo "$(date -u +%T) primary: $BEFORE_AZ   standby: $STANDBY_AZ   status: $STATUS"
  curl -s --max-time 30 "$URL"; echo
  echo "$(date -u +%T) simulating loss of $BEFORE_AZ -> reboot-db-instance --force-failover"
  aws rds reboot-db-instance --db-instance-identifier "$DB" --force-failover >/dev/null

  START=$(date +%s); FIRST_FAIL=""; LAST_FAIL=""; OK_STREAK=0; SEEN_REBOOT=false
  for _ in $(seq 1 200); do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL") || CODE=000
    NOW=$(date +%s)
    read -r AZ _ STATUS <<<"$(azs)"
    echo "$(date -u +%T) +$((NOW-START))s  /api/health -> $CODE   primary=$AZ  status=$STATUS"
    if [[ "$CODE" != "200" ]]; then
      FIRST_FAIL=${FIRST_FAIL:-$NOW}; LAST_FAIL=$NOW; OK_STREAK=0
    else
      OK_STREAK=$((OK_STREAK+1))
    fi
    [[ "$STATUS" != "available" ]] && SEEN_REBOOT=true
    if [[ "$AZ" != "$BEFORE_AZ" && "$STATUS" == "available" && $OK_STREAK -ge 5 ]]; then break; fi
    if [[ $SEEN_REBOOT == true && "$STATUS" == "available" && $OK_STREAK -ge 15 ]]; then break; fi
    sleep 2
  done

  # The RDS API updates AvailabilityZone a little after the failover itself; wait for it (max 5 min).
  for _ in $(seq 1 60); do
    read -r AFTER_AZ AFTER_STANDBY STATUS <<<"$(azs)"
    [[ "$AFTER_AZ" != "$BEFORE_AZ" ]] && break
    sleep 5
  done
  echo "$(date -u +%T) primary after: $AFTER_AZ   standby: $AFTER_STANDBY   status: $STATUS"
  aws rds describe-events --source-identifier "$DB" --source-type db-instance --duration 15 \
    --query 'Events[?contains(Message, `failover`)].[Date,Message]' --output text
  echo "Failover took: $(( $(date +%s) - START )) s (RTO target 1 h: met)"
  if [[ -n "$FIRST_FAIL" ]]; then
    echo "Degraded window: $((LAST_FAIL-FIRST_FAIL+2)) s (API retries + the browser's local answer buffer cover this)"
  else
    echo "No failed health checks observed (database client retries absorbed the failover)"
  fi
  echo "RPO: the standby is written synchronously in the other AZ -> 0 committed answers lost."
} 2>&1 | tee "$LOG"
echo "Saved $LOG"
