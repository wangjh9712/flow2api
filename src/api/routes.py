"""API routes - OpenAI compatible endpoints"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from typing import List, Optional
import base64
import re
import json
from urllib.parse import urlparse
from curl_cffi.requests import AsyncSession
from ..core.auth import verify_api_key_header
from ..core.models import ChatCompletionRequest
from ..services.generation_handler import GenerationHandler, MODEL_CONFIG
from ..core.logger import debug_logger

router = APIRouter()

# Dependency injection will be set up in main.py
generation_handler: GenerationHandler = None


def set_generation_handler(handler: GenerationHandler):
    """Set generation handler instance"""
    global generation_handler
    generation_handler = handler


async def retrieve_image_data(url: str) -> Optional[bytes]:
    """
    智能获取图片数据：
    1. 优先检查是否为本地 /tmp/ 缓存文件，如果是则直接读取磁盘
    2. 如果本地不存在或是外部链接，则进行网络下载
    """
    try:
        # 简单的判断：如果URL包含 /tmp/ 且 generation_handler 已初始化
        if "/tmp/" in url and generation_handler and generation_handler.file_cache:
            # 解析路径提取文件名，例如 http://host/tmp/abc.jpg -> abc.jpg
            path = urlparse(url).path
            filename = path.split("/tmp/")[-1]
            
            # 构建本地绝对路径
            local_file_path = generation_handler.file_cache.cache_dir / filename
            
            # 检查文件是否存在
            if local_file_path.exists() and local_file_path.is_file():
                debug_logger.log_info(f"[CONTEXT] ⚡️ 命中本地缓存，直接读取: {filename}")
                return local_file_path.read_bytes()
    except Exception as e:
        debug_logger.log_warning(f"[CONTEXT] 本地文件读取尝试失败: {str(e)}")

    try:
        debug_logger.log_info(f"[CONTEXT] 本地未命中，开始网络下载: {url}")
        async with AsyncSession() as session:
            response = await session.get(url, timeout=30, impersonate="chrome110", verify=False)
            if response.status_code == 200:
                return response.content
            else:
                debug_logger.log_warning(f"[CONTEXT] 图片下载失败: {response.status_code}")
                return None
    except Exception as e:
        debug_logger.log_error(f"[CONTEXT] 图片下载出错: {str(e)}")
        return None


@router.get("/v1/models")
async def list_models(api_key: str = Depends(verify_api_key_header)):
    """List available models"""
    models = []

    for model_id, config in MODEL_CONFIG.items():
        description = f"{config['type'].capitalize()} generation"
        if config['type'] == 'image':
            description += f" - {config['model_name']}"
        else:
            description += f" - {config['model_key']}"

        models.append({
            "id": model_id,
            "object": "model",
            "owned_by": "flow2api",
            "description": description
        })

    return {
        "object": "list",
        "data": models
    }


@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    api_key: str = Depends(verify_api_key_header)
):
    """Create chat completion (unified endpoint for image and video generation)"""
    try:
        # Extract prompt from messages
        if not request.messages:
            raise HTTPException(status_code=400, detail="Messages cannot be empty")

        last_message = request.messages[-1]
        content = last_message.content

        # Handle both string and array format (OpenAI multimodal)
        prompt = ""
        images: List[bytes] = []

        if isinstance(content, str):
            # Simple text format
            prompt = content
        elif isinstance(content, list):
            # Multimodal format
            for item in content:
                if item.get("type") == "text":
                    prompt = item.get("text", "")
                elif item.get("type") == "image_url":
                    # Extract base64 image
                    image_url = item.get("image_url", {}).get("url", "")
                    if image_url.startswith("data:image"):
                        # Parse base64
                        match = re.search(r"base64,(.+)", image_url)
                        if match:
                            image_base64 = match.group(1)
                            image_bytes = base64.b64decode(image_base64)
                            images.append(image_bytes)

        # Fallback to deprecated image parameter
        if request.image and not images:
            if request.image.startswith("data:image"):
                match = re.search(r"base64,(.+)", request.image)
                if match:
                    image_base64 = match.group(1)
                    image_bytes = base64.b64decode(image_base64)
                    images.append(image_bytes)

        if not images and len(request.messages) > 1:
            # 如果当前请求没有上传图片，则尝试从历史记录中寻找最近的一张生成图
            for msg in reversed(request.messages[:-1]):
                role = getattr(msg, 'role', '') or msg.get('role', '')
                msg_content = getattr(msg, 'content', '') or msg.get('content', '')

                if role == "assistant" and isinstance(msg_content, str):
                    # 匹配 Markdown 图片格式: ![...](http...)
                    matches = re.findall(r"!\[.*?\]\((.*?)\)", msg_content)
                    if matches:
                        last_image_url = matches[-1]
                        
                        if last_image_url.startswith("http"):
                            # 使用新的智能获取函数
                            downloaded_bytes = await retrieve_image_data(last_image_url)
                            if downloaded_bytes:
                                images.append(downloaded_bytes)
                                # 找到一张图就停止
                                break
                                
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")

        # Call generation handler
        if request.stream:
            # Streaming response
            async def generate():
                async for chunk in generation_handler.handle_generation(
                    model=request.model,
                    prompt=prompt,
                    images=images if images else None,
                    stream=True
                ):
                    yield chunk

                # Send [DONE] signal
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # Non-streaming response
            result = None
            async for chunk in generation_handler.handle_generation(
                model=request.model,
                prompt=prompt,
                images=images if images else None,
                stream=False
            ):
                result = chunk

            if result:
                # Parse the result JSON string
                try:
                    result_json = json.loads(result)
                    return JSONResponse(content=result_json)
                except json.JSONDecodeError:
                    # If not JSON, return as-is
                    return JSONResponse(content={"result": result})
            else:
                raise HTTPException(status_code=500, detail="Generation failed: No response from handler")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
