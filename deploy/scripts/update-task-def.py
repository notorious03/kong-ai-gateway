"""
Update ECS Task Definition with new image tags and redeploy service.
Usage: python update-task-def.py [guardrails-tag] [kong-tag]
Default: latest
"""
import os, sys, json, boto3, copy, time
os.environ.pop('AWS_ENDPOINT_URL', None)

REGION = 'us-east-1'
ACCOUNT = '435627631709'
CLUSTER = 'kong-ai-gateway-cluster'
SERVICE = 'kong-ai-gateway-service'
FAMILY = 'kong-ai-gateway'

guardrails_tag = sys.argv[1] if len(sys.argv) > 1 else 'latest'
kong_tag = sys.argv[2] if len(sys.argv) > 2 else 'latest'

print(f'Updating task def: guardrails:{guardrails_tag}, kong:{kong_tag}')

ecs = boto3.client('ecs', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)

td = ecs.describe_task_definition(taskDefinition=FAMILY)['taskDefinition']
containers = copy.deepcopy(td['containerDefinitions'])

for c in containers:
    if c['name'] == 'guardrails':
        c['image'] = f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/ai-guardrails:{guardrails_tag}'
        print(f'  guardrails image: {c["image"]}')
    elif c['name'] == 'kong':
        c['image'] = f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/kong-gateway:{kong_tag}'
        print(f'  kong image: {c["image"]}')

resp = ecs.register_task_definition(
    family=FAMILY,
    taskRoleArn=td['taskRoleArn'],
    executionRoleArn=td['executionRoleArn'],
    networkMode=td['networkMode'],
    containerDefinitions=containers,
    requiresCompatibilities=td['requiresCompatibilities'],
    cpu=td['cpu'],
    memory=td['memory'],
    volumes=td.get('volumes', []),
    runtimePlatform=td.get('runtimePlatform', {})
)

new_rev = resp['taskDefinition']['revision']
print(f'New Task Definition: {FAMILY}:{new_rev}')

ecs.update_service(
    cluster=CLUSTER,
    service=SERVICE,
    taskDefinition=f'{FAMILY}:{new_rev}',
    forceNewDeployment=True
)
print(f'Service updated to {FAMILY}:{new_rev}')

print('\nPolling for HEALTHY...')
elapsed = 0
while elapsed < 600:
    time.sleep(30)
    elapsed += 30

    tasks = ecs.list_tasks(cluster=CLUSTER, desiredStatus='RUNNING')['taskArns']
    if not tasks:
        print(f'  [{elapsed}s] no RUNNING tasks')
        continue

    desc = ecs.describe_tasks(cluster=CLUSTER, tasks=tasks)['tasks']
    for t in desc:
        rev = t['taskDefinitionArn'].split(':')[-1]
        if rev != str(new_rev):
            continue
        h = t.get('healthStatus', 'UNKNOWN')
        c_health = {c['name']: c.get('healthStatus','?') for c in t.get('containers',[])}
        pub_ip = 'N/A'
        for att in t.get('attachments', []):
            if att['type'] == 'ElasticNetworkInterface':
                eni_id = next((d['value'] for d in att['details'] if d['name']=='networkInterfaceId'), None)
                if eni_id:
                    try:
                        eni = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])['NetworkInterfaces'][0]
                        pub_ip = eni.get('Association',{}).get('PublicIp','N/A')
                    except:
                        pass
        print(f'  [{elapsed}s] rev:{rev} | {t["lastStatus"]}/{h} | {c_health} | {pub_ip}')
        if h == 'HEALTHY':
            print(f'\nHEALTHY! http://{pub_ip}:8000')
            exit(0)

print('Timeout waiting for HEALTHY')
