"""
Tripo API 客户端封装
==================
异步封装 Tripo 3D 生成 API：图片转 3D 模型 → 下载 GLB 文件。

依赖: pip install tripo3d
API Key: 从环境变量 TRIPO_API_KEY 获取，或直接在 config.py 中设置
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional

# ============================================================
# Monkey-patch: 让 tripo3d SDK 使用系统代理
# 在导入 SDK 之前设置 aiohttp 的代理环境变量
# ============================================================
# 确保 aiohttp session 读取系统代理设置
os.environ.setdefault("trust_env", "true")

from tripo3d import TripoClient, TaskStatus

# 补丁: 替换 aiohttp session 创建方法，加入 trust_env=True
try:
    from tripo3d.client_impl.aiohttp_client_impl import AioHttpClientImpl
    _orig_ensure_session = AioHttpClientImpl._ensure_session

    async def _patched_ensure_session(self):
        if self._session is None or self._session.closed:
            import aiohttp
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.api_key}"},
                connector=connector,
                trust_env=True,  # <-- 关键: 读取 HTTPS_PROXY 等环境变量
            )
        return self._session

    AioHttpClientImpl._ensure_session = _patched_ensure_session
except ImportError:
    pass  # 如果不是 aiohttp 实现则忽略

from config import (
    TRIPO_API_KEY,
    MODELS_DIR,
    TRIPO_MODEL_VERSION,
    TRIPO_TEXTURE_QUALITY,
    TRIPO_FACE_LIMIT,
    TRIPO_PBR,
)


class TripoConverter:
    """
    Tripo API 转换器。

    用法:
        async with TripoConverter() as converter:
            glb_path = await converter.convert_image("path/to/photo.jpg")
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Tripo API Key，若不传则从 config.TRIPO_API_KEY 读取
        """
        self.api_key = api_key or TRIPO_API_KEY
        if not self.api_key:
            raise ValueError(
                "Tripo API Key 未设置！\n"
                "  方式1: 设置环境变量 TRIPO_API_KEY\n"
                "  方式2: 在 config.py 中设置 TRIPO_API_KEY\n"
                "  获取 Key: https://platform.tripo3d.ai"
            )
        self._client: Optional[TripoClient] = None

    async def __aenter__(self):
        self._client = TripoClient(api_key=self.api_key)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.close()

    @property
    def client(self) -> TripoClient:
        if self._client is None:
            raise RuntimeError("TripoConverter 未初始化，请使用 'async with' 上下文管理器")
        return self._client

    async def convert_image(
        self,
        image_path: str,
        output_dir: Optional[str] = None,
        model_version: str = TRIPO_MODEL_VERSION,
        texture_quality: str = TRIPO_TEXTURE_QUALITY,
        face_limit: int = TRIPO_FACE_LIMIT,
        pbr: bool = TRIPO_PBR,
    ) -> Optional[Path]:
        """
        将单张图片转换为 3D 模型 (GLB)。

        Args:
            image_path: 输入图片路径
            output_dir: 输出目录，默认 MODELS_DIR
            model_version: 模型版本 (v2.0, v2.5 等)
            texture_quality: 贴图质量
            face_limit: 面数上限
            pbr: 是否 PBR 材质

        Returns:
            下载的 GLB 文件路径，失败返回 None
        """
        image = Path(image_path)
        if not image.exists():
            print(f"[tripo] ❌ 图片不存在: {image_path}")
            return None

        out_dir = Path(output_dir) if output_dir else MODELS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"[tripo] 🚀 开始转换: {image.name}")

        try:
            # Step 1: 创建图片转 3D 任务
            task_id = await self.client.image_to_model(
                image=str(image_path),
                model_version=model_version,
                texture_quality=texture_quality,
                face_limit=face_limit,
                pbr=pbr,
            )
            print(f"[tripo]   任务 ID: {task_id}")

            # Step 2: 等待任务完成（带进度显示）
            task = await self.client.wait_for_task(task_id, verbose=True)

            if task.status != TaskStatus.SUCCESS:
                print(f"[tripo] ❌ 任务失败: {task.status} - {task.error}")
                return None

            print(f"[tripo] ✅ 任务完成，正在下载模型...")

            # Step 3: 下载模型文件
            downloaded = await self.client.download_task_models(task, str(out_dir))

            # 优先返回 GLB 路径
            glb_path = downloaded.get("glb")
            if glb_path:
                glb_path = Path(glb_path)
                print(f"[tripo] 📦 模型已下载: {glb_path.name}")
                return glb_path

            # 如果没有 GLB，尝试其他格式
            for fmt, path in downloaded.items():
                if path:
                    print(f"[tripo] 📦 下载了 {fmt}: {Path(path).name}")
                    return Path(path)

            print("[tripo] ⚠️ 没有可用的模型文件下载")
            return None

        except Exception as e:
            print(f"[tripo] ❌ 转换异常: {type(e).__name__}: {e}")
            return None

    async def convert_batch(
        self,
        image_paths: List[str],
        output_dir: Optional[str] = None,
        concurrency: int = 3,
        **kwargs,
    ) -> List[Path]:
        """
        批量转换图片为 3D 模型（并发控制）。

        Args:
            image_paths: 图片路径列表
            output_dir: 输出目录
            concurrency: 最大并发数
            **kwargs: 传递给 convert_image 的参数

        Returns:
            成功转换的 GLB 路径列表
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _convert_one(image_path: str) -> Optional[Path]:
            async with semaphore:
                return await self.convert_image(image_path, output_dir, **kwargs)

        print(f"[tripo] 🔄 批量转换 {len(image_paths)} 张图片（并发={concurrency}）...")

        tasks = [_convert_one(str(p)) for p in image_paths]
        results = await asyncio.gather(*tasks)

        # 过滤失败结果
        glb_files = [r for r in results if r is not None]
        print(f"[tripo] 🎉 批量转换完成: {len(glb_files)}/{len(image_paths)} 成功")
        return glb_files


# ============================================================
# 便捷函数（无需手动管理上下文管理器）
# ============================================================

async def image_to_glb(
    image_path: str,
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[Path]:
    """
    便捷函数：图片 → GLB 文件。

    用法:
        glb_path = await image_to_glb("path/to/photo.jpg")
    """
    async with TripoConverter(api_key=api_key) as converter:
        return await converter.convert_image(image_path, output_dir)


async def batch_images_to_glb(
    image_paths: List[str],
    output_dir: Optional[str] = None,
    api_key: Optional[str] = None,
    concurrency: int = 3,
) -> List[Path]:
    """
    便捷函数：批量图片 → GLB 文件。

    用法:
        glb_files = await batch_images_to_glb(["a.jpg", "b.jpg", "c.jpg"])
    """
    async with TripoConverter(api_key=api_key) as converter:
        return await converter.convert_batch(image_paths, output_dir, concurrency)


# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    import sys

    async def _test():
        if len(sys.argv) < 2:
            print("用法: python tripo_client.py <图片路径> [输出目录]")
            print("前提: 设置环境变量 TRIPO_API_KEY")
            return

        image = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else None

        result = await image_to_glb(image, out)
        if result:
            print(f"\n✅ 转换成功: {result}")
        else:
            print("\n❌ 转换失败")

    asyncio.run(_test())
