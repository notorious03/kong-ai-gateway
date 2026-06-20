#!/bin/bash
# =============================================================
# AWS 인프라 초기 설정 스크립트 (최초 1회 실행)
# 생성: ECS 클러스터, ALB, Secrets Manager, CloudWatch, IAM
# =============================================================

set -e

REGION=${AWS_REGION:-us-east-1}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
VPC_ID=${VPC_ID:-$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text --region "$REGION")}

echo "===== AWS 인프라 설정 시작 ====="
echo "리전: $REGION | 계정: $ACCOUNT_ID | VPC: $VPC_ID"

# 1. CloudWatch 로그 그룹 생성
echo "[1/6] CloudWatch 로그 그룹 생성..."
aws logs create-log-group --log-group-name /ecs/kong-ai-gateway/kong --region "$REGION" 2>/dev/null || true
aws logs create-log-group --log-group-name /ecs/kong-ai-gateway/guardrails --region "$REGION" 2>/dev/null || true
aws logs put-retention-policy --log-group-name /ecs/kong-ai-gateway/kong \
  --retention-in-days 30 --region "$REGION"
aws logs put-retention-policy --log-group-name /ecs/kong-ai-gateway/guardrails \
  --retention-in-days 30 --region "$REGION"
echo "로그 그룹 생성 완료"

# 2. IAM 역할 생성
echo "[2/6] IAM 역할 생성..."

# ECS Task Execution Role (이미 있으면 스킵)
aws iam get-role --role-name ecsTaskExecutionRole 2>/dev/null || \
  aws iam create-role --role-name ecsTaskExecutionRole \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy 2>/dev/null || true

# Kong AI Gateway Task Role
aws iam get-role --role-name kongAiGatewayTaskRole 2>/dev/null || \
  aws iam create-role --role-name kongAiGatewayTaskRole \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

# 인라인 정책 연결
POLICY_DOC=$(cat "$(dirname "$0")/../ecs/iam-policy.json" | \
  sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); del d['_comment']; print(json.dumps(d))")

aws iam put-role-policy --role-name kongAiGatewayTaskRole \
  --policy-name KongAiGatewayPolicy \
  --policy-document "$POLICY_DOC"
echo "IAM 역할 생성 완료"

# 3. Secrets Manager에 시크릿 저장
echo "[3/6] Secrets Manager 시크릿 생성..."
echo "  - KONG_API_KEY 값을 입력하세요 (엔터 후 Ctrl+D):"
read -r KONG_API_KEY_VALUE

aws secretsmanager create-secret \
  --name "kong-ai-gateway/api-key" \
  --secret-string "$KONG_API_KEY_VALUE" \
  --region "$REGION" 2>/dev/null || \
  aws secretsmanager update-secret \
    --secret-id "kong-ai-gateway/api-key" \
    --secret-string "$KONG_API_KEY_VALUE" \
    --region "$REGION"

# Bedrock Guardrail ID (기존 것 재사용)
aws secretsmanager create-secret \
  --name "kong-ai-gateway/bedrock-guardrail-id" \
  --secret-string "${BEDROCK_GUARDRAIL_ID:-nrkd5a2s5f8v}" \
  --region "$REGION" 2>/dev/null || true

echo "Secrets Manager 설정 완료"

# 4. ECS 클러스터 생성
echo "[4/6] ECS 클러스터 생성..."
aws ecs create-cluster \
  --cluster-name kong-ai-gateway-cluster \
  --capacity-providers FARGATE \
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1 \
  --region "$REGION" 2>/dev/null || true
echo "ECS 클러스터 생성 완료"

# 5. 서브넷 조회
echo "[5/6] 네트워크 설정..."
SUBNET_IDS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=default-for-az,Values=true" \
  --query 'Subnets[*].SubnetId' \
  --output text --region "$REGION" | tr '\t' ',')
echo "서브넷: $SUBNET_IDS"

# 보안 그룹 생성
SG_ID=$(aws ec2 create-security-group \
  --group-name kong-ai-gateway-sg \
  --description "Kong AI Gateway Security Group" \
  --vpc-id "$VPC_ID" \
  --region "$REGION" \
  --query 'GroupId' --output text 2>/dev/null || \
  aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=kong-ai-gateway-sg" \
    --query 'SecurityGroups[0].GroupId' --output text --region "$REGION")

aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 8000 --cidr 0.0.0.0/0 \
  --region "$REGION" 2>/dev/null || true

# 6. ECS 서비스 생성
echo "[6/6] ECS 서비스 생성..."
aws ecs create-service \
  --cluster kong-ai-gateway-cluster \
  --service-name kong-ai-gateway-service \
  --task-definition kong-ai-gateway \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
  --region "$REGION" 2>/dev/null || \
  echo "서비스가 이미 존재합니다. deploy.sh로 업데이트하세요."

echo ""
echo "===== 초기 설정 완료 ====="
echo "다음 단계: ./deploy.sh 를 실행하여 이미지를 배포하세요."
echo "보안 그룹 ID: $SG_ID"
