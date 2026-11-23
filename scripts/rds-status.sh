#!/usr/bin/env bash
# Shows where the RDS primary and standby are now, plus recent failover events.
set -euo pipefail
DB=${1:-examhub-prod-db}
aws rds describe-events --source-identifier "$DB" --source-type db-instance --duration 120 \
  --query 'Events[?contains(Message, `failover`)].[Date,Message]' --output text
aws rds describe-db-instances --db-instance-identifier "$DB" \
  --query 'DBInstances[0].{primary:AvailabilityZone,standby:SecondaryAvailabilityZone,multiAZ:MultiAZ,status:DBInstanceStatus}' --output table
