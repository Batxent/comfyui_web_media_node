import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

try:
    from .cache_service import PullThroughCacheService
except ImportError:  # pragma: no cover
    from cache_service import PullThroughCacheService


def _cache_dir() -> str:
    default_dir = Path(__file__).resolve().parent / "cache"
    return os.getenv("MEDIA_CACHE_DIR", str(default_dir))


def _cache_max_bytes() -> int:
    return int(os.getenv("MEDIA_CACHE_MAX_BYTES", str(100 * 1024 * 1024)))


def _disk_cache_max_bytes() -> int:
    return int(os.getenv("MEDIA_DISK_CACHE_MAX_BYTES", str(10 * 1024 * 1024 * 1024)))


def _cache_timeout_seconds() -> int:
    return int(os.getenv("MEDIA_CACHE_TIMEOUT_SECONDS", "15"))


def _cache_lock_timeout_seconds() -> int:
    return int(os.getenv("MEDIA_CACHE_LOCK_TIMEOUT_SECONDS", "10"))


def _memory_cache_enabled() -> bool:
    raw = os.getenv("MEDIA_MEMORY_CACHE_ENABLED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _memory_cache_max_items() -> int:
    return int(os.getenv("MEDIA_MEMORY_CACHE_MAX_ITEMS", "64"))


def _memory_cache_ttl_seconds() -> int:
    return int(os.getenv("MEDIA_MEMORY_CACHE_TTL_SECONDS", "300"))


_MEMORY_CACHE_LOCK = threading.Lock()
_MEMORY_CACHE: "OrderedDict[str, tuple[float, tuple[torch.Tensor, torch.Tensor, int, int]]]" = OrderedDict()


def _memory_cache_key(full_path: str) -> str:
    try:
        stat = os.stat(full_path)
        return f"{full_path}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return full_path


def _memory_cache_get(
    key: str,
    ttl_seconds: int,
) -> tuple[torch.Tensor, torch.Tensor, int, int] | None:
    now = time.time()
    with _MEMORY_CACHE_LOCK:
        item = _MEMORY_CACHE.get(key)
        if not item:
            return None
        ts, value = item
        if ttl_seconds > 0 and now - ts > ttl_seconds:
            _MEMORY_CACHE.pop(key, None)
            return None
        _MEMORY_CACHE.move_to_end(key)
        return value


def _memory_cache_set(
    key: str,
    value: tuple[torch.Tensor, torch.Tensor, int, int],
    max_items: int,
) -> None:
    now = time.time()
    with _MEMORY_CACHE_LOCK:
        _MEMORY_CACHE[key] = (now, value)
        _MEMORY_CACHE.move_to_end(key)
        if max_items > 0:
            while len(_MEMORY_CACHE) > max_items:
                _MEMORY_CACHE.popitem(last=False)


def _service() -> PullThroughCacheService:
    return PullThroughCacheService(
        cache_dir=_cache_dir(),
        timeout_seconds=_cache_timeout_seconds(),
        max_bytes=_cache_max_bytes(),
        lock_timeout_seconds=_cache_lock_timeout_seconds(),
        disk_cache_max_bytes=_disk_cache_max_bytes(),
    )


class MediaPullThroughCacheAsset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_url": ("STRING", {"default": ""}),
                "asset_key": ("STRING", {"default": ""}),
                "force_refresh": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = ("filename", "subfolder", "full_path", "cache_hit")
    FUNCTION = "run"
    CATEGORY = "media/cache"

    @classmethod
    def IS_CHANGED(cls, source_url: str, asset_key: str, force_refresh: bool, **kwargs):
        if force_refresh:
            return float("NaN")
        return ""

    def run(self, source_url: str, asset_key: str, force_refresh: bool):
        result = _service().resolve(
            source_url=source_url,
            asset_key=asset_key,
            force_refresh=force_refresh,
        )
        return (result.filename, result.subfolder, result.full_path, result.cache_hit)


class MediaLoadCachedImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "full_path": ("STRING", {"default": ""}),
                "memory_cache_enabled": ("BOOLEAN", {"default": False}),
                "memory_cache_max_items": (
                    "INT",
                    {"default": 64, "min": 1, "max": 4096},
                ),
                "memory_cache_ttl_seconds": (
                    "INT",
                    {"default": 300, "min": 0, "max": 86400},
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT")
    RETURN_NAMES = ("image", "mask", "width", "height")
    FUNCTION = "run"
    CATEGORY = "media/cache"

    def run(
        self,
        full_path: str,
        memory_cache_enabled: bool = False,
        memory_cache_max_items: int = 64,
        memory_cache_ttl_seconds: int = 300,
    ):
        enabled = memory_cache_enabled or _memory_cache_enabled()
        max_items = (
            memory_cache_max_items
            if memory_cache_enabled
            else _memory_cache_max_items()
        )
        ttl_seconds = (
            memory_cache_ttl_seconds
            if memory_cache_enabled
            else _memory_cache_ttl_seconds()
        )
        cache_key = _memory_cache_key(full_path)
        if enabled:
            cached = _memory_cache_get(cache_key, ttl_seconds=ttl_seconds)
            if cached:
                return cached

        path = Path(full_path)
        if not path.exists():
            raise ValueError(f"cached file not found: {full_path}")

        try:
            image = Image.open(path)
        except UnidentifiedImageError:
            raise ValueError(
                f"Cannot load {path.name} as an image. If this is a video file, "
                "please use the MediaPullThroughCacheAsset node alongside a Video Loader."
            )

        images = []
        masks = []
        parsed_width, parsed_height = 0, 0

        for i, frame in enumerate(ImageSequence.Iterator(image)):
            frame = ImageOps.exif_transpose(frame)
            if i == 0:
                parsed_width, parsed_height = frame.width, frame.height
            rgb = frame.convert("RGB")
            arr = np.array(rgb).astype(np.float32) / 255.0
            images.append(torch.from_numpy(arr))

            if "A" in frame.getbands():
                alpha = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
                masks.append(1.0 - torch.from_numpy(alpha))
            else:
                masks.append(
                    torch.zeros((parsed_height, parsed_width), dtype=torch.float32)
                )

        image_tensor = torch.stack(images)
        mask_tensor = torch.stack(masks)

        result = (image_tensor, mask_tensor, parsed_width, parsed_height)
        if enabled:
            _memory_cache_set(cache_key, result, max_items=max_items)
        return result


class MediaLoadImageFromURLWithCache:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_url": ("STRING", {"default": ""}),
                "asset_key": ("STRING", {"default": ""}),
                "force_refresh": ("BOOLEAN", {"default": False}),
                "memory_cache_enabled": ("BOOLEAN", {"default": False}),
                "memory_cache_max_items": (
                    "INT",
                    {"default": 64, "min": 1, "max": 4096},
                ),
                "memory_cache_ttl_seconds": (
                    "INT",
                    {"default": 300, "min": 0, "max": 86400},
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "BOOLEAN", "STRING")
    RETURN_NAMES = ("image", "mask", "width", "height", "cache_hit", "full_path")
    FUNCTION = "run"
    CATEGORY = "media/cache"

    @classmethod
    def IS_CHANGED(cls, source_url: str, asset_key: str, force_refresh: bool, **kwargs):
        if force_refresh:
            return float("NaN")
        return ""

    def run(
        self,
        source_url: str,
        asset_key: str,
        force_refresh: bool,
        memory_cache_enabled: bool = False,
        memory_cache_max_items: int = 64,
        memory_cache_ttl_seconds: int = 300,
    ):
        result = _service().resolve(
            source_url=source_url,
            asset_key=asset_key,
            force_refresh=force_refresh,
        )
        image, mask, width, height = MediaLoadCachedImage().run(
            result.full_path,
            memory_cache_enabled=memory_cache_enabled,
            memory_cache_max_items=memory_cache_max_items,
            memory_cache_ttl_seconds=memory_cache_ttl_seconds,
        )
        return (image, mask, width, height, result.cache_hit, result.full_path)


NODE_CLASS_MAPPINGS = {
    "MediaPullThroughCacheAsset": MediaPullThroughCacheAsset,
    "MediaLoadCachedImage": MediaLoadCachedImage,
    "MediaLoadImageFromURLWithCache": MediaLoadImageFromURLWithCache,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MediaPullThroughCacheAsset": "Media Pull-Through Cache Asset",
    "MediaLoadCachedImage": "Media Load Cached Image",
    "MediaLoadImageFromURLWithCache": "Media Load Image From URL (Cached)",
}
