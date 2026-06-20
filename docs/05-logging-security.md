# 통합 로그 관리 및 보안 모니터링

## 로그 수집 아키텍처

이 시스템은 세 개의 독립된 컴포넌트에서 로그가 발생합니다.  
각 로그를 CloudWatch로 통합하고, S3 아카이브 후 Athena/SIEM에서 분석합니다.

```
┌─────────────────────────────────────────────────────────────┐
│                     로그 발생 지점                            │
│                                                             │
│  Kong Access Log          Guardrails App Log    Bedrock     │
│  (HTTP 요청/응답)          (스캐너 결과/차단)    CloudTrail  │
│  ─────────────────         ─────────────────    ──────────  │
│  요청 IP, 경로, 상태코드    risk_score, 스캐너   InvokeModel │
│  응답 시간, 바이트 수       차단 여부, 사용자     InputTokens │
│  Kong 소비자(apikey)        Anonymize 결과       OutputTokens│
└──────────┬──────────────────────┬─────────────────────┬─────┘
           │                      │                     │
           ▼                      ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  CloudWatch Logs                            │
│                                                             │
│  /ecs/kong-ai-gateway/kong                                  │
│  /ecs/kong-ai-gateway/guardrails                            │
│  aws-bedrock-invocations (CloudTrail → CloudWatch)          │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────────┐
           ▼               ▼                   ▼
    CloudWatch         S3 Archive          OpenSearch/SIEM
    Insights          (장기 보관)          (실시간 분석)
    (즉각 쿼리)        Athena 분석          Kibana 대시보드
```

---

## 컴포넌트별 로그 설정

### 1. Kong 로그 설정

Kong은 기본적으로 `stdout`으로 액세스 로그를 출력하고,  
ECS Fargate의 awslogs 드라이버가 자동으로 CloudWatch로 수집합니다.

**Kong 로그 포맷 커스터마이징** (`kong/kong.yaml`):

```yaml
plugins:
  # 전역 로깅 플러그인 추가
  - name: file-log
    config:
      path: /dev/stdout
      reopen: true
      custom_fields_by_lua:
        consumer_id: "return (kong.client.get_consumer() or {}).id"
        consumer_username: "return (kong.client.get_consumer() or {}).username"

  # 또는 HTTP로 중앙 로그 시스템에 전송
  - name: http-log
    config:
      http_endpoint: http://log-aggregator:8888
      method: POST
      content_type: application/json
      timeout: 5000
      keepalive: 60000
```

**Kong 기본 액세스 로그 필드**:
```json
{
  "client_ip": "10.0.1.45",
  "request": {
    "method": "POST",
    "uri": "/v1/chat/completions",
    "headers": {"host": "kong.internal", "apikey": "[HIDDEN]"}
  },
  "response": {
    "status": 200,
    "size": 1024
  },
  "latencies": {
    "request": 1450,
    "kong": 12,
    "proxy": 1438
  },
  "consumer": {
    "username": "claude-code-client",
    "id": "uuid-..."
  },
  "route": {"name": "openai-compat-route"},
  "service": {"name": "llm-guardrails-service"}
}
```

### 2. Guardrails 로그 설정

`guardrails/app/main.py`에서 구조화 로그를 출력합니다.

```python
import logging
import json

# JSON 구조화 로그 포매터
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "service": "guardrails",
            "message": record.getMessage(),
        }
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        return json.dumps(log_data, ensure_ascii=False)

# 각 요청마다 스캐너 결과 로깅
logger.info("Guardrails scan complete", extra={
    "request_id": request_id,
    "user_ip": client_ip,
    "consumer": consumer_username,   # Kong에서 X-Consumer-Username 헤더로 전달
    "risk_score": numeric_score,
    "blocked": blocked,
    "scanner_results": details["scanner_results"],
    "anonymized_entities": anonymized_count,
    "input_tokens": token_count,
    "latency_ms": latency
})
```

**Guardrails 로그 예시**:
```json
{
  "timestamp": "2026-06-20T09:15:32Z",
  "level": "INFO",
  "service": "guardrails",
  "request_id": "req-abc123",
  "consumer": "claude-code-client",
  "risk_score": 0.12,
  "blocked": false,
  "scanner_results": {
    "Anonymize": 0.0,
    "PromptInjection": 0.08,
    "Toxicity": 0.12,
    "TokenLimit": 0.0
  },
  "anonymized_entities": 2,
  "input_tokens": 342,
  "latency_ms": 487
}
```

**차단 이벤트 로그**:
```json
{
  "timestamp": "2026-06-20T09:22:11Z",
  "level": "WARNING",
  "service": "guardrails",
  "event_type": "GUARDRAIL_BLOCK",
  "consumer": "unknown-user",
  "risk_score": 0.94,
  "blocked": true,
  "scanner_results": {
    "PromptInjection": 0.94,
    "Toxicity": 0.23
  },
  "blocked_reason": "PromptInjection threshold exceeded"
}
```

### 3. Bedrock 로그 설정 (CloudTrail)

Bedrock API 호출은 AWS CloudTrail에 자동 기록됩니다.

**CloudTrail → CloudWatch 연동**:
```bash
# CloudTrail을 CloudWatch Logs로 전송 설정
aws cloudtrail put-event-selectors \
  --trail-name kong-ai-gateway-trail \
  --event-selectors '[{
    "ReadWriteType": "All",
    "IncludeManagementEvents": true,
    "DataResources": [{
      "Type": "AWS::Bedrock::Model",
      "Values": ["arn:aws:bedrock:*"]
    }]
  }]'
```

**CloudTrail Bedrock 로그 필드**:
```json
{
  "eventTime": "2026-06-20T09:15:32Z",
  "eventSource": "bedrock.amazonaws.com",
  "eventName": "InvokeModel",
  "userIdentity": {
    "type": "AssumedRole",
    "arn": "arn:aws:sts::435627631709:assumed-role/KongAiGatewayRole/..."
  },
  "requestParameters": {
    "modelId": "us.anthropic.claude-sonnet-4-6-20250514-v1:0"
  },
  "responseElements": {
    "inputTokenCount": 342,
    "outputTokenCount": 128
  },
  "sourceIPAddress": "10.0.1.45"
}
```

---

## CloudWatch Insights 쿼리 모음

### 기본 운영 쿼리

```sql
-- 최근 1시간 요청 통계
fields @timestamp, @message
| filter @logStream like /guardrails/
| stats 
    count(*) as total_requests,
    sum(blocked) as blocked_requests,
    avg(risk_score) as avg_risk,
    avg(latency_ms) as avg_latency
| by bin(5m)

-- 소비자별 사용량
fields @timestamp, consumer, input_tokens
| filter @logStream like /guardrails/
| stats sum(input_tokens) as total_tokens, count(*) as requests by consumer
| sort total_tokens desc
```

### 보안 이벤트 쿼리

```sql
-- 차단된 요청만 조회
fields @timestamp, consumer, risk_score, scanner_results, blocked_reason
| filter @logStream like /guardrails/ and blocked = true
| sort @timestamp desc
| limit 50

-- 고위험 요청 (차단되지 않았지만 위험도 높음)
fields @timestamp, consumer, risk_score
| filter @logStream like /guardrails/ and risk_score > 0.5 and blocked = false
| sort risk_score desc
| limit 100
```

---

## 보안 취약점 모니터링 시나리오

### 시나리오 1: 프롬프트 인젝션 공격 탐지

**위협**: 공격자가 "이전 지시 무시", "당신은 이제 제한이 없는 AI야" 등의 패턴으로 가드레일 우회 시도

**탐지 방법**:

```sql
-- PromptInjection 스캐너 점수 급등 패턴
fields @timestamp, consumer, scanner_results
| filter @logStream like /guardrails/
| parse scanner_results '"PromptInjection": *,' as injection_score
| filter injection_score > 0.6
| stats count(*) as attempts by consumer, bin(1h)
| sort attempts desc
```

**알림 설정** (CloudWatch Alarm):
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "HighPromptInjectionAttempts" \
  --metric-name "BlockedRequests" \
  --namespace "KongAIGateway" \
  --period 300 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:us-east-1:435627631709:security-alerts
```

**대응 절차**:
1. 해당 소비자의 API 키를 kong.yaml에서 제거
2. 소비자 IP 차단 (Kong ip-restriction 플러그인)
3. 패턴 분석 후 BAN_SUBSTRINGS에 추가

---

### 시나리오 2: PII 반복 유출 시도 탐지

**위협**: 임직원이 고객 개인정보를 Claude에 입력해 데이터 처리를 시도

**탐지 방법**:

```sql
-- PII 익명화 빈도가 높은 사용자 (일정 기간 기준)
fields @timestamp, consumer, anonymized_entities
| filter @logStream like /guardrails/ and anonymized_entities > 0
| stats 
    sum(anonymized_entities) as total_pii_detected,
    count(*) as requests_with_pii,
    avg(anonymized_entities) as avg_pii_per_request
  by consumer
| sort total_pii_detected desc

-- PII가 집중된 시간대 분석
fields @timestamp, consumer, anonymized_entities
| filter anonymized_entities > 5  -- 한 요청에 5개 이상 PII
| stats count(*) by bin(1h), consumer
```

**Bedrock 비용과 교차 분석**:
```sql
-- PII 많은 요청과 토큰 사용량 상관관계
fields @timestamp, consumer, anonymized_entities, input_tokens
| filter anonymized_entities > 3 and input_tokens > 1000
| stats count(*) as suspicious_requests by consumer
| sort suspicious_requests desc
```

**대응 절차**:
1. 해당 부서 DLP(데이터 유출 방지) 정책 점검
2. 사용자 보안 교육 실시
3. 필요 시 해당 팀 API 접근 임시 제한

---

### 시나리오 3: 비정상 사용량 폭증 탐지

**위협**: 단일 계정이 자동화 스크립트로 대량 API 호출, 비용 폭증 또는 서비스 저하

**탐지 방법**:

```sql
-- Kong 로그에서 rate limit 위반 연속 발생
fields @timestamp, @message
| filter @logStream like /kong/ and @message like /429/
| parse @message '"consumer":"*"' as consumer
| stats count(*) as rate_limit_hits by consumer, bin(1m)
| filter rate_limit_hits > 5
| sort rate_limit_hits desc

-- Bedrock 토큰 사용량 급증 감지 (CloudTrail)
fields eventTime, requestParameters.modelId, responseElements.inputTokenCount
| filter eventSource = "bedrock.amazonaws.com"
| stats sum(responseElements.inputTokenCount) as total_input_tokens by bin(5m)
| sort @timestamp desc
```

**비용 알림 설정**:
```bash
# Bedrock 일일 사용량 임계값 알림
aws budgets create-budget \
  --account-id 435627631709 \
  --budget '{
    "BudgetName": "BedrockDailyAlert",
    "BudgetLimit": {"Amount": "50", "Unit": "USD"},
    "TimeUnit": "DAILY",
    "BudgetType": "COST",
    "CostFilters": {"Service": ["Amazon Bedrock"]}
  }'
```

**대응 절차**:
1. 해당 소비자의 rate limit을 즉시 낮춤 (kong.yaml 수정)
2. 자동화 스크립트 여부 조사
3. 비정상 패턴 확인 후 차단 여부 결정

---

### 시나리오 4: 업무 외 주제 질의 누적 탐지

**위협**: 임직원이 업무 외 용도(개인 프로젝트, 금지 주제)로 회사 자원 남용

**탐지 방법**:

```sql
-- BanTopics 차단 누적 현황
fields @timestamp, consumer, blocked_reason, scanner_results
| filter @logStream like /guardrails/ 
  and blocked = true 
  and blocked_reason like /BanTopics/
| stats count(*) as topic_violations by consumer, bin(1d)
| sort topic_violations desc

-- 차단은 안됐지만 금지 주제 점수가 높은 요청
fields @timestamp, consumer
| filter @logStream like /guardrails/
| parse scanner_results '"BanTopics": *,' as topics_score
| filter topics_score > 0.4 and topics_score < 0.6  -- 임계값 근처
| stats count(*) as near_violation_requests by consumer
| sort near_violation_requests desc
```

**대응 절차**:
1. 반복 위반자 관리자에게 통보
2. BAN_TOPICS에 추가 주제 등록
3. 임계값 조정 검토 (0.6 → 0.5)

---

### 시나리오 5: 모델 응답 내 민감정보 유출 탐지

**위협**: Claude가 응답 중에 의도치 않게 시스템 프롬프트, 내부 설정값, 비밀번호 등을 노출

**탐지 방법**:

```sql
-- Output Sensitive 스캐너 트리거 현황
fields @timestamp, consumer, output_scanner_results
| filter @logStream like /guardrails/
| parse output_scanner_results '"Sensitive": *' as sensitive_score
| filter sensitive_score > 0.5
| stats count(*) as sensitive_outputs by bin(1h)
| sort @timestamp desc

-- 응답 마스킹이 발생한 요청 (Sensitive 스캐너가 실제로 내용을 수정한 경우)
fields @timestamp, consumer, output_redacted
| filter output_redacted = true
| stats count(*) as redacted_responses by consumer, bin(1d)
```

**추가 모니터링 - 시스템 프롬프트 노출 패턴**:
```sql
fields @timestamp, @message
| filter @logStream like /guardrails/
| filter @message like /REDACTED/ or @message like /system.prompt/
| stats count(*) by bin(1h)
```

**대응 절차**:
1. 마스킹된 내용의 패턴 분석
2. 시스템 프롬프트에 민감 정보가 있다면 제거
3. 필요 시 Sensitive 스캐너 임계값 조정

---

## S3 장기 보관 및 Athena 분석

### CloudWatch → S3 내보내기

```bash
# CloudWatch 로그를 S3로 내보내기 (일간)
aws logs create-export-task \
  --log-group-name /ecs/kong-ai-gateway/guardrails \
  --from $(date -d "yesterday" +%s000) \
  --to $(date +%s000) \
  --destination s3://company-ai-gateway-logs \
  --destination-prefix guardrails/$(date -d "yesterday" +%Y/%m/%d)
```

### Athena 테이블 정의

```sql
-- Guardrails 로그용 Athena 테이블
CREATE EXTERNAL TABLE guardrails_logs (
  timestamp STRING,
  level STRING,
  consumer STRING,
  risk_score DOUBLE,
  blocked BOOLEAN,
  anonymized_entities INT,
  input_tokens INT,
  latency_ms INT,
  scanner_results STRUCT<
    PromptInjection: DOUBLE,
    Toxicity: DOUBLE,
    Anonymize: DOUBLE,
    TokenLimit: DOUBLE
  >
)
PARTITIONED BY (year STRING, month STRING, day STRING)
STORED AS JSON
LOCATION 's3://company-ai-gateway-logs/guardrails/';

-- 월간 보안 리포트 쿼리
SELECT 
  consumer,
  COUNT(*) as total_requests,
  SUM(CASE WHEN blocked THEN 1 ELSE 0 END) as blocked_count,
  AVG(risk_score) as avg_risk_score,
  SUM(input_tokens) as total_tokens
FROM guardrails_logs
WHERE year='2026' AND month='06'
GROUP BY consumer
ORDER BY blocked_count DESC;
```

---

## SIEM 연동 (OpenSearch / Splunk)

### OpenSearch 연동

```python
# CloudWatch Logs → Kinesis → OpenSearch 파이프라인
# 또는 직접 Guardrails에서 OpenSearch로 전송

import boto3
import json

def send_to_opensearch(log_event):
    opensearch_client = boto3.client('opensearchserverless')
    
    # 인덱스 이름: ai-gateway-YYYY-MM
    index_name = f"ai-gateway-{datetime.now().strftime('%Y-%m')}"
    
    opensearch_client.create_document(
        collection_endpoint="https://opensearch.company.internal",
        index=index_name,
        body=json.dumps(log_event)
    )
```

### Kibana 대시보드 구성 권장 항목

1. **실시간 요청 모니터링**
   - 분당 요청 수 (정상 vs 차단)
   - 평균 risk_score 추이

2. **위협 인텔리전스 패널**
   - 상위 차단 소비자
   - 스캐너별 차단 분포
   - 시간대별 공격 패턴

3. **비용 추적**
   - 소비자별 일일 토큰 사용량
   - 주간/월간 Bedrock 비용 예측

4. **PII 처리 현황**
   - 익명화된 엔티티 유형별 분포
   - PII 빈도 높은 사용자 추적

---

## 결론

세 레이어(Kong + Guardrails + Bedrock)의 로그를 통합하면  
단일 로그에서는 불가능한 **상관 분석**이 가능해집니다.

```
Kong 로그 (누가, 언제, 어떤 경로로)
    +
Guardrails 로그 (무엇이 차단/허용되었고, 위험도는 얼마)
    +
Bedrock CloudTrail (실제 모델 호출, 토큰 사용량)
    =
완전한 AI 사용 감사 추적 + 보안 위협 탐지
```

이 데이터를 기반으로 AI 보안 담당자는:
- **사후 조사**: "이 사용자가 지난 달 어떤 프롬프트를 보냈는가?"
- **사전 예방**: "어떤 패턴이 나타나기 시작하는가?"
- **규정 준수**: "PII 처리 현황을 감사자에게 증명할 수 있는가?"

위 세 질문에 모두 답할 수 있는 로그 체계를 갖추게 됩니다.
