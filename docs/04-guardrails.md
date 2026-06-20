# AI Guardrails 미들웨어

## Bedrock 기본 가드레일이 있는데 왜 별도 미들웨어를?

AWS Bedrock은 자체 Guardrails 기능을 제공합니다.  
그런데 이 프로젝트에서는 **별도의 FastAPI 기반 Guardrails 미들웨어 계층**을 추가했습니다.  
그 이유를 먼저 이해하는 것이 중요합니다.

---

## Bedrock 기본 가드레일 vs 독립 미들웨어 비교

| 비교 항목 | Bedrock 기본 Guardrails | 이 프로젝트 Guardrails |
|-----------|------------------------|----------------------|
| **PII 감지** | 영어 중심, 패턴 매칭 기반 | Presidio NLP + BERT NER (다국어 포함) |
| **프롬프트 인젝션 탐지** | 키워드 기반 제한적 탐지 | 전용 ML 모델 (94% F1 score) |
| **독성 탐지** | 기본 유해 콘텐츠 필터 | 멀티라벨 독성 분류 ML 모델 |
| **정책 관리** | AWS 콘솔 → UI 클릭 | 코드로 관리, Git 버전 추적 |
| **커스텀 확장** | 제한적 (AWS가 허용하는 범위) | 임의 스캐너 추가 가능 |
| **응답 후처리** | 없음 | 출력 PII 마스킹, 민감정보 재검사 |
| **감사 로그** | CloudTrail (요약) | 스캐너별 점수 포함 상세 로그 |
| **추가 비용** | 요청당 과금 (Guardrails 호출) | 컴퓨팅 비용만 (ECS 내부) |
| **벤더 종속** | AWS 정책 변경에 의존 | 완전 통제 가능 |
| **오프라인 동작** | 불가 (AWS 연결 필수) | ECS 내부에서 완전 동작 |

### 핵심 차이: Bedrock 가드레일은 "AWS가 만든 필터"

Bedrock 기본 가드레일은 AWS가 정의한 범주 내에서만 설정 가능합니다.  
반면 이 프로젝트의 Guardrails는 **보안 담당자가 원하는 모든 정책을 코드로 표현**할 수 있습니다.

예를 들어:
- "주민등록번호 패턴을 `***-**-*****`으로 마스킹 후 전달" → Presidio 커스텀 인식기
- "경쟁사 이름을 모델에 알리지 않기" → BanSubstrings 스캐너
- "M&A 관련 질문 차단" → BanTopics 스캐너
- "특정 사내 코드명 노출 차단" → 커스텀 스캐너 작성

---

## 사용된 오픈소스 라이브러리

### 전체 스택

```
FastAPI (웹 서버)
    │
    └─ LLM Guard 0.3.14 (ProtectAI) ← 스캐너 프레임워크
           │
           ├─ Input Scanners
           │    ├─ Anonymize ← Microsoft Presidio (PII 감지/익명화)
           │    │               └─ spaCy + BERT NER 모델
           │    ├─ PromptInjection ← HuggingFace: protectai/deberta-v3-base-prompt-injection-v2
           │    ├─ Toxicity ← HuggingFace: martin-ha/toxic-comment-model
           │    ├─ BanTopics ← HuggingFace: MoritzLaurer/deberta-v3-base-zeroshot
           │    ├─ BanSubstrings ← 단순 문자열 매칭
           │    └─ TokenLimit ← tiktoken 토큰 카운터
           │
           └─ Output Scanners
                ├─ Deanonymize ← Presidio Anonymizer 역변환
                └─ Sensitive ← HuggingFace: Isotonic/distilbert_finetuned_topic_classification
```

### 라이브러리별 상세

#### 1. LLM Guard (ProtectAI)
- **역할**: 스캐너 파이프라인 프레임워크
- **GitHub**: `protectai/llm-guard`
- **Stars**: 4,000+
- **특징**: 단일 API(`scan_prompt`, `scan_output`)로 여러 스캐너를 조합 실행

```python
from llm_guard import scan_prompt, scan_output
sanitized_text, results, risk_scores = scan_prompt(scanners, user_input)
```

#### 2. Microsoft Presidio
- **역할**: PII(개인식별정보) 감지 및 익명화
- **GitHub**: `microsoft/presidio`
- **Stars**: 10,000+
- **지원 PII 유형**: 이름, 이메일, 전화번호, 주민등록번호, 신용카드번호, IP 주소, 계좌번호 등 100+ 엔티티

```python
# Presidio가 감지하는 엔티티 예시
"홍길동의 이메일은 hong@company.com이고 전화번호는 010-1234-5678입니다"
                                                    ↓
"[PERSON]의 이메일은 [EMAIL_ADDRESS]이고 전화번호는 [PHONE_NUMBER]입니다"
```

#### 3. HuggingFace Transformers
- **역할**: ML 기반 위협 탐지 모델 로딩 및 추론
- **Stars**: 130,000+
- 프롬프트 인젝션 탐지에 `deberta-v3` 모델 사용 (DeBERTa는 BERT 대비 NLU 성능 향상)

#### 4. spaCy
- **역할**: NER(Named Entity Recognition) 파이프라인
- **Stars**: 29,000+
- Presidio의 영어 NER 파이프라인에서 사용

#### 5. FastAPI
- **역할**: Guardrails HTTP API 서버
- **Stars**: 76,000+
- 비동기 처리로 Kong의 동시 요청을 효율적으로 처리

---

## 현재 활성화된 스캐너

### Input Scanners (프롬프트 검사)

| 스캐너 | 탐지 대상 | 동작 |
|--------|---------|------|
| **Anonymize** | 이름, 이메일, 전화번호, 주민번호, 카드번호 등 PII | 마스킹 후 전달 (`[PERSON]` 등으로 치환) |
| **PromptInjection** | "이전 지시 무시", "system prompt 무시" 등 인젝션 패턴 | threshold 0.75 초과 시 차단 |
| **Toxicity** | 욕설, 혐오 발언, 위협적 언어 | threshold 0.7 초과 시 차단 |
| **TokenLimit** | 입력 길이 초과 | 4096 토큰 초과 시 차단 |
| **BanTopics** | 환경변수 `BAN_TOPICS`에 정의된 주제 | threshold 0.6 초과 시 차단 |
| **BanSubstrings** | 환경변수 `BAN_SUBSTRINGS`에 정의된 문자열 | 포함 시 차단 |

### Output Scanners (응답 검사)

| 스캐너 | 탐지 대상 | 동작 |
|--------|---------|------|
| **Deanonymize** | 익명화된 PII 복원 | 응답에서 `[PERSON]` → 원래 이름으로 복원 |
| **Sensitive** | 응답 내 민감정보 (비밀번호, 토큰, 키 등) | 감지 시 `[REDACTED]`로 대체 |

---

## 가드레일 정책 추가 방법

### 방법 1: 환경변수로 간단 제어 (재배포 필요)

ECS Task Definition의 환경변수를 수정합니다.

```bash
# 금지 주제 설정 (쉼표로 구분)
BAN_TOPICS=malware,hacking,drugs,weapon

# 금지 문자열 설정
BAN_SUBSTRINGS=ignore previous instructions,system prompt,jailbreak

# 차단 임계값 (낮을수록 더 엄격)
BLOCK_THRESHOLD=0.7

# 입력 토큰 제한
MAX_TOKENS_INPUT=2048
```

**ECS 태스크 정의 업데이트**:

```python
# deploy/scripts/update-task-def.py 실행
python deploy/scripts/update-task-def.py latest latest \
  --env BAN_TOPICS=malware,hacking \
  --env BLOCK_THRESHOLD=0.7
```

### 방법 2: 코드에서 스캐너 추가 (`guardrails/app/main.py`)

`init_scanners()` 함수에 새 스캐너를 추가합니다.

#### 예시 1: 커스텀 BanSubstrings 추가

```python
def init_scanners():
    from llm_guard.input_scanners import BanSubstrings
    
    # 회사 내부 코드명 노출 방지
    internal_codewords = ["project-x", "operation-stealth", "confidential-merger"]
    
    input_scanners.append(
        BanSubstrings(
            substrings=internal_codewords,
            match_type="word",  # "word": 단어 단위, "str": 부분 문자열
            case_sensitive=False,
            redact=True,  # 차단 대신 마스킹
            contains_all=False  # 하나라도 포함 시 트리거
        )
    )
```

#### 예시 2: 코드 시크릿 탐지 스캐너 추가

```python
def init_scanners():
    from llm_guard.input_scanners import Secrets
    
    input_scanners.append(
        Secrets(
            # 감지할 시크릿 패턴
            redact_mode="all",  # 모든 감지된 시크릿 마스킹
        )
    )
```

#### 예시 3: 언어 제한 스캐너 추가

```python
def init_scanners():
    from llm_guard.input_scanners import Language
    
    input_scanners.append(
        Language(
            valid_languages=["ko", "en"],  # 한국어, 영어만 허용
            threshold=0.6,
        )
    )
```

#### 예시 4: 커스텀 Presidio 인식기 추가 (한국 주민등록번호)

```python
def init_scanners():
    from presidio_analyzer import PatternRecognizer, Pattern
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    
    # 주민등록번호 패턴: 000000-0000000
    rrn_pattern = Pattern(
        name="KOREAN_RRN",
        regex=r"\d{6}-[1-4]\d{6}",
        score=0.9
    )
    rrn_recognizer = PatternRecognizer(
        supported_entity="KOREAN_RRN",
        patterns=[rrn_pattern]
    )
    
    # Anonymize 스캐너 생성 시 커스텀 인식기 전달
    from llm_guard.input_scanners.anonymize import Anonymize
    anonymize_scanner = Anonymize(
        vault=vault,
        recognizer_conf=BERT_LARGE_NER_CONF,
        language="en",
        # 커스텀 인식기는 Presidio AnalyzerEngine에 직접 추가 필요
    )
```

### 방법 3: 환경에 따라 다른 정책 적용

```python
def init_scanners():
    env = os.environ.get("ENVIRONMENT", "production")
    
    if env == "production":
        # 프로덕션: 더 엄격한 설정
        prompt_injection_threshold = 0.65
        toxicity_threshold = 0.60
    elif env == "staging":
        # 스테이징: 중간
        prompt_injection_threshold = 0.75
        toxicity_threshold = 0.70
    else:
        # 개발: 느슨한 설정
        prompt_injection_threshold = 0.90
        toxicity_threshold = 0.85
    
    input_scanners = [
        PromptInjection(threshold=prompt_injection_threshold),
        Toxicity(threshold=toxicity_threshold),
    ]
```

---

## 차단 시 응답 형식

가드레일에 의해 요청이 차단될 때 클라이언트가 받는 응답입니다.

```json
HTTP/1.1 400 Bad Request
{
  "detail": {
    "type": "guardrail_violation",
    "message": "[보안 안내] 요청이 보안 정책에 의해 차단되었습니다.",
    "risk_score": 0.92,
    "scanner_results": {
      "PromptInjection": 0.93,
      "Toxicity": 0.45
    }
  }
}
```

`risk_score`는 모든 스캐너 중 최댓값입니다.  
`scanner_results`에서 어느 스캐너가 높은 점수를 줬는지 확인할 수 있습니다.

---

## 성능 고려사항

### 모델 로딩 지연

ML 모델들은 컨테이너 시작 시 한 번만 로딩됩니다.  
첫 요청 처리 전 약 **60-90초**의 워밍업 시간이 필요합니다.

```python
# 앱 시작 시 한 번만 로드 (캐싱)
@app.on_event("startup")
async def startup_event():
    get_scanners()  # 모델 사전 로딩
    logger.info("Guardrails scanners initialized")
```

### 처리 지연

| 스캐너 | 추가 지연 (대략) |
|--------|----------------|
| Anonymize (Presidio) | 50-150ms |
| PromptInjection (DeBERTa) | 100-300ms |
| Toxicity (DistilBERT) | 50-150ms |
| BanTopics (zero-shot) | 200-500ms |
| TokenLimit | <5ms |
| **전체 합계** | **400ms - 1100ms** |

실제 Bedrock 응답 시간(1-3초)에 비해 추가 지연은 허용 범위 내입니다.

### ECS 리소스 권장사항

```json
{
  "guardrails": {
    "cpu": 1024,       // 1 vCPU 이상 권장 (ML 추론)
    "memoryMiB": 4096  // 4 GB 이상 권장 (모델 로딩)
  },
  "kong": {
    "cpu": 512,
    "memoryMiB": 1024
  }
}
```

---

## 결론

독립 Guardrails 미들웨어는 단순한 "추가 필터"가 아닙니다.

> **"Bedrock 가드레일이 AWS가 만든 안전망이라면,  
> 이 미들웨어는 보안 담당자가 직접 설계한 기업 맞춤 안전망입니다."**

오픈소스 ML 모델 기반으로 프롬프트 인젝션, 독성, PII, 금지 주제를 실시간 탐지하고,  
모든 정책을 코드로 관리하여 GitOps 기반의 보안 정책 관리가 가능합니다.
