# AWS Bedrock을 선택한 이유

## 배경: 기업 내 Claude Code 도입 시 보안 담당자의 우려

기업이 Claude Code를 도입할 때 AI 보안 담당자가 가장 먼저 받는 질문은  
**"우리 코드가 Anthropic 서버로 넘어가는 거 아니야?"** 입니다.

Anthropic API(api.anthropic.com)를 직접 호출하면 프롬프트와 응답이 Anthropic의 미국 서버를 통과합니다.  
이는 다음 상황에서 즉각적인 거부 사유가 됩니다.

- 금융/의료/공공 기관의 데이터 국외 이전 규제
- 내부 코드·영업 전략이 포함된 프롬프트
- 임직원 정보나 고객 PII가 포함될 수 있는 업무 맥락

**AWS Bedrock은 이 문제를 근본적으로 해결합니다.**

---

## AWS Bedrock의 핵심 보안 이점

### 1. 데이터가 AWS 계정 밖으로 나가지 않는다

```
[직접 Anthropic API]
개발자 PC → 인터넷 → api.anthropic.com (미국) → 응답 반환

[AWS Bedrock]
개발자 PC → AWS VPC → Bedrock 엔드포인트 → 응답 반환
                         (모두 계정 내부)
```

AWS Bedrock 약관에는 명시적으로 다음이 포함됩니다.
- 고객의 프롬프트·응답을 모델 훈련에 사용하지 않음
- 데이터가 AWS 계정 경계 밖으로 이동하지 않음
- 처리 로그가 고객 CloudTrail에 기록됨 (투명성)

### 2. VPC Endpoint 구성 시 완전한 내부망 통신

```yaml
# AWS PrivateLink로 Bedrock 엔드포인트를 VPC 내부로 가져오기
# terraform 예시
resource "aws_vpc_endpoint" "bedrock" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.us-east-1.bedrock-runtime"
  vpc_endpoint_type = "Interface"
  subnet_ids        = [aws_subnet.private.id]
  security_group_ids = [aws_security_group.bedrock_endpoint.id]
}
```

VPC Endpoint 구성 후에는 ECS 컨테이너 → Bedrock 요청이 인터넷을 전혀 거치지 않습니다.  
심지어 ECS 태스크에 퍼블릭 IP가 없어도 Bedrock을 호출할 수 있습니다.

### 3. IAM 기반 세밀한 접근 제어

API 키 대신 IAM Role을 사용하므로:

```json
// 특정 모델만 허용하는 IAM 정책
{
  "Effect": "Allow",
  "Action": "bedrock:InvokeModel",
  "Resource": [
    "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6*"
  ],
  "Condition": {
    "StringEquals": {
      "aws:RequestedRegion": "us-east-1"
    }
  }
}
```

- 팀별 IAM Role로 사용 가능 모델 차별화
- MFA Condition으로 민감 모델 추가 인증 요구 가능
- 키 노출 리스크 없음 (자격증명 자동 로테이션)

### 4. 규정 준수 인증 상속

| 인증 | 활용 |
|------|------|
| ISO 27001 | 정보보안 관리체계 인증 근거 |
| SOC 2 Type II | 서비스 신뢰 원칙 감사 |
| PCI-DSS Level 1 | 카드 정보 처리 환경 |
| HIPAA BAA | 의료정보 처리 |
| ISMS-P | 국내 정보보호 인증 (AWS 서울 리전) |

AWS 인프라 위에서 Bedrock을 사용하면 이 인증들이 "상속"되어  
자사 컴플라이언스 심사 시 증빙 자료로 활용할 수 있습니다.

### 5. 데이터 레지던시 보장

```python
# 리전을 명시하면 그 외 리전으로 데이터 이동 없음
client = boto3.client("bedrock-runtime", region_name="ap-northeast-2")  # 서울 리전
```

Cross-region inference profile(`us.anthropic.*`)을 사용하면 미국 리전에서 처리됩니다.  
국내 데이터 레지던시가 필요한 경우 서울 리전 단일 모델 ARN을 사용해야 합니다.

```python
# 서울 리전 전용 (데이터 한국 내 처리)
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
# region_name="ap-northeast-2" 필수
```

### 6. 사용량 가시성과 비용 제어

```bash
# 팀별 태그로 비용 추적
aws bedrock tag-resource \
  --resource-arn arn:aws:bedrock:... \
  --tags Team=engineering,Project=claude-code
```

AWS Cost Explorer에서 팀별 Claude 사용량을 직접 확인하고  
예산 초과 시 알림·자동 차단을 설정할 수 있습니다.

---

## Bedrock vs 직접 API 비교

| 항목 | Anthropic API | AWS Bedrock |
|------|--------------|-------------|
| 데이터 경로 | 인터넷 → Anthropic 서버 | AWS VPC 내부 |
| 인증 방식 | API 키 (노출 위험) | IAM Role (자동 관리) |
| 감사 로그 | 없음 | CloudTrail 전수 기록 |
| 규정 준수 | 별도 검토 필요 | AWS 인증 상속 |
| 데이터 레지던시 | 미국 | 리전 선택 가능 |
| 훈련 데이터 사용 | 옵트아웃 필요 | 계약 상 사용 불가 |
| 비용 청구 | Anthropic 별도 계정 | AWS 통합 청구 |
| 모델 버전 관리 | API 직접 | Bedrock 콘솔 |

---

## 결론

AWS Bedrock은 단순히 Claude를 AWS에서 실행하는 것이 아닙니다.  
**기업의 데이터 주권과 컴플라이언스 요구사항을 충족하면서**  
Claude의 성능을 그대로 활용할 수 있는 엔터프라이즈 경로입니다.

AI 보안 담당자 입장에서 "왜 Bedrock인가?"에 대한 답은 명확합니다:  
데이터가 우리 AWS 계정을 떠나지 않고, 모든 호출이 감사되며, 규정 준수 증빙이 가능합니다.
