from fastapi import APIRouter, Depends
from app.dependencies import require_admin
from app.models.user import User
from app.schemas.config import ModelTestRequest
import httpx

router = APIRouter(prefix="/api/admin/model-test", tags=["model-test"])


def _normalize_chat_completion_url(raw_url: str) -> str:
    url = (raw_url or "").rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return url


@router.post("/")
async def test_model_connection(
    req: ModelTestRequest,
    admin: User = Depends(require_admin),
):
    """Test model API connectivity by type."""
    try:
        if req.model_type == "chat":
            url = _normalize_chat_completion_url(req.api_url)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": req.model_name,
                        "messages": [{"role": "user", "content": "Say hi in one word."}],
                        "max_tokens": 256,
                    },
                )
                resp.raise_for_status()
                raw = resp.text
                data = resp.json() if raw else {}
                if data is None:
                    return {"success": False, "message": f"API返回空响应，状态码: {resp.status_code}"}
                choices = data.get("choices") or []
                content = ""
                if choices:
                    msg = choices[0].get("message") or {}
                    content = msg.get("content") or msg.get("reasoning") or choices[0].get("text") or ""
                if content:
                    return {"success": True, "message": f"连接成功，模型回复: {content[:100]}"}
                else:
                    return {"success": True, "message": f"连接成功，模型已响应 (model: {data.get('model', 'unknown')})"}

        elif req.model_type == "embedding":
            url = req.api_url.rstrip("/")
            if not url.endswith("/embeddings"):
                url += "/embeddings"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"},
                    json={"model": req.model_name, "input": "test embedding"},
                )
                resp.raise_for_status()
                data = resp.json()
                emb_data = data.get("data") or []
                if emb_data and emb_data[0].get("embedding"):
                    dim = len(emb_data[0]["embedding"])
                    return {"success": True, "message": f"连接成功，向量维度: {dim}"}
                else:
                    return {"success": True, "message": f"连接成功，响应: {str(data)[:200]}"}

        elif req.model_type == "translate":
            if req.translate_type == "deepl":
                url = req.api_url.rstrip("/") if req.api_url else "https://api-free.deepl.com/v2/translate"
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        url,
                        headers={"Authorization": f"DeepL-Auth-Key {req.api_key}", "Content-Type": "application/json"},
                        json={"text": ["Hello"], "target_lang": "ZH"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    translations = data.get("translations") or []
                    translated = translations[0]["text"] if translations else str(data)[:200]
                    return {"success": True, "message": f"连接成功，翻译结果: {translated}"}
            else:
                url = _normalize_chat_completion_url(req.api_url)
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {req.api_key}", "Content-Type": "application/json"},
                        json={
                            "model": req.model_name,
                            "messages": [
                                {"role": "system", "content": "Translate to Chinese."},
                                {"role": "user", "content": "Hello world"},
                            ],
                            "max_tokens": 64,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    choices = data.get("choices") or []
                    if choices and choices[0].get("message"):
                        content = choices[0]["message"].get("content", "")
                    else:
                        content = str(data)[:200]
                    return {"success": True, "message": f"连接成功，翻译结果: {content[:100]}"}
        else:
            return {"success": False, "message": "未知模型类型"}

    except httpx.HTTPStatusError as e:
        return {"success": False, "message": f"HTTP错误: {e.response.status_code} - {e.response.text[:200]}"}
    except Exception as e:
        import traceback
        return {"success": False, "message": f"连接失败: {type(e).__name__}: {str(e)[:300]}"}
