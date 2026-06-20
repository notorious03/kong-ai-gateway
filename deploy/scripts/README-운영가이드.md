# 운영 가이드 — 비용 최소화 모드

## 현재 상태 (절약 모드)

| 항목 | 상태 | 월 비용 |
|------|------|---------|
| ECS Fargate 태스크 | **중지** (desiredCount=0) | $0 |
| ECR ai-guardrails 이미지 | 보존 (latest 1개) | ~$0.29/월 |
| ECR kong-gateway 이미지 | 보존 (latest 1개) | ~$0.03/월 |
| AWS Bedrock | 실사용분만 과금 | ~$0/일 (미사용 시) |
| **합계** | | **~$0.32/월** |

---

## 평소 Claude Code 사용 (비용 최소)

ECS 없이 Claude Code → Bedrock 직접 연결.

```
Claude Code → AWS Bedrock (직접)
```

**조건:** `AWS_ENDPOINT_URL` 환경변수가 없어야 함 (현재 제거됨).

VS Code를 재시작하면 즉시 Bedrock 직접 연결로 동작합니다.

---

## 게이트웨이 복구 (면접 시연 / 포트폴리오 데모)

```powershell
cd C:\workspaces\taesikpjt\kong-ai-gateway\deploy\scripts
python gateway-start.py
```

약 3~5분 후 아래와 같이 출력됩니다.

```
=======================================================
  GATEWAY HEALTHY!
=======================================================
  Kong URL  : http://<IP>:8000
  Admin URL : http://<IP>:8001

── Claude Code 연결 설정 ──────────────────────────────
  [PowerShell]
  $env:AWS_ENDPOINT_URL = "http://<IP>:8000"

  [영구 설정 - Windows 레지스트리]
  [Environment]::SetEnvironmentVariable(
    "AWS_ENDPOINT_URL", "http://<IP>:8000", "User")

  ※ VS Code를 재시작해야 환경변수가 반영됩니다.
```

> **주의:** ECS Fargate는 IP가 변경될 수 있습니다.
> 매번 시작 후 출력되는 IP를 확인하여 설정하세요.

---

## 게이트웨이 중지 (면접 후 반드시 실행)

```powershell
cd C:\workspaces\taesikpjt\kong-ai-gateway\deploy\scripts
python gateway-stop.py
```

중지 후 Claude Code를 다시 Bedrock 직접 연결로 되돌리려면:

```powershell
# 현재 세션만
Remove-Item Env:AWS_ENDPOINT_URL

# 영구 제거 (레지스트리)
[System.Environment]::SetEnvironmentVariable("AWS_ENDPOINT_URL", $null, "User")
# VS Code 재시작 필요
```

---

## 비용 비교

| 사용 패턴 | 월 비용 |
|-----------|---------|
| ECS 항상 실행 (이전) | ~$87/월 |
| ECS 완전 중지 (현재) | ~$0.32/월 |
| 면접 당일만 3시간 실행 | ~$0.32 + $0.36 = **~$0.68** |

---

## 빠른 참고

| 작업 | 명령 |
|------|------|
| 게이트웨이 시작 | `python gateway-start.py` |
| 게이트웨이 중지 | `python gateway-stop.py` |
| ECS 상태 확인 | `python -c "import os,boto3; os.environ.pop('AWS_ENDPOINT_URL',None); ecs=boto3.client('ecs',region_name='us-east-1'); svc=ecs.describe_services(cluster='kong-ai-gateway-cluster',services=['kong-ai-gateway-service'])['services'][0]; print('desired:', svc['desiredCount'], 'running:', svc['runningCount'])"` |
