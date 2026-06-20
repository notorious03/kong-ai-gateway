import os
import json
import logging
import boto3
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("guardrails")

app = FastAPI(title="AI Guardrails Service", version="1.0.0")

# Bedrock 클라이언트 (ECS Task Role 자동 인증)
def get_bedrock_client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-runtime", region_name=region)

BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
BEDROCK_GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
BEDROCK_GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")

# =============================================================
# 스캐너 초기화 (LLM Guard)
# =============================================================
def init_scanners():
    from llm_guard.input_scanners import (
        Anonymize,
        PromptInjection,
        Toxicity,
        BanTopics,
        BanSubstrings,
        TokenLimit,
    )
    from llm_guard.input_scanners.anonymize_helpers import BERT_LARGE_NER_CONF
    from llm_guard.output_scanners import (
        Deanonymize,
        Sensitive,
    )
    from llm_guard.vault import Vault

    vault = Vault()

    ban_topics = [t.strip() for t in os.environ.get("BAN_TOPICS", "").split(",") if t.strip()]
    ban_substrings = [s.strip() for s in os.environ.get("BAN_SUBSTRINGS", "").split(",") if s.strip()]

    input_scanners = [
        Anonymize(
            vault=vault,
            preamble="Detect and anonymize PII including personal data.",
            allowed_names=[],
            hidden_names=[],
            recognizer_conf=BERT_LARGE_NER_CONF,
            language="en",
        ),
        PromptInjection(threshold=0.75),
        Toxicity(threshold=0.7),
        TokenLimit(limit=int(os.environ.get("MAX_TOKENS_INPUT", "4096"))),
    ]

    if ban_topics:
        input_scanners.append(BanTopics(topics=ban_topics, threshold=0.6))
    if ban_substrings:
        input_scanners.append(BanSubstrings(substrings=ban_substrings, match_type="word"))

    output_scanners = [
        Deanonymize(vault=vault),
        Sensitive(redact=True),
    ]

    return input_scanners, output_scanners, vault

# 스캐너 lazy 초기화 (컨테이너 시작 시 무거운 모델 로딩 방지)
_input_scanners = None
_output_scanners = None
_vault = None
_scanners_ready = False

def get_scanners():
    global _input_scanners, _output_scanners, _vault, _scanners_ready
    if not _scanners_ready:
        logger.info("LLM Guard 스캐너 초기화 중...")
        _input_scanners, _output_scanners, _vault = init_scanners()
        _scanners_ready = True
        logger.info("LLM Guard 스캐너 초기화 완료")
    return _input_scanners, _output_scanners, _vault

# =============================================================
# 입력 검사
# =============================================================
def scan_input(text: str) -> tuple[str, bool, dict]:
    """
    반환: (정제된 텍스트, 차단여부, 스캔결과상세)
    """
    from llm_guard import scan_prompt
    input_scanners, _, _ = get_scanners()

    sanitized, results, risk_score = scan_prompt(input_scanners, text)

    # risk_score may be dict or float depending on llm-guard version
    if isinstance(risk_score, dict):
        numeric_score = max(risk_score.values()) if risk_score else 0.0
    else:
        numeric_score = float(risk_score) if risk_score is not None else 0.0

    blocked = numeric_score > float(os.environ.get("BLOCK_THRESHOLD", "0.8"))

    details = {
        "risk_score": numeric_score,
        "scanner_results": {k: (v if isinstance(v, (int, float, bool, str)) else str(v)) for k, v in results.items()},
    }
    return sanitized, blocked, details

# =============================================================
# 출력 검사
# =============================================================
def scan_output(prompt: str, response_text: str) -> tuple[str, dict]:
    from llm_guard import scan_output as llm_scan_output
    _, output_scanners, _ = get_scanners()

    sanitized, results, risk_score = llm_scan_output(output_scanners, prompt, response_text)

    if isinstance(risk_score, dict):
        numeric_score = max(risk_score.values()) if risk_score else 0.0
    else:
        numeric_score = float(risk_score) if risk_score is not None else 0.0

    details = {
        "risk_score": numeric_score,
        "scanner_results": {k: (v if isinstance(v, (int, float, bool, str)) else str(v)) for k, v in results.items()},
    }
    return sanitized, details

# =============================================================
# Bedrock 호출
# =============================================================
def call_bedrock(messages: list, max_tokens: int = 4096) -> dict:
    client = get_bedrock_client()

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }

    kwargs = {
        "modelId": BEDROCK_MODEL_ID,
        "body": json.dumps(body),
        "contentType": "application/json",
        "accept": "application/json",
    }

    # Bedrock 기본 가드레일도 함께 적용 (설정된 경우)
    if BEDROCK_GUARDRAIL_ID:
        kwargs["guardrailIdentifier"] = BEDROCK_GUARDRAIL_ID
        kwargs["guardrailVersion"] = BEDROCK_GUARDRAIL_VERSION

    response = client.invoke_model(**kwargs)
    return json.loads(response["body"].read())

# =============================================================
# 메인 엔드포인트: /v1/chat/completions (OpenAI 호환)
# =============================================================
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages field required")

    # 사용자 마지막 메시지 추출
    user_message = messages[-1].get("content", "")

    # ---- 입력 가드레일 ----
    sanitized_input, blocked, input_details = scan_input(user_message)

    logger.info(f"[INPUT SCAN] risk_score={input_details['risk_score']:.3f} blocked={blocked}")

    if blocked:
        logger.warning(f"[BLOCKED] 입력 차단: {input_details}")
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "guardrail_violation",
                    "message": "[보안 안내] 요청이 보안 정책에 의해 차단되었습니다.",
                    "risk_score": input_details["risk_score"],
                }
            },
        )

    # 정제된 입력으로 메시지 교체
    sanitized_messages = messages[:-1] + [{**messages[-1], "content": sanitized_input}]

    # ---- Bedrock 호출 ----
    max_tokens = body.get("max_tokens", 4096)
    try:
        bedrock_response = call_bedrock(sanitized_messages, max_tokens=max_tokens)
    except Exception as e:
        logger.error(f"Bedrock 호출 실패: {e}")
        raise HTTPException(status_code=502, detail=f"Bedrock error: {str(e)}")

    # ---- 출력 가드레일 ----
    output_text = bedrock_response.get("content", [{}])[0].get("text", "")
    sanitized_output, output_details = scan_output(sanitized_input, output_text)

    logger.info(f"[OUTPUT SCAN] risk_score={output_details['risk_score']:.3f}")

    # OpenAI 호환 응답 형식으로 변환
    return {
        "id": bedrock_response.get("id", "chatcmpl-guardrails"),
        "object": "chat.completion",
        "model": BEDROCK_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": sanitized_output,
                },
                "finish_reason": bedrock_response.get("stop_reason", "stop"),
            }
        ],
        "usage": {
            "prompt_tokens": bedrock_response.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": bedrock_response.get("usage", {}).get("output_tokens", 0),
            "total_tokens": (
                bedrock_response.get("usage", {}).get("input_tokens", 0)
                + bedrock_response.get("usage", {}).get("output_tokens", 0)
            ),
        },
        "x_guardrails": {
            "input_risk_score": input_details["risk_score"],
            "output_risk_score": output_details["risk_score"],
        },
    }

# =============================================================
# Bedrock-compatible endpoint (for AWS_ENDPOINT_URL routing)
# Handles POST /model/{model_id}/invoke
# =============================================================
@app.post("/model/{model_id}/invoke")
async def bedrock_invoke(model_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Bedrock Anthropic format -> extract messages
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages field required")

    user_message = messages[-1].get("content", "")
    if isinstance(user_message, list):
        # content can be list of blocks
        user_message = " ".join(
            block.get("text", "") for block in user_message if isinstance(block, dict)
        )

    sanitized_input, blocked, input_details = scan_input(user_message)
    logger.info(f"[BEDROCK INPUT SCAN] risk={input_details['risk_score']:.3f} blocked={blocked}")

    if blocked:
        logger.warning(f"[BLOCKED] {input_details}")
        raise HTTPException(
            status_code=400,
            detail={
                "type": "guardrail_violation",
                "message": "[보안 안내] 요청이 보안 정책에 의해 차단되었습니다.",
                "risk_score": input_details["risk_score"],
            },
        )

    sanitized_messages = messages[:-1] + [{**messages[-1], "content": sanitized_input}]
    max_tokens = body.get("max_tokens", 4096)

    try:
        bedrock_response = call_bedrock(sanitized_messages, max_tokens=max_tokens)
    except Exception as e:
        logger.error(f"Bedrock 호출 실패: {e}")
        raise HTTPException(status_code=502, detail=f"Bedrock error: {str(e)}")

    output_text = bedrock_response.get("content", [{}])[0].get("text", "")
    sanitized_output, output_details = scan_output(sanitized_input, output_text)
    logger.info(f"[BEDROCK OUTPUT SCAN] risk={output_details['risk_score']:.3f}")

    # Return Bedrock-native response format with sanitized output
    result = dict(bedrock_response)
    if result.get("content"):
        result["content"][0]["text"] = sanitized_output
    return result


# =============================================================
# MCP passthrough: Kong MCP Proxy가 사용
# =============================================================
@app.api_route("/mcp-passthrough/{path:path}", methods=["GET", "POST"])
async def mcp_passthrough(path: str, request: Request):
    # MCP 요청은 가드레일 없이 통과 (MCP 서버 자체 보안에 위임)
    return JSONResponse({"status": "mcp-passthrough", "path": path})

# =============================================================
# 헬스체크
# =============================================================
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "scanners_ready": _scanners_ready,
        "model": BEDROCK_MODEL_ID,
        "guardrail_id": BEDROCK_GUARDRAIL_ID or "none",
    }

@app.get("/ready")
async def ready():
    # 스캐너 초기화 트리거 (warm-up용)
    try:
        get_scanners()
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "not ready", "error": str(e)})
