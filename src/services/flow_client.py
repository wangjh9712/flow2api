"""Flow API Client for VideoFX (Veo)"""
import time
import uuid
import random
import base64
from typing import Dict, Any, Optional, List
from curl_cffi.requests import AsyncSession
from ..core.logger import debug_logger
from ..core.config import config


class FlowAPIException(Exception):
    """自定义API异常，包含状态码和完整响应"""
    def __init__(self, status_code: int, response_data: dict):
        self.status_code = status_code
        self.response_data = response_data
        self.error_message = response_data.get("error", {}).get("message", str(response_data))
        self.status_text = response_data.get("error", {}).get("status", f"HTTP_{status_code}")
        super().__init__(f"HTTP {status_code}: {self.status_text} - {self.error_message}")


class FlowClient:
    """VideoFX API客户端"""

    def __init__(self, proxy_manager):
        self.proxy_manager = proxy_manager
        self.labs_base_url = config.flow_labs_base_url  # https://labs.google/fx/api
        self.api_base_url = config.flow_api_base_url    # https://aisandbox-pa.googleapis.com/v1
        self.timeout = config.flow_timeout

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        use_st: bool = False,
        st_token: Optional[str] = None,
        use_at: bool = False,
        at_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """统一HTTP请求处理"""
        proxy_url = await self.proxy_manager.get_proxy_url()

        if headers is None:
            headers = {}

        # ST认证 - 使用Cookie
        if use_st and st_token:
            headers["Cookie"] = f"__Secure-next-auth.session-token={st_token}"

        # AT认证 - 使用Bearer
        if use_at and at_token:
            headers["authorization"] = f"Bearer {at_token}"

        # 通用请求头
        headers.update({
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

        # Log request
        if config.debug_enabled:
            debug_logger.log_request(
                method=method,
                url=url,
                headers=headers,
                body=json_data,
                proxy=proxy_url
            )

        start_time = time.time()

        try:
            async with AsyncSession() as session:
                if method.upper() == "GET":
                    response = await session.get(
                        url,
                        headers=headers,
                        proxy=proxy_url,
                        timeout=self.timeout,
                        impersonate="chrome110"
                    )
                else:  # POST
                    response = await session.post(
                        url,
                        headers=headers,
                        json=json_data,
                        proxy=proxy_url,
                        timeout=self.timeout,
                        impersonate="chrome110"
                    )

                duration_ms = (time.time() - start_time) * 1000

                # Log response
                if config.debug_enabled:
                    debug_logger.log_response(
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        body=response.text,
                        duration_ms=duration_ms
                    )

                # 手动检查状态码，抛出自定义异常
                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                    except:
                        # 解析JSON失败，使用文本作为错误信息
                        error_data = {
                            "error": {
                                "message": response.text,
                                "status": f"HTTP_{response.status_code}"
                            }
                        }
                    raise FlowAPIException(response.status_code, error_data)

                return response.json()

        except FlowAPIException:
            # 直接抛出自定义异常，保持状态码信息
            raise

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = str(e)

            if config.debug_enabled:
                debug_logger.log_error(
                    error_message=error_msg,
                    status_code=getattr(e, 'status_code', None),
                    response_text=getattr(e, 'response_text', None)
                )

            raise Exception(f"Flow API request failed: {error_msg}")

    # ========== 认证相关 (使用ST) ==========

    async def st_to_at(self, st: str) -> dict:
        """ST转AT"""
        url = f"{self.labs_base_url}/auth/session"
        result = await self._make_request(
            method="GET",
            url=url,
            use_st=True,
            st_token=st
        )
        return result

    # ... (其余方法保持不变) ...

    # ========== 项目管理 (使用ST) ==========

    async def create_project(self, st: str, title: str) -> str:
        """创建项目,返回project_id"""
        url = f"{self.labs_base_url}/trpc/project.createProject"
        json_data = {
            "json": {
                "projectTitle": title,
                "toolName": "PINHOLE"
            }
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_st=True,
            st_token=st
        )

        project_id = result["result"]["data"]["json"]["result"]["projectId"]
        return project_id

    async def delete_project(self, st: str, project_id: str):
        """删除项目"""
        url = f"{self.labs_base_url}/trpc/project.deleteProject"
        json_data = {
            "json": {
                "projectToDeleteId": project_id
            }
        }

        await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_st=True,
            st_token=st
        )

    # ========== 余额查询 (使用AT) ==========

    async def get_credits(self, at: str) -> dict:
        """查询余额"""
        url = f"{self.api_base_url}/credits"
        result = await self._make_request(
            method="GET",
            url=url,
            use_at=True,
            at_token=at
        )
        return result

    # ========== 图片上传 (使用AT) ==========

    async def upload_image(
        self,
        at: str,
        image_bytes: bytes,
        aspect_ratio: str = "IMAGE_ASPECT_RATIO_LANDSCAPE"
    ) -> str:
        """上传图片,返回mediaGenerationId"""
        if aspect_ratio.startswith("VIDEO_"):
            aspect_ratio = aspect_ratio.replace("VIDEO_", "IMAGE_")

        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        url = f"{self.api_base_url}:uploadUserImage"
        json_data = {
            "imageInput": {
                "rawImageBytes": image_base64,
                "mimeType": "image/jpeg",
                "isUserUploaded": True,
                "aspectRatio": aspect_ratio
            },
            "clientContext": {
                "sessionId": self._generate_session_id(),
                "tool": "ASSET_MANAGER"
            }
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        media_id = result["mediaGenerationId"]["mediaGenerationId"]
        return media_id

    # ========== 图片生成 (使用AT) - 同步返回 ==========

    async def generate_image(
        self,
        at: str,
        project_id: str,
        prompt: str,
        model_name: str,
        aspect_ratio: str,
        image_inputs: Optional[List[Dict]] = None,
        count: int = 1
    ) -> dict:
        """生成图片(同步返回)"""
        url = f"{self.api_base_url}/projects/{project_id}/flowMedia:batchGenerateImages"

        recaptcha_token = await self._get_recaptcha_token(project_id) or ""
        session_id = self._generate_session_id()

        requests_list = []
        generated_seeds = []

        # Loop to create multiple requests with unique seeds
        for _ in range(count):
            seed = random.randint(1, 99999)
            generated_seeds.append(seed)
            
            request_data = {
                "clientContext": {
                    "recaptchaToken": recaptcha_token,
                    "projectId": project_id,
                    "sessionId": session_id,
                    "tool": "PINHOLE"
                },
                "seed": seed,
                "imageModelName": model_name,
                "imageAspectRatio": aspect_ratio,
                "prompt": prompt,
                "imageInputs": image_inputs or []
            }
            requests_list.append(request_data)

        json_data = {
            "clientContext": {
                "recaptchaToken": recaptcha_token,
                "sessionId": session_id
            },
            "requests": requests_list
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        result["_generated_seeds"] = generated_seeds
        return result

    # ========== 视频生成 (使用AT) - 异步返回 ==========

    async def generate_video_text(
        self,
        at: str,
        project_id: str,
        prompt: str,
        model_key: str,
        aspect_ratio: str,
        user_paygate_tier: str = "PAYGATE_TIER_ONE"
    ) -> dict:
        """文生视频,返回task_id"""
        url = f"{self.api_base_url}/video:batchAsyncGenerateVideoText"

        recaptcha_token = await self._get_recaptcha_token(project_id) or ""
        session_id = self._generate_session_id()
        scene_id = str(uuid.uuid4())

        json_data = {
            "clientContext": {
                "recaptchaToken": recaptcha_token,
                "sessionId": session_id,
                "projectId": project_id,
                "tool": "PINHOLE",
                "userPaygateTier": user_paygate_tier
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "seed": random.randint(1, 99999),
                "textInput": {
                    "prompt": prompt
                },
                "videoModelKey": model_key,
                "metadata": {
                    "sceneId": scene_id
                }
            }]
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        return result

    async def generate_video_reference_images(
        self,
        at: str,
        project_id: str,
        prompt: str,
        model_key: str,
        aspect_ratio: str,
        reference_images: List[Dict],
        user_paygate_tier: str = "PAYGATE_TIER_ONE"
    ) -> dict:
        """图生视频,返回task_id"""
        url = f"{self.api_base_url}/video:batchAsyncGenerateVideoReferenceImages"

        recaptcha_token = await self._get_recaptcha_token(project_id) or ""
        session_id = self._generate_session_id()
        scene_id = str(uuid.uuid4())

        json_data = {
            "clientContext": {
                "recaptchaToken": recaptcha_token,
                "sessionId": session_id,
                "projectId": project_id,
                "tool": "PINHOLE",
                "userPaygateTier": user_paygate_tier
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "seed": random.randint(1, 99999),
                "textInput": {
                    "prompt": prompt
                },
                "videoModelKey": model_key,
                "referenceImages": reference_images,
                "metadata": {
                    "sceneId": scene_id
                }
            }]
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        return result

    async def generate_video_start_end(
        self,
        at: str,
        project_id: str,
        prompt: str,
        model_key: str,
        aspect_ratio: str,
        start_media_id: str,
        end_media_id: str,
        user_paygate_tier: str = "PAYGATE_TIER_ONE"
    ) -> dict:
        """收尾帧生成视频,返回task_id"""
        url = f"{self.api_base_url}/video:batchAsyncGenerateVideoStartAndEndImage"

        recaptcha_token = await self._get_recaptcha_token(project_id) or ""
        session_id = self._generate_session_id()
        scene_id = str(uuid.uuid4())

        json_data = {
            "clientContext": {
                "recaptchaToken": recaptcha_token,
                "sessionId": session_id,
                "projectId": project_id,
                "tool": "PINHOLE",
                "userPaygateTier": user_paygate_tier
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "seed": random.randint(1, 99999),
                "textInput": {
                    "prompt": prompt
                },
                "videoModelKey": model_key,
                "startImage": {
                    "mediaId": start_media_id
                },
                "endImage": {
                    "mediaId": end_media_id
                },
                "metadata": {
                    "sceneId": scene_id
                }
            }]
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        return result

    async def generate_video_start_image(
        self,
        at: str,
        project_id: str,
        prompt: str,
        model_key: str,
        aspect_ratio: str,
        start_media_id: str,
        user_paygate_tier: str = "PAYGATE_TIER_ONE"
    ) -> dict:
        """仅首帧生成视频,返回task_id"""
        url = f"{self.api_base_url}/video:batchAsyncGenerateVideoStartAndEndImage"

        recaptcha_token = await self._get_recaptcha_token(project_id) or ""
        session_id = self._generate_session_id()
        scene_id = str(uuid.uuid4())

        json_data = {
            "clientContext": {
                "recaptchaToken": recaptcha_token,
                "sessionId": session_id,
                "projectId": project_id,
                "tool": "PINHOLE",
                "userPaygateTier": user_paygate_tier
            },
            "requests": [{
                "aspectRatio": aspect_ratio,
                "seed": random.randint(1, 99999),
                "textInput": {
                    "prompt": prompt
                },
                "videoModelKey": model_key,
                "startImage": {
                    "mediaId": start_media_id
                },
                "metadata": {
                    "sceneId": scene_id
                }
            }]
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        return result

    # ========== 任务轮询 (使用AT) ==========

    async def check_video_status(self, at: str, operations: List[Dict]) -> dict:
        """查询视频生成状态"""
        url = f"{self.api_base_url}/video:batchCheckAsyncVideoGenerationStatus"

        json_data = {
            "operations": operations
        }

        result = await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_at=True,
            at_token=at
        )

        return result

    # ========== 媒体删除 (使用ST) ==========

    async def delete_media(self, st: str, media_names: List[str]):
        """删除媒体"""
        url = f"{self.labs_base_url}/trpc/media.deleteMedia"
        json_data = {
            "json": {
                "names": media_names
            }
        }

        await self._make_request(
            method="POST",
            url=url,
            json_data=json_data,
            use_st=True,
            st_token=st
        )

    # ========== 辅助方法 ==========

    def _generate_session_id(self) -> str:
        """生成sessionId: ;timestamp"""
        return f";{int(time.time() * 1000)}"

    def _generate_scene_id(self) -> str:
        """生成sceneId: UUID"""
        return str(uuid.uuid4())

    async def _get_recaptcha_token(self, project_id: str) -> Optional[str]:
        """获取reCAPTCHA token - 支持两种方式"""

        client_key = config.yescaptcha_api_key
        if not client_key:
            debug_logger.log_info("[reCAPTCHA] API key not configured, skipping")
            return None

        website_key = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
        website_url = f"https://labs.google/fx/tools/flow/project/{project_id}"
        base_url = config.yescaptcha_base_url
        page_action = "FLOW_GENERATION"

        try:
            async with AsyncSession() as session:
                create_url = f"{base_url}/createTask"
                create_data = {
                    "clientKey": client_key,
                    "task": {
                        "websiteURL": website_url,
                        "websiteKey": website_key,
                        "type": "RecaptchaV3TaskProxylessM1",
                        "pageAction": page_action
                    }
                }

                result = await session.post(create_url, json=create_data, impersonate="chrome110")
                result_json = result.json()
                task_id = result_json.get('taskId')

                debug_logger.log_info(f"[reCAPTCHA] created task_id: {task_id}")

                if not task_id:
                    return None

                get_url = f"{base_url}/getTaskResult"
                for i in range(40):
                    get_data = {
                        "clientKey": client_key,
                        "taskId": task_id
                    }
                    result = await session.post(get_url, json=get_data, impersonate="chrome110")
                    result_json = result.json()

                    debug_logger.log_info(f"[reCAPTCHA] polling #{i+1}: {result_json}")

                    solution = result_json.get('solution', {})
                    response = solution.get('gRecaptchaResponse')

                    if response:
                        return response

                    time.sleep(3)

                return None

        except Exception as e:
            debug_logger.log_error(f"[reCAPTCHA] error: {str(e)}")
            return None