# Kong AI Gateway + AI Guardrails on AWS ECS Fargate

AWS Bedrock(Claude Sonnet 4.6) 기반 LLM 게이트웨이로, **Kong AI Gateway**와 **AI Guardrails** 레이어를 조합한 프로덕션 수준의 아키텍처입니다.

## 아키텍처

```
Claude Code / AWS SDK
        │
        │  AWS_ENDPOINT_URL=http://<ECS_PUBLIC_IP>:8000
        ▼
┌─────────────────────────────────────┐
│        Kong AI Gateway (port 8000)  │
│  ┌─────────────────────────────────┐│
│  │  Plugins                        ││
│  │  - key-auth (OpenAI 경로)       ││
│  │  - rate-limiting (60/분, 1000/시)││
│  │  - request-transformer          ││
│  └─────────────────────────────────┘│
│  Routes:                            │
│  - POST /v1/chat/completions → 8080 │  ← OpenAI 호환 (apikey 필요)
│  - POST /model/{id}/invoke  → 8080  │  ← Bedrock 호환 (AWS SDK)
│  - GET/POST /mcp            → 8080  │  ← MCP Proxy
└─────────────────────────────────────┘
        │ (localhost:8080, same ECS task)
        ▼
┌─────────────────────────────────────┐
│     AI Guardrails (port 8080)       │
│  FastAPI + LLM Guard 0.3.14         │
│                                     │
│  Input Scanners:                    │
│  - Anonymize (PII 마스킹)           │
│  - PromptInjection (임계값 0.75)    │
│  - Toxicity (임계값 0.7)            │
│  - TokenLimit (4096)                │
│  - BanTopics / BanSubstrings (선택) │
│                                     │
│  Output Scanners:                   │
│  - Deanonymize (PII 복원)           │
│  - Sensitive (민감정보 마스킹)      │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  AWS Bedrock                        │
│  us.anthropic.claude-sonnet-4-6     │
└─────────────────────────────────────┘
```

## 디렉터리 구조

```
kong-ai-gateway/
├── kong/
│   ├── Dockerfile          # Amazon Linux 2023 + Kong RPM
│   ├── kong.yaml           # DB-less 선언적 설정
│   ├── kong.conf           # Kong 기본 설정
│   ├── start.sh            # 시작 스크립트 (config string → 파일 변환)
│   └── buildspec-mirror.yml # CodeBuild 빌드 스펙
├── guardrails/
│   ├── Dockerfile          # python:3.12-slim + LLM Guard
│   ├── requirements.txt
│   ├── buildspec.yml       # CodeBuild 빌드 스펙
│   └── app/
│       └── main.py         # FastAPI 애플리케이션
├── deploy/
│   ├── ecs/
│   │   ├── task-definition.json  # ECS 태스크 정의 템플릿
│   │   └── iam-policy.json       # IAM 정책 템플릿
│   └── scripts/
│       ├── setup-aws.sh          # AWS 인프라 초기 설정
│       ├── deploy.sh             # 전체 배포 스크립트
│       ├── update-task-def.py    # Task Definition 업데이트
│       └── test-gateway.py       # 엔드포인트 검증 스크립트
├── docker-compose.yml      # 로컬 개발용
├── .env.example            # 환경 변수 샘플
└── .gitignore
```

## 주요 기술 결정 및 트러블슈팅

### Kong 배포 방식
- **문제**: Docker Hub rate limit으로 `kong:3.9` 이미지 풀 실패
- **해결**: Amazon Linux 2023(ECR Public) + Kong 공식 RPM 설치
  ```dockerfile
  FROM public.ecr.aws/amazonlinux/amazonlinux:2023
  RUN wget -O /tmp/kong-setup.sh https://packages.konghq.com/public/gateway-39/setup.rpm.sh \
      && bash /tmp/kong-setup.sh && dnf install -y kong
  ```

### Kong DB-less Config 로딩
- **문제**: `KONG_DECLARATIVE_CONFIG_STRING` 환경 변수가 Kong 3.9의 `dedicated_config_processing=true` 모드에서 silent fail
- **해결**: `start.sh`에서 환경 변수 → 파일 변환 후 `KONG_DECLARATIVE_CONFIG` 경로로 전달
  ```bash
  echo "$KONG_DECLARATIVE_CONFIG_STRING" > /kong/kong.yaml
  export KONG_DECLARATIVE_CONFIG=/kong/kong.yaml
  ```

### Guardrails 언어 설정
- **문제**: `Anonymize(language="ko")` → llm-guard 0.3.14는 `['en', 'zh']`만 지원
- **해결**: `language="en"` 으로 변경 (BERT NER 모델이 다국어 지원)

### BanTopics 빈 리스트 오류
- **문제**: `BanTopics(topics=[])` → zero-shot classification 오류
- **해결**: 환경 변수가 설정된 경우에만 스캐너 추가

### risk_score 타입 불일치
- **문제**: llm-guard 0.3.14에서 `scan_prompt()` 반환 `risk_score`가 `dict` 또는 `float`로 버전마다 다름
- **해결**: 타입 체크 후 처리
  ```python
  if isinstance(risk_score, dict):
      numeric_score = max(risk_score.values()) if risk_score else 0.0
  else:
      numeric_score = float(risk_score)
  ```

### IAM 권한
- **문제**: `bedrock:InvokeModel` 권한이 foundation-model ARN에만 있어 cross-region inference-profile 거부
- **해결**: Bedrock Resource를 `*`로 확장

### KONG_NGINX_DAEMON
- **문제**: nginx가 daemon 모드로 시작되어 ECS에서 컨테이너가 즉시 종료
- **해결**: `KONG_NGINX_DAEMON=off` 환경 변수 필수

## 빠른 시작

### 사전 요구사항
- AWS CLI 설정 (`aws configure`)
- AWS 계정에 Bedrock Claude Sonnet 4.6 모델 접근 권한
- ECR 리포지터리: `ai-guardrails`, `kong-gateway`
- ECS 클러스터: `kong-ai-gateway-cluster`

### 1. AWS 인프라 설정
```bash
# ECR, IAM Role, Security Group, CloudWatch 로그 그룹 생성
python deploy/scripts/setup-aws.py
```

### 2. 이미지 빌드 (AWS CodeBuild)
```bash
# Guardrails 이미지
cd guardrails && aws codebuild start-build --project-name ai-guardrails-build

# Kong 이미지
cd kong && aws codebuild start-build --project-name kong-mirror-build
```

### 3. ECS 배포
```bash
python deploy/scripts/update-task-def.py latest latest
```

### 4. 동작 확인
```bash
# 환경 변수 설정 (배포 후 출력되는 IP 사용)
export KONG_ENDPOINT=http://<ECS_PUBLIC_IP>:8000
export KONG_API_KEY=kong-xxxx

python deploy/scripts/test-gateway.py $KONG_ENDPOINT $KONG_API_KEY
```

## API 엔드포인트

### OpenAI 호환 (Claude Code 직접 사용)
```bash
curl -X POST http://<IP>:8000/v1/chat/completions \
  -H "apikey: <KONG_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"max_tokens":100}'
```

### Bedrock 호환 (AWS SDK / Claude Code Bedrock 모드)
```bash
# AWS_ENDPOINT_URL로 자동 라우팅 (인증 없음 - AWS SigV4 통과)
export AWS_ENDPOINT_URL=http://<IP>:8000
aws bedrock-runtime invoke-model \
  --model-id us.anthropic.claude-sonnet-4-6 \
  --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}' \
  /tmp/output.json
```

### 헬스체크
```bash
curl http://<IP>:8000/health       # Kong proxy (404 = 정상, 라우트 없음)
curl http://<IP>:8001/status       # Kong admin (내부 접근만)
curl http://<IP>:8080/health       # Guardrails (직접 접근 불가, 동일 태스크만)
```

## Claude Code 연결 설정

```bash
# AWS_ENDPOINT_URL을 Kong 게이트웨이로 변경
# Windows (PowerShell):
[System.Environment]::SetEnvironmentVariable("AWS_ENDPOINT_URL", "http://<IP>:8000", "User")

# Linux/Mac:
export AWS_ENDPOINT_URL=http://<IP>:8000
```

## 환경 변수 (Guardrails)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-6` | Bedrock 모델 ID |
| `BEDROCK_GUARDRAIL_ID` | (없음) | 추가 Bedrock 가드레일 ID |
| `BLOCK_THRESHOLD` | `0.8` | 차단 임계값 (0~1) |
| `BAN_TOPICS` | (없음) | 금지 주제 (쉼표 구분) |
| `BAN_SUBSTRINGS` | (없음) | 금지 문자열 (쉼표 구분) |
| `MAX_TOKENS_INPUT` | `4096` | 최대 입력 토큰 수 |

## 비용 (AWS us-east-1 기준)

| 서비스 | 스펙 | 시간당 비용 |
|--------|------|------------|
| ECS Fargate | 2 vCPU / 8 GB | ~$0.12/hr |
| ECR 저장소 | ~3.5 GB | ~$0.35/월 |
| CloudWatch Logs | 로그 수집 | ~$0.01/GB |
| CodeBuild | 빌드 시간 | $0.005/분 |

> **절약 팁**: 사용하지 않을 때 ECS 서비스를 0으로 스케일 다운
> ```bash
> aws ecs update-service --cluster kong-ai-gateway-cluster \
>   --service kong-ai-gateway-service --desired-count 0
> ```

## 라이선스

MIT
