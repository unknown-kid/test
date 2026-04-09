from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies import require_user
from app.models.user import User
from app.services.llm_service import get_model_config_sync
import httpx
from app.utils.http_clients import build_async_httpx_client

router = APIRouter(prefix="/api/translate", tags=["translate"])


def _normalize_chat_completion_url(raw_url: str) -> str:
    url = (raw_url or "").rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return url


class TranslateRequest(BaseModel):
    text: str
    source_lang: str = "auto"
    target_lang: str = "zh"


class TranslateResponse(BaseModel):
    original: str
    translated: str


@router.post("/", response_model=TranslateResponse)
async def translate_text(
    req: TranslateRequest,
    user: User = Depends(require_user),
):
    configs = get_model_config_sync()
    translate_type = configs.get("translate_type", "openai")  # openai or deepl

    if translate_type == "deepl":
        api_key = configs.get("translate_api_key", "")
        api_url = configs.get("translate_api_url", "")
        if not api_key:
            raise HTTPException(status_code=500, detail="翻译模型未配置")
        url = api_url.rstrip("/") if api_url else "https://api-free.deepl.com/v2/translate"
        async with build_async_httpx_client(timeout=30) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"DeepL-Auth-Key {api_key}", "Content-Type": "application/json"},
                json={"text": [req.text], "target_lang": "ZH"},
            )
            resp.raise_for_status()
            data = resp.json()
            translated = data["translations"][0]["text"]
    else:
        # OpenAI-compatible translation
        api_url = configs.get("translate_api_url", "")
        api_key = configs.get("translate_api_key", "")
        model_name = configs.get("translate_model_name", "")
        if not api_url or not api_key:
            raise HTTPException(status_code=500, detail="翻译模型未配置")

        url = _normalize_chat_completion_url(api_url)

        async with build_async_httpx_client(timeout=30) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "你是一个专业的学术翻译助手。请将用户提供的文本翻译成中文，保持学术术语的准确性。只返回翻译结果，不要其他内容。"},
                        {"role": "user", "content": req.text},
                    ],
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            translated = data["choices"][0]["message"]["content"]

    return TranslateResponse(original=req.text, translated=translated)
