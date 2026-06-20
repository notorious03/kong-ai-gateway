# Docker Hub rate limit 우회: AWS ECR Public 미러 사용
FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# 시스템 의존성 (spacy, torch 빌드에 필요)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# pip 먼저 업그레이드
RUN pip install --upgrade pip

# 의존성 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# spacy 한국어 모델 다운로드
RUN python -m spacy download ko_core_news_sm 2>/dev/null || true

# 앱 소스 복사
COPY app/ ./app/

EXPOSE 8080

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
