"""
Kong AI Gateway 중지 스크립트
사용법: python gateway-stop.py

ECS 서비스를 중지합니다 (desired=0).
ECR 이미지와 설정은 그대로 보존되므로 gateway-start.py로 언제든 복구됩니다.
"""
import os, boto3

os.environ.pop('AWS_ENDPOINT_URL', None)

REGION  = 'us-east-1'
CLUSTER = 'kong-ai-gateway-cluster'
SERVICE = 'kong-ai-gateway-service'

ecs = boto3.client('ecs', region_name=REGION)

svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])['services'][0]
current_desired = svc['desiredCount']
current_running = svc['runningCount']

if current_desired == 0:
    print('이미 중지 상태입니다 (desired=0).')
    print('비용이 청구되지 않고 있습니다.')
else:
    ecs.update_service(cluster=CLUSTER, service=SERVICE, desiredCount=0)
    print('ECS 서비스 중지 완료 (desired=0)')
    print()
    print('── 비용 절감 효과 ─────────────────────────────────')
    print('  Fargate 2vCPU/8GB: $0.00/시간 (실행 중인 태스크 없음)')
    print('  ECR 이미지 보존  : 이미지·설정 모두 그대로 유지')
    print('  복구 방법        : python gateway-start.py')
    print()
    print('── Claude Code 평소 사용 ─────────────────────────')
    print('  AWS_ENDPOINT_URL 환경변수를 제거하면')
    print('  Claude Code가 Bedrock을 직접 호출합니다.')
    print()
    print('  [PowerShell - 현재 세션만]')
    print('  Remove-Item Env:AWS_ENDPOINT_URL')
    print()
    print('  [영구 제거 - Windows 레지스트리]')
    print('  [Environment]::SetEnvironmentVariable(')
    print('    "AWS_ENDPOINT_URL", $null, "User")')
    print()
    print('  ※ VS Code를 재시작해야 반영됩니다.')
    print('─' * 55)
