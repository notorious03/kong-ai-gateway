# MCP Gateway 통합 가이드

## MCP(Model Context Protocol)란?

MCP는 Anthropic이 2024년 공개한 개방형 표준으로,  
AI 모델이 외부 도구·데이터 소스와 표준화된 방식으로 통신하는 프로토콜입니다.

```
[기존 방식]                    [MCP 방식]
Claude ←→ 커스텀 연동 코드     Claude ←→ MCP 클라이언트
       ←→ 별도 DB 연결 코드            ←→ MCP 서버 (파일시스템)
       ←→ API 직접 호출 코드           ←→ MCP 서버 (데이터베이스)
                                       ←→ MCP 서버 (외부 API)
```

Claude Code는 MCP 서버를 통해 파일 읽기, 코드 실행, 데이터베이스 조회 등을 수행합니다.

---

## MCP를 Kong에 통합한 이유

### 문제: MCP 서버가 분산되면 보안 사각지대 발생

기업 내 Claude Code 사용자가 늘어나면 각자 MCP 서버를 설정하는 상황이 생깁니다.

```
[통제 없는 MCP 환경]
개발자 A ──► 로컬 MCP 서버 A (파일시스템)
개발자 B ──► 로컬 MCP 서버 B (내부 DB 직접 연결)
개발자 C ──► 외부 MCP 서버   (인터넷의 3rd party)
```

이 경우:
- 어떤 도구가 어떤 데이터에 접근했는지 **감사 불가**
- 팀별 접근 권한 통제 **불가**
- 악성 MCP 서버 연결 **탐지 불가**

### 해결: Kong을 MCP 게이트웨이로 사용

```
[Kong MCP Gateway 환경]
개발자 A ──►
개발자 B ──► Kong MCP Proxy ──► 승인된 MCP 서버들만
개발자 C ──►                    (내부망에서만 접근 가능)
              │
              └─ 모든 요청/응답 로깅
                 도구별 접근 제어
                 rate limiting
```

---

## Kong ai-mcp-proxy 플러그인

Kong 3.9부터 `ai-mcp-proxy` 플러그인이 기본 제공됩니다.

### 현재 프로젝트 설정 (`kong/kong.yaml`)

```yaml
services:
  - name: mcp-proxy-service
    url: http://localhost:8080/mcp-passthrough
    routes:
      - name: mcp-route
        paths:
          - /mcp
        methods:
          - GET
          - POST
        strip_path: false
```

현재는 Guardrails 서비스의 `/mcp-passthrough` 엔드포인트로 전달합니다.  
실제 MCP 서버를 추가할 때 아래 정책을 적용합니다.

---

## MCP 정책 설정 방법

### 1. 기본 MCP 서버 등록

`kong/kong.yaml`에 MCP 서버를 서비스로 등록합니다.

```yaml
services:
  # 파일시스템 MCP 서버
  - name: mcp-filesystem
    url: http://mcp-filesystem-server:3000
    routes:
      - name: mcp-filesystem-route
        paths: [/mcp/filesystem]
        methods: [GET, POST]
    plugins:
      - name: key-auth
        config: {key_names: [X-MCP-Key]}

  # 데이터베이스 MCP 서버 (읽기 전용)
  - name: mcp-database-readonly
    url: http://mcp-db-server:3001
    routes:
      - name: mcp-db-route
        paths: [/mcp/database]
        methods: [POST]
    plugins:
      - name: key-auth
        config: {key_names: [X-MCP-Key]}
      - name: rate-limiting
        config:
          minute: 30  # DB 조회 더 엄격하게 제한
```

### 2. 도구 화이트리스트/블랙리스트 설정

`ai-mcp-proxy` 플러그인으로 허용/차단 도구를 세밀하게 제어합니다.

```yaml
plugins:
  - name: ai-mcp-proxy
    service: mcp-filesystem
    config:
      # 허용 도구 목록 (화이트리스트 방식 - 더 안전)
      allowed_tools:
        - read_file
        - list_directory
        - search_files
      # 또는 차단 도구 목록 (블랙리스트 방식)
      blocked_tools:
        - write_file
        - delete_file
        - move_file
        - execute_command
      # 접근 가능한 경로 제한
      allowed_paths:
        - /workspace/projects
        - /workspace/docs
      blocked_paths:
        - /etc
        - /home
        - /var/secrets
```

### 3. 팀별 접근 제어

Consumer 그룹으로 팀별로 다른 MCP 서버에 접근할 수 있습니다.

```yaml
consumers:
  # 엔지니어링 팀 - 파일시스템 + DB 접근 허용
  - username: engineering-team
    keyauth_credentials:
      - key: ENG_MCP_KEY_PLACEHOLDER
    tags: [engineering]

  # HR 팀 - 파일시스템만 접근 (DB 접근 불가)
  - username: hr-team
    keyauth_credentials:
      - key: HR_MCP_KEY_PLACEHOLDER
    tags: [hr]

# ACL로 팀별 접근 제어
plugins:
  - name: acl
    service: mcp-database-readonly
    config:
      allow:
        - engineering  # 엔지니어링만 DB 접근 허용
      hide_groups_header: true
```

### 4. MCP 요청 로깅 설정

MCP 도구 호출 내역을 CloudWatch로 전송합니다.

```yaml
plugins:
  - name: file-log
    service: mcp-filesystem
    config:
      path: /dev/stdout  # ECS에서 CloudWatch로 자동 수집
      reopen: true

  # 또는 HTTP 로그 전송
  - name: http-log
    service: mcp-filesystem
    config:
      http_endpoint: https://logs.company.internal/mcp
      method: POST
      content_type: application/json
      headers:
        Authorization: Bearer MCP_LOG_TOKEN
```

### 5. MCP 요청 크기 및 속도 제한

```yaml
plugins:
  # 전체 MCP 요청 크기 제한
  - name: request-size-limiting
    service: mcp-filesystem
    config:
      allowed_payload_size: 10  # 10 MB 초과 차단

  # MCP 도구 호출 rate limiting
  - name: rate-limiting
    service: mcp-filesystem
    config:
      minute: 20
      hour: 200
      policy: local
      fault_tolerant: true
      limit_by: consumer  # 사용자별 제한
```

---

## MCP 보안 정책 적용 예시

### 시나리오: 코드 리뷰용 MCP 서버

개발자가 코드 리뷰를 Claude Code에 요청할 때,  
특정 리포지터리의 파일만 읽을 수 있도록 제한합니다.

```yaml
services:
  - name: mcp-code-review
    url: http://mcp-git-server:4000
    routes:
      - name: mcp-code-review-route
        paths: [/mcp/code-review]
    plugins:
      - name: key-auth
        config: {key_names: [X-Review-Key]}

      - name: ai-mcp-proxy
        config:
          allowed_tools:
            - read_file
            - get_diff
            - list_commits
          blocked_tools:
            - push_commit
            - merge_branch
            - delete_branch
          allowed_repos:
            - "github.com/company/product-*"  # 회사 리포만 허용
          blocked_repos:
            - "github.com/*/secrets"
            - "*.internal/finance*"

      - name: request-transformer
        config:
          add:
            headers:
              - "X-Audit-User: $(consumer.username)"  # 감사를 위한 사용자 정보 주입
```

---

## MCP 서버 추가 절차

새로운 MCP 서버를 추가할 때 거쳐야 할 절차입니다.

```
1. 보안 심사
   - MCP 서버가 접근하는 데이터/시스템 목록 작성
   - 접근 권한 최소화 원칙 검토
   - 내부망 통신 여부 확인

2. kong.yaml 업데이트
   - 새 서비스/라우트 추가
   - ai-mcp-proxy 플러그인으로 도구 화이트리스트 설정
   - 접근 가능 사용자/팀 ACL 설정

3. PR 리뷰 → 머지
   - 보안 담당자 필수 리뷰

4. CI/CD 자동 배포
   CodeBuild → ECR → ECS 롤링 업데이트

5. 사후 모니터링
   - CloudWatch 로그에서 MCP 도구 호출 패턴 확인
   - 이상 접근 알람 설정
```

---

## MCP 관련 CloudWatch 쿼리

MCP 도구 호출 패턴을 분석하는 CloudWatch Insights 쿼리입니다.

```sql
-- MCP 도구별 호출 횟수
fields @timestamp, @message
| filter @message like /mcp-route/
| parse @message '"tool":"*"' as tool_name
| stats count(*) by tool_name
| sort count(*) desc

-- 특정 사용자의 MCP 접근 이력
fields @timestamp, @message
| filter @message like /mcp/ and @message like /username/
| parse @message '"username":"*"' as username
| filter username = "target-user"
| sort @timestamp desc
| limit 100
```

---

## 결론

MCP를 Kong에 통합하면:

1. **중앙 감사**: 모든 MCP 도구 호출이 Kong 로그에 기록됨
2. **세밀한 접근 제어**: 팀/사용자별 허용 도구와 경로를 코드로 관리
3. **보안 정책 일관성**: LLM 요청과 MCP 요청이 동일한 보안 게이트웨이를 통과
4. **GitOps 관리**: MCP 서버 추가/변경이 kong.yaml PR로 추적됨
