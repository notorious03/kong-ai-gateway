#!/bin/bash
# =============================================================
# Kong AI Gateway - AWS ECR/ECS 배포 스크립트
# 사용법: ./deploy.sh [환경: dev|prod]
# =============================================================

set -e

ENV=${1:-dev}
REGION=${AWS_REGION:-us-east-1}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/ai-guardrails"
ECS_CLUSTER="kong-ai-gateway-cluster"
ECS_SERVICE="kong-ai-gateway-service"

echo "===== Kong AI Gateway 배포 시작 ====="
echo "환경: $ENV | 리전: $REGION | 계정: $ACCOUNT_ID"

# 1. ECR 로그인
echo "[1/5] ECR 로그인..."
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

# 2. ECR 리포지토리 생성 (없으면)
echo "[2/5] ECR 리포지토리 확인..."
aws ecr describe-repositories --repository-names ai-guardrails --region "$REGION" 2>/dev/null || \
  aws ecr create-repository --repository-name ai-guardrails --region "$REGION" \
    --image-scanning-configuration scanOnPush=true

# 3. Guardrails 이미지 빌드 및 푸시
echo "[3/5] Guardrails 이미지 빌드 중..."
cd "$(dirname "$0")/../../guardrails"
docker build -t ai-guardrails:latest .
docker tag ai-guardrails:latest "$ECR_REPO:latest"
docker tag ai-guardrails:latest "$ECR_REPO:$(git rev-parse --short HEAD 2>/dev/null || echo 'manual')"
docker push "$ECR_REPO:latest"
echo "이미지 푸시 완료: $ECR_REPO:latest"
cd -

# 4. ECS 클러스터/서비스 존재 확인
echo "[4/5] ECS 서비스 업데이트..."
CLUSTER_EXISTS=$(aws ecs describe-clusters --clusters "$ECS_CLUSTER" --region "$REGION" \
  --query 'clusters[0].status' --output text 2>/dev/null || echo "MISSING")

if [ "$CLUSTER_EXISTS" != "ACTIVE" ]; then
  echo "ECS 클러스터가 없습니다. 먼저 setup.sh를 실행하세요."
  exit 1
fi

# Task Definition 등록
TASK_DEF=$(cat "$(dirname "$0")/../ecs/task-definition.json" | \
  sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" | \
  sed "s/EFS_FILESYSTEM_ID/${EFS_FILESYSTEM_ID:-}/g")

TASK_DEF_ARN=$(echo "$TASK_DEF" | aws ecs register-task-definition \
  --cli-input-json file:///dev/stdin \
  --region "$REGION" \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

echo "Task Definition 등록: $TASK_DEF_ARN"

# 서비스 업데이트
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$TASK_DEF_ARN" \
  --force-new-deployment \
  --region "$REGION" > /dev/null

echo "[5/5] 배포 상태 대기 중 (최대 5분)..."
aws ecs wait services-stable \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE" \
  --region "$REGION"

echo "===== 배포 완료 ====="

# ALB DNS 출력
ALB_DNS=$(aws elbv2 describe-load-balancers \
  --names kong-ai-gateway-alb \
  --region "$REGION" \
  --query 'LoadBalancers[0].DNSName' \
  --output text 2>/dev/null || echo "ALB 정보를 가져올 수 없음")

echo "엔드포인트: http://$ALB_DNS/v1/chat/completions"
