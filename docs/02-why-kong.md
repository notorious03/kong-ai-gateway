# Kong AI Gateway를 선택한 이유

## Kong이란?

Kong은 2015년 오픈소스로 공개된 이후 **API 게이트웨이 시장에서 가장 널리 사용되는 솔루션**입니다.  
단순한 API 프록시를 넘어, 오늘날에는 LLM 전용 AI Gateway 기능까지 포함한  
엔터프라이즈 플랫폼으로 진화했습니다.

---

## 시장 인지도 및 검증

### 수치로 보는 Kong의 위상

| 지표 | 수치 (2024 기준) |
|------|-----------------|
| Docker Hub 다운로드 | **3억 회 이상** |
| 사용 기업 수 | **전 세계 1만 개 이상** |
| GitHub Stars | 38,000+ (kong/kong) |
| 국내 도입 사례 | 삼성, 카카오, 네이버 계열사 등 |

### 업계 분석 기관의 평가

- **Gartner API Management Magic Quadrant** — 매년 "Leader" 또는 "Visionary" 구간에 지속 선정
- **Forrester Wave API Management** — 상위권 지속 유지
- **G2 API Management Category** — 리더 배지 수상
- **CNCF(Cloud Native Computing Foundation)** 멤버 프로젝트

### 글로벌 레퍼런스 고객

- **Samsung** — 글로벌 API 관리
- **Expedia** — 트래블 서비스 API 레이어
- **Honeywell** — 산업 IoT API 게이트웨이
- **NBCUniversal** — 미디어 스트리밍 API
- **Nasdaq** — 금융 데이터 API

---

## LLM Gateway로 Kong을 선택한 이유

### 1. AI 전용 플러그인 기본 제공

Kong 3.x부터 LLM 워크로드를 위한 전용 플러그인이 추가되었습니다.

| 플러그인 | 기능 |
|---------|------|
| `ai-proxy` | OpenAI/Claude/Gemini 등 멀티 모델 라우팅 |
| `ai-prompt-guard` | 프롬프트 패턴 기반 필터링 |
| `ai-prompt-decorator` | 시스템 프롬프트 자동 추가 |
| `ai-request-transformer` | 요청 포맷 변환 |
| `ai-response-transformer` | 응답 포맷 변환 |
| `ai-mcp-proxy` | MCP 서버 프록시 및 도구 제어 |
| `ai-semantic-cache` | 의미론적 캐싱으로 비용 절감 |
| `ai-rate-limiting-advanced` | 토큰 단위 rate limiting |

### 2. OpenAI 호환 API — Claude Code 무수정 연결

가장 중요한 이유 중 하나입니다.

Claude Code는 내부적으로 `AWS SDK`(Bedrock)와 `OpenAI SDK` 형식 양쪽을 지원합니다.  
Kong이 `/v1/chat/completions` 엔드포인트를 제공하면  
**Claude Code에서 `AWS_ENDPOINT_URL`만 변경하면 되며, 코드 수정 불필요**합니다.

```python
# Claude Code가 보내는 요청 (OpenAI 형식)
POST /v1/chat/completions
{
  "model": "claude-sonnet-4-6",
  "messages": [{"role": "user", "content": "..."}],
  "max_tokens": 4096
}
```

Kong이 이를 수신 → Guardrails → Bedrock으로 라우팅합니다.

### 3. DB-less 선언적 설정 — GitOps 친화적

Kong의 DB-less 모드는 전체 설정을 단일 YAML 파일로 관리합니다.

```yaml
# kong/kong.yaml 한 파일로 전체 정책 관리
_format_version: "3.0"

services:
  - name: llm-guardrails-service
    url: http://localhost:8080
    routes:
      - name: openai-compat-route
        paths: [/v1/chat/completions]
    plugins:
      - name: key-auth
      - name: rate-limiting
        config:
          minute: 60
```

**GitOps 워크플로우**:
```
개발자가 kong.yaml 수정 → PR → 코드 리뷰 → 머지
→ CodeBuild 자동 빌드 → ECR 푸시 → ECS 롤링 업데이트
```

데이터베이스 없이 컨테이너만으로 운영되므로 ECS Fargate에 최적화됩니다.

### 4. 플러그인 생태계 — 200개 이상

```
인증·인가: key-auth, jwt, oauth2, ldap-auth, openid-connect
보안:       bot-detection, ip-restriction, acl, cors
트래픽:     rate-limiting, response-ratelimiting, request-size-limiting
변환:       request-transformer, response-transformer, correlation-id
관찰성:     logging, prometheus, datadog, opentelemetry, zipkin
AI 특화:    ai-proxy, ai-prompt-guard, ai-mcp-proxy ...
```

새로운 요구사항이 생겨도 플러그인 하나 추가로 해결됩니다.

### 5. 멀티 모델·멀티 팀 라우팅

팀별로 다른 모델과 정책을 적용할 수 있습니다.

```yaml
# 예시: 팀별 차별화 라우팅
services:
  - name: engineering-llm
    routes:
      - paths: [/v1/engineering/chat]
    plugins:
      - name: key-auth
        config: {key_names: [X-Eng-Key]}
      - name: rate-limiting
        config: {minute: 120}  # 엔지니어링: 분당 120회

  - name: hr-llm
    routes:
      - paths: [/v1/hr/chat]
    plugins:
      - name: key-auth
        config: {key_names: [X-HR-Key]}
      - name: rate-limiting
        config: {minute: 20}  # HR: 분당 20회
      - name: ai-prompt-guard
        config:
          deny_patterns: ["employee.*salary", "personal.*data"]
```

### 6. 엔터프라이즈 지원 옵션

OSS 버전으로 시작하고, 필요 시 상용 지원으로 업그레이드 가능합니다.

| 버전 | 특징 |
|------|------|
| **Kong OSS** | 무료, 커뮤니티 지원, 이 프로젝트에서 사용 |
| **Kong Konnect** | 클라우드 관리형 콘솔, SLA, 전용 지원 |
| **Kong Enterprise** | Self-hosted, 추가 플러그인, RBAC |

---

## Kong vs 대안 솔루션 비교

| 항목 | Kong OSS | AWS API Gateway | NGINX | Traefik |
|------|---------|----------------|-------|---------|
| LLM 전용 플러그인 | ✅ 네이티브 | ❌ 없음 | ❌ 없음 | ❌ 없음 |
| MCP 프록시 | ✅ ai-mcp-proxy | ❌ | ❌ | ❌ |
| OpenAI 호환 API | ✅ | ❌ 별도 구현 | ❌ 별도 구현 | ❌ |
| DB-less 모드 | ✅ | N/A | ✅ | ✅ |
| 플러그인 수 | 200+ | 제한적 | 제한적 | 50+ |
| 벤더 종속 | ❌ 없음 | ✅ AWS 종속 | ❌ 없음 | ❌없음 |
| 엔터프라이즈 지원 | 유료 옵션 | AWS 지원 | NGINX Plus | 상용 버전 |
| 시장 인지도 | 매우 높음 | 높음 | 높음 | 중간 |

---

## 이 프로젝트에서의 Kong 역할

```
클라이언트 요청 수신
    │
    ├─ key-auth: API 키 검증 (OpenAI 경로)
    │
    ├─ rate-limiting: 분당 60회 / 시간당 1000회 제한
    │
    ├─ request-transformer: X-Kong-Gateway 헤더 추가
    │
    └─ 라우팅:
        ├─ /v1/chat/completions → Guardrails (OpenAI 형식)
        ├─ /model/{id}/invoke   → Guardrails (Bedrock 형식)
        └─ /mcp                 → MCP 패스스루
```

Kong은 이 아키텍처에서 **첫 번째 보안 문으로 동작**합니다.  
인증되지 않은 요청, 과도한 트래픽, 허용되지 않은 경로를 Guardrails 도달 전에 차단합니다.

---

## 결론

Kong을 선택한 이유를 한 문장으로 요약하면:

> **"검증된 시장 1위 API 게이트웨이가 AI 시대를 위한 LLM 전용 기능을 탑재했고,  
> OpenAI 호환 API 덕분에 Claude Code가 무수정으로 연결되며,  
> DB-less 선언적 설정으로 GitOps 기반 보안 정책 관리가 가능하다."**
