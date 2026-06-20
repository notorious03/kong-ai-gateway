# Kong AI Gateway + AI Guardrails on AWS ECS Fargate

> **기업 내 Claude Code 안전 사용을 위한 AI 보안 게이트웨이**
>
> AI 보안 담당자 관점에서 설계한 엔터프라이즈 LLM 보안 인프라.  
> AWS Bedrock 기반으로 외부 인터넷 없이 Claude를 사용하면서,  
> Kong AI Gateway + 독립 Guardrails 미들웨어로 다층 보안을 구현합니다.

---

## 목차

1. [왜 이 아키텍처인가?](#왜-이-아키텍처인가)
2. [아키텍처 개요](#아키텍처-개요)
3. [AWS Bedrock 선택 이유](#aws-bedrock-선택-이유)
4. [Kong AI Gateway 선택 이유](#kong-ai-gateway-선택-이유)
5. [MCP Gateway 통합](#mcp-gateway-통합)
6. [AI Guardrails 미들웨어](#ai-guardrails-미들웨어)
7. [통합 로그 관리 및 보안 모니터링](#통합-로그-관리-및-보안-모니터링)
8. [빠른 시작](#빠른-시작)
9. [디렉터리 구조](#디렉터리-구조)
10. [트러블슈팅](#트러블슈팅)

---

## 왜 이 아키텍처인가?

기업 내에서 Claude Code를 도입할 때 AI 보안 담당자가 마주하는 핵심 과제는 다음과 같습니다.

| 과제 | 이 아키텍처의 해결 방식 |
|------|------------------------|
| 코드·데이터가 외부로 나가는 것이 불안하다 | AWS Bedrock으로 VPC 내부에서 처리 |
| 직원이 어떤 프롬프트를 넣는지 모른다 | Kong 중앙 게이트웨이에서 전수 감사 |
| Jailbreak·프롬프트 인젝션 공격을 막아야 한다 | LLM Guard 스캐너 실시간 탐지 |
| 주민번호·카드번호 등 PII가 모델로 유출될 수 있다 | Presidio Anonymize로 마스킹 후 전달 |
| 특정 부서/도구별로 접근을 제한해야 한다 | Kong key-auth + rate-limiting |
| MCP 도구 서버도 중앙에서 관리하고 싶다 | Kong AI MCP Proxy 통합 |
| 보안 사고 발생 시 로그가 파편화되어 있다 | CloudWatch 통합 + SIEM 연동 |

---

## 아키텍처 개요

```
┌──────────────────────────────────────────────────────────┐
│                    기업 내부 환경                          │
│                                                          │
│  개발자 PC / CI-CD 파이프라인                              │
│  ┌─────────────────────────────┐                         │
│  │  Claude Code                │                         │
│  │  AWS_ENDPOINT_URL=Kong IP   │                         │
│  └────────────┬────────────────┘                         │
│               │ HTTPS                                    │
└───────────────┼──────────────────────────────────────────┘
                │  (인터넷 구간 없음 - PrivateLink 또는 Public ECS)
                ▼
┌──────────────────────────────────────────────────────────┐
│              AWS Cloud (VPC)                             │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  ECS Fargate Task (2 vCPU / 8 GB)                  │  │
│  │                                                    │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │  Kong AI Gateway  (port 8000/8001)           │  │  │
│  │  │                                             │  │  │
│  │  │  Plugins: key-auth │ rate-limiting          │  │  │
│  │  │           ai-mcp-proxy │ request-transform  │  │  │
│  │  │                                             │  │  │
│  │  │  Routes:                                    │  │  │
│  │  │  POST /v1/chat/completions  (OpenAI 호환)   │  │  │
│  │  │  POST /model/{id}/invoke    (Bedrock 호환)  │  │  │
│  │  │  *    /mcp                  (MCP Proxy)     │  │  │
│  │  └──────────────────┬──────────────────────────┘  │  │
│  │                     │ localhost:8080               │  │
│  │  ┌──────────────────▼──────────────────────────┐  │  │
│  │  │  AI Guardrails  (port 8080)                  │  │  │
│  │  │  FastAPI + LLM Guard 0.3.14                  │  │  │
│  │  │                                             │  │  │
│  │  │  Input:  Anonymize │ PromptInjection        │  │  │
│  │  │          Toxicity  │ TokenLimit             │  │  │
│  │  │          BanTopics │ BanSubstrings           │  │  │
│  │  │                                             │  │  │
│  │  │  Output: Deanonymize │ Sensitive             │  │  │
│  │  └──────────────────┬──────────────────────────┘  │  │
│  └────────────────────┼──────────────────────────────┘  │
│                        │ AWS SDK (IAM Task Role)         │
│  ┌─────────────────────▼──────────────────────────────┐  │
│  │  AWS Bedrock                                        │  │
│  │  us.anthropic.claude-sonnet-4-6                     │  │
│  │  (VPC Endpoint 구성 시 완전 내부망)                  │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  CloudWatch Logs → S3 Archive → SIEM/Athena              │
└──────────────────────────────────────────────────────────┘
```

---

## AWS Bedrock 선택 이유

자세한 내용: [docs/01-why-bedrock.md](docs/01-why-bedrock.md)

### 핵심 요약

**보안/컴플라이언스 측면**
- 프롬프트와 응답이 Anthropic 서버로 가지 않음 — AWS 계정 내부에서만 처리
- AWS VPC Endpoint 구성 시 인터넷 구간 완전 차단 가능
- SOC2, ISO27001, HIPAA, PCI-DSS 등 AWS 인증 그대로 상속
- 데이터 레지던시: `us-east-1` 등 리전을 명시하면 그 외 리전으로 데이터 이동 없음

**운영 측면**
- IAM Role 기반 인증 — API 키 없이 서비스 계정으로 접근
- AWS 청구서 단일화, 사용량 태깅으로 팀·프로젝트별 비용 추적
- Claude 모델 업그레이드 시 Bedrock에서 자동 반영

---

## Kong AI Gateway 선택 이유

자세한 내용: [docs/02-why-kong.md](docs/02-why-kong.md)

### 시장 인지도

Kong은 **API 게이트웨이 시장 1위** 오픈소스 솔루션으로, Gartner API Management Magic Quadrant에 매년 선정됩니다.

- **3억 회 이상** Docker Hub 다운로드
- **전 세계 1만 개 이상** 기업 사용 (Samsung, Expedia, Honeywell 등)
- CNCF(Cloud Native Computing Foundation) 멤버 프로젝트
- GitHub Stars 38,000+

### LLM Gateway로 Kong을 선택한 이유

| 기능 | 설명 |
|------|------|
| **AI 전용 플러그인** | `ai-proxy`, `ai-prompt-guard`, `ai-mcp-proxy` 등 LLM 특화 플러그인 기본 제공 |
| **DB-less 모드** | 선언적 YAML 한 파일로 전체 설정 — GitOps/IaC 친화적 |
| **OpenAI 호환 API** | Claude Code를 포함한 모든 OpenAI SDK 클라이언트가 무수정 연동 |
| **플러그인 생태계** | 200+ 플러그인으로 인증·로깅·변환 등 즉시 확장 가능 |
| **엔터프라이즈 지원** | Kong Inc.의 상용 지원(Kong Konnect) 옵션 존재 |

---

## MCP Gateway 통합

자세한 내용: [docs/03-mcp-gateway.md](docs/03-mcp-gateway.md)

### MCP를 Kong에 통합한 이유

MCP(Model Context Protocol)는 Claude가 외부 도구(파일 시스템, DB, API 등)를 호출하는 프로토콜입니다.  
이를 Kong에 통합하면:

- **중앙 제어**: 어떤 MCP 서버에 누가 접근했는지 단일 감사 로그
- **접근 제어**: 팀별로 허용된 MCP 도구만 노출
- **보안 스캔**: MCP 요청/응답도 Guardrails 통과 옵션

### MCP 정책 설정 방법

`kong/kong.yaml`에서 MCP 관련 정책을 설정합니다.

```yaml
# MCP 라우트에 특정 도구만 허용하는 예시
plugins:
  - name: ai-mcp-proxy
    route: mcp-route
    config:
      # 허용할 MCP 서버 목록
      upstream_servers:
        - name: filesystem-server
          url: http://mcp-filesystem:3000
        - name: database-server
          url: http://mcp-database:3001
      # 허용할 도구(tool) 화이트리스트
      allowed_tools:
        - read_file
        - list_directory
        - query_readonly
      # 차단할 도구 블랙리스트
      blocked_tools:
        - write_file
        - delete_file
        - execute_command
```

---

## AI Guardrails 미들웨어

자세한 내용: [docs/04-guardrails.md](docs/04-guardrails.md)

### Bedrock 기본 가드레일 대신 독립 레이어를 선택한 이유

| 비교 항목 | Bedrock 기본 가드레일 | 이 프로젝트의 Guardrails |
|-----------|----------------------|--------------------------|
| PII 감지 | 영어 중심, 패턴 기반 | Presidio NLP + BERT NER (한국어 포함) |
| 커스텀 정책 | AWS 콘솔에서만 설정 | 코드로 관리, GitOps 가능 |
| 프롬프트 인젝션 | 제한적 | 전용 ML 모델 탐지 |
| 응답 후처리 | 기본 필터링 | 출력 PII 마스킹, 민감정보 재검사 |
| 감사 로그 | CloudTrail | 스캐너별 상세 점수 포함 |
| 비용 | 요청당 과금 추가 | 컴퓨팅 비용만 |

### 사용 오픈소스

| 라이브러리 | 역할 | GitHub Stars |
|-----------|------|-------------|
| **LLM Guard** (ProtectAI) | 스캐너 프레임워크 전체 | 4,000+ |
| **Microsoft Presidio** | PII 감지 및 익명화 | 10,000+ |
| **HuggingFace Transformers** | PromptInjection, Toxicity ML 모델 | 130,000+ |
| **spaCy** | NER 기반 텍스트 분석 | 29,000+ |
| **FastAPI** | Guardrails HTTP 서버 | 76,000+ |

### 가드레일 정책 추가 방법

`guardrails/app/main.py`의 `init_scanners()` 함수에서 스캐너를 추가합니다.  
환경 변수로도 간단히 제어할 수 있습니다.

```bash
# ECS Task Definition 또는 .env에서 설정
BAN_TOPICS=malware,hacking,drugs          # 금지 주제 (쉼표 구분)
BAN_SUBSTRINGS=system_prompt,ignore above  # 금지 문자열
BLOCK_THRESHOLD=0.7                        # 차단 임계값 낮추면 더 엄격
MAX_TOKENS_INPUT=2048                      # 입력 토큰 제한
```

---

## 통합 로그 관리 및 보안 모니터링

자세한 내용: [docs/05-logging-security.md](docs/05-logging-security.md)

### 로그 수집 구조

```
Kong Access Log  ──┐
Guardrails Log   ──┼──► CloudWatch Logs ──► S3 ──► Athena / OpenSearch
Bedrock CloudTrail─┘                              (SIEM 연동)
```

### 핵심 모니터링 시나리오

1. **프롬프트 인젝션 공격 탐지** — risk_score 급등 패턴
2. **PII 반복 유출 시도** — 동일 사용자의 익명화 빈도 이상
3. **비정상 사용량 폭증** — Rate limit 위반 연속 발생
4. **업무 외 주제 질의** — BanTopics 차단 누적
5. **모델 응답 내 민감정보 유출** — 출력 Sensitive 스캐너 트리거

---

## 빠른 시작

### 사전 요구사항

- AWS CLI 설정 (`aws configure`)
- AWS Bedrock에서 Claude Sonnet 4.6 모델 접근 권한 활성화
- ECR 리포지터리: `ai-guardrails`, `kong-gateway`
- ECS 클러스터: `kong-ai-gateway-cluster`

### 1. AWS 인프라 설정

```bash
cd deploy/scripts
python setup-aws.py   # ECR, IAM Role, Security Group, CloudWatch 로그 그룹 생성
```

### 2. 이미지 빌드 (AWS CodeBuild)

```bash
# Guardrails 이미지
aws codebuild start-build --project-name ai-guardrails-build

# Kong 이미지
aws codebuild start-build --project-name kong-mirror-build
```

### 3. ECS 배포

```bash
python deploy/scripts/update-task-def.py latest latest
```

### 4. 동작 확인

```bash
# IP 확인 후 테스트
KONG_IP=$(python -c "
import boto3, os; os.environ.pop('AWS_ENDPOINT_URL',None)
ecs=boto3.client('ecs',region_name='us-east-1')
ec2=boto3.client('ec2',region_name='us-east-1')
t=ecs.list_tasks(cluster='kong-ai-gateway-cluster',desiredStatus='RUNNING')['taskArns'][0]
task=ecs.describe_tasks(cluster='kong-ai-gateway-cluster',tasks=[t])['tasks'][0]
for att in task['attachments']:
  if att['type']=='ElasticNetworkInterface':
    eid=next(d['value'] for d in att['details'] if d['name']=='networkInterfaceId')
    print(ec2.describe_network_interfaces(NetworkInterfaceIds=[eid])['NetworkInterfaces'][0]['Association']['PublicIp'])
")

python deploy/scripts/test-gateway.py http://$KONG_IP:8000 <YOUR_API_KEY>
```

### 5. Claude Code 연결

```bash
# Windows
[System.Environment]::SetEnvironmentVariable("AWS_ENDPOINT_URL", "http://<KONG_IP>:8000", "User")

# Linux/Mac
echo 'export AWS_ENDPOINT_URL=http://<KONG_IP>:8000' >> ~/.bashrc
```

---

## 디렉터리 구조

```
kong-ai-gateway/
├── README.md
├── docs/
│   ├── 01-why-bedrock.md          # AWS Bedrock 선택 근거
│   ├── 02-why-kong.md             # Kong 선택 근거 및 시장 분석
│   ├── 03-mcp-gateway.md          # MCP Gateway 통합 가이드
│   ├── 04-guardrails.md           # Guardrails 구성 및 정책 설정
│   └── 05-logging-security.md     # 통합 로깅 및 보안 모니터링
├── kong/
│   ├── Dockerfile                 # Amazon Linux 2023 + Kong RPM
│   ├── kong.yaml                  # DB-less 선언적 설정
│   ├── kong.conf                  # Kong 기본 설정
│   ├── start.sh                   # 시작 스크립트
│   └── buildspec-mirror.yml       # CodeBuild 스펙
├── guardrails/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── buildspec.yml
│   └── app/
│       └── main.py                # FastAPI + LLM Guard
├── deploy/
│   ├── ecs/
│   │   ├── task-definition.json   # ECS 태스크 정의 템플릿
│   │   └── iam-policy.json        # IAM 정책 템플릿
│   └── scripts/
│       ├── setup-aws.sh
│       ├── deploy.sh
│       ├── update-task-def.py
│       └── test-gateway.py
├── docker-compose.yml             # 로컬 개발용
└── .env.example
```

---

## 트러블슈팅

주요 이슈 및 해결 방법은 각 문서를 참고하세요.

| 이슈 | 원인 | 해결 |
|------|------|------|
| Kong 컨테이너 즉시 종료 | `KONG_NGINX_DAEMON` 기본값 `on` | `KONG_NGINX_DAEMON=off` 환경 변수 필수 |
| Kong 라우트 0개 | `dedicated_config_processing=true` silent fail | `start.sh`로 config string → 파일 변환 |
| Docker Hub rate limit | 무료 계정 pull 제한 | ECR Public 이미지 사용 |
| Guardrails `language="ko"` 오류 | llm-guard 0.3.14는 `en`, `zh`만 지원 | `language="en"` 변경 (BERT는 다국어 지원) |
| Bedrock AccessDeniedException | inference-profile ARN 미포함 | IAM 정책 Resource를 `*`로 확장 |

---

## 비용 가이드 (AWS us-east-1)

| 서비스 | 스펙 | 비용 |
|--------|------|------|
| ECS Fargate | 2 vCPU / 8 GB | ~$0.12/시간 (~$86/월 상시 운영) |
| ECR 저장소 | ~3.5 GB | ~$0.35/월 |
| CloudWatch Logs | 수집 + 저장 | ~$0.50/GB |
| CodeBuild | 빌드 | $0.005/분 |
| Bedrock | Claude Sonnet 4.6 | 입력 $3/1M tokens, 출력 $15/1M tokens |

> **절약**: 업무 시간에만 운영 시 `desired-count=0` 으로 야간 중지
> ```bash
> # 중지
> aws ecs update-service --cluster kong-ai-gateway-cluster \
>   --service kong-ai-gateway-service --desired-count 0
> # 재시작
> aws ecs update-service --cluster kong-ai-gateway-cluster \
>   --service kong-ai-gateway-service --desired-count 1
> ```

---

## 라이선스

MIT — 자유롭게 사용하되, 프로덕션 배포 전 보안 검토를 권장합니다.
