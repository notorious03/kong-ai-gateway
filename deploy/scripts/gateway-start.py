"""
Kong AI Gateway 복구 스크립트
사용법: python gateway-start.py

ECS 서비스를 시작하고 HEALTHY 상태까지 대기합니다.
면접 준비 시 또는 포트폴리오 시연 전에 실행하세요.
"""
import os, sys, time, boto3

os.environ.pop('AWS_ENDPOINT_URL', None)

REGION  = 'us-east-1'
CLUSTER = 'kong-ai-gateway-cluster'
SERVICE = 'kong-ai-gateway-service'
TIMEOUT = 600   # 최대 10분 대기

ecs = boto3.client('ecs', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)

# ── 현재 상태 확인 ──────────────────────────────────────────
svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])['services'][0]
current = svc['desiredCount']

if current >= 1 and svc['runningCount'] >= 1:
    print(f'이미 실행 중입니다 (desired={current}, running={svc["runningCount"]})')
    print('IP 확인 중...')
else:
    print('ECS 서비스 시작 중...')
    ecs.update_service(cluster=CLUSTER, service=SERVICE, desiredCount=1)
    print('시작 요청 완료. HEALTHY 대기 중...')

# ── HEALTHY 대기 루프 ─────────────────────────────────────────
def get_public_ip():
    tasks = ecs.list_tasks(cluster=CLUSTER, desiredStatus='RUNNING')['taskArns']
    if not tasks:
        return None, None
    task = ecs.describe_tasks(cluster=CLUSTER, tasks=[tasks[0]])['tasks'][0]
    for att in task.get('attachments', []):
        if att['type'] == 'ElasticNetworkInterface':
            eni_id = next(
                (d['value'] for d in att['details'] if d['name'] == 'networkInterfaceId'),
                None
            )
            if eni_id:
                eni = ec2.describe_network_interfaces(
                    NetworkInterfaceIds=[eni_id]
                )['NetworkInterfaces'][0]
                pub_ip = eni.get('Association', {}).get('PublicIp')
                containers = {
                    c['name']: c.get('lastStatus')
                    for c in task.get('containers', [])
                }
                health = {
                    c['name']: c.get('healthStatus', 'UNKNOWN')
                    for c in task.get('containers', [])
                }
                return pub_ip, health
    return None, None

start = time.time()
interval = 20
while time.time() - start < TIMEOUT:
    elapsed = int(time.time() - start)
    ip, health = get_public_ip()
    svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])['services'][0]

    status = svc.get('deployments', [{}])[0].get('rolloutState', 'UNKNOWN')
    running = svc['runningCount']
    desired = svc['desiredCount']

    print(f'  [{elapsed:>3}s] running:{running}/{desired} | 컨테이너:{health} | IP:{ip}')

    if running >= 1 and ip and health:
        all_healthy = all(v == 'HEALTHY' for v in health.values())
        if all_healthy:
            print()
            print('=' * 55)
            print('  GATEWAY HEALTHY!')
            print('=' * 55)
            print(f'  Kong URL  : http://{ip}:8000')
            print(f'  Admin URL : http://{ip}:8001')
            print()
            print('── Claude Code 연결 설정 ──────────────────────────')
            print(f'  [PowerShell]')
            print(f'  $env:AWS_ENDPOINT_URL = "http://{ip}:8000"')
            print()
            print(f'  [영구 설정 - Windows 레지스트리]')
            print(f'  [Environment]::SetEnvironmentVariable(')
            print(f'    "AWS_ENDPOINT_URL", "http://{ip}:8000", "User")')
            print()
            print('  ※ VS Code를 재시작해야 환경변수가 반영됩니다.')
            print('─' * 55)
            sys.exit(0)

    time.sleep(interval)

print()
print('⚠  타임아웃: 컨테이너가 HEALTHY 상태가 되지 않았습니다.')
print('   CloudWatch Logs에서 에러를 확인하세요:')
print('   /ecs/kong-ai-gateway/guardrails')
print('   /ecs/kong-ai-gateway/kong')
sys.exit(1)
