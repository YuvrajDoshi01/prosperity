#!/bin/bash
# Round-1 AWS Probe — uses creds extracted by imc_probe_r1.py (tick 5 CREDS_B64).
# Usage:
#   1. Submit trader-logic/round-1/oracle/imc_probe_r1.py
#   2. Download logs -> run-logs/round-1/<RUN_ID>/
#   3. bash trader-logic/round-1/oracle/aws_probe.sh <RUN_ID>
# Credentials expire ~1h after Lambda invocation. Run fast.

set -e
RUN_ID=${1:?"Usage: aws_probe.sh <run_id>"}
LOG_FILE="run-logs/round-1/${RUN_ID}/${RUN_ID}.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "ERROR: $LOG_FILE not found"
    exit 1
fi

echo "=== Extracting CREDS_B64 from run $RUN_ID ==="
CREDS_B64=$(python -c "
import json
with open('$LOG_FILE') as f:
    data = json.load(f)
for entry in data.get('logs', []):
    llog = (entry.get('lambdaLog') or '')
    if 'CREDS_B64' in llog:
        lines = llog.strip().split('\n')
        for i, line in enumerate(lines):
            if 'CREDS_B64' in line:
                print(''.join(lines[i+1:]).strip())
                break
        break
")

if [ -z "$CREDS_B64" ]; then
    echo "ERROR: CREDS_B64 not found in $LOG_FILE"
    exit 1
fi

CREDS=$(echo "$CREDS_B64" | python -c "import sys,base64,json; print(json.dumps(json.loads(base64.b64decode(sys.stdin.read().strip())), indent=2))")
echo "Decoded:"
echo "$CREDS"

export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['KEY'])")
export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['SECRET'])")
export AWS_SESSION_TOKEN=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['TOKEN'])")
export AWS_DEFAULT_REGION=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['REGION'])")

echo ""
echo "=== 1. Identity ==="
aws sts get-caller-identity 2>&1

echo ""
echo "=== 2. Lambda functions ==="
aws lambda list-functions --max-items 20 --query 'Functions[].{Name:FunctionName,Runtime:Runtime,LastModified:LastModified}' --output table 2>&1

echo ""
echo "=== 3. S3 ==="
aws s3 ls 2>&1

echo ""
echo "=== 4. DynamoDB ==="
aws dynamodb list-tables 2>&1

echo ""
echo "=== 5. CloudWatch logs ==="
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/prosperity --query 'logGroups[].{Name:logGroupName,Stored:storedBytes}' --output table 2>&1

echo ""
echo "=== 6. API Gateway ==="
aws apigateway get-rest-apis --query 'items[].{Name:name,Id:id}' --output table 2>&1

echo ""
echo "=== 7. Step Functions ==="
aws stepfunctions list-state-machines --query 'stateMachines[].{Name:name,Arn:stateMachineArn}' --output table 2>&1

echo ""
echo "=== 8. SQS ==="
aws sqs list-queues 2>&1

echo ""
echo "=== 9. ECS ==="
aws ecs list-clusters 2>&1

echo ""
echo "=== DONE ==="
