import hashlib
import json
import mimetypes
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen


_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}


@dataclass
class CacheResult:
    filename: str
    subfolder: str
    full_path: str
    cache_hit: bool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_key(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned[:120] if cleaned else ""


def _key_from_url(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def _guess_ext(source_url: str, content_type: str) -> str:
    parsed = urlparse(source_url)
    from_path = os.path.splitext(parsed.path)[1].lower()
    if from_path:
        return from_path
    if content_type:
        normalized = content_type.split(";")[0].strip().lower()
        if normalized in _CONTENT_TYPE_EXT:
            return _CONTENT_TYPE_EXT[normalized]
        guessed = mimetypes.guess_extension(normalized)
        if guessed:
            return guessed
    return ".bin"


class PullThroughCacheService:
    def __init__(
        self,
        cache_dir: str,
        timeout_seconds: int = 15,
        max_bytes: int = 100 * 1024 * 1024,
        lock_timeout_seconds: int = 10,
        disk_cache_max_bytes: int = 0,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.lock_timeout_seconds = lock_timeout_seconds
        self.disk_cache_max_bytes = disk_cache_max_bytes
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def resolve(
        self,
        source_url: str,
        asset_key: str = "",
        force_refresh: bool = False,
    ) -> CacheResult:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"}:
            local_path = self._resolve_local_file(source_url)
            return CacheResult(
                filename=local_path.name,
                subfolder="",
                full_path=str(local_path),
                cache_hit=True,
            )

        key = _safe_key(asset_key) or _key_from_url(source_url)
        lock_path = self.cache_dir / f"{key}.lock"

        existing = self._find_existing_file(key)
        if existing and existing.stat().st_size > 0 and not force_refresh:
            return CacheResult(
                filename=existing.name,
                subfolder="",
                full_path=str(existing),
                cache_hit=True,
            )

        lock_fd = self._acquire_lock(lock_path)
        try:
            existing_after_lock = self._find_existing_file(key)
            if (
                existing_after_lock
                and existing_after_lock.stat().st_size > 0
                and not force_refresh
            ):
                return CacheResult(
                    filename=existing_after_lock.name,
                    subfolder="",
                    full_path=str(existing_after_lock),
                    cache_hit=True,
                )
            final_path = self._download_to_cache(source_url=source_url, key=key)
            return CacheResult(
                filename=final_path.name,
                subfolder="",
                full_path=str(final_path),
                cache_hit=False,
            )
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                if lock_path.exists():
                    lock_path.unlink()

    def _resolve_local_file(self, source: str) -> Path:
        raw = source.strip()
        if not raw:
            raise ValueError("source_url is empty")

        path = Path(raw)
        candidates: list[Path] = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(self.cache_dir / path)
            candidates.append(path)

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue

        raise ValueError("local file not found")

    def _find_existing_file(self, key: str) -> Optional[Path]:
        for candidate in self.cache_dir.glob(f"{key}.*"):
            if candidate.suffix in {".json", ".lock", ".part"}:
                continue
            return candidate
        return None

    def _acquire_lock(self, lock_path: Path) -> Optional[int]:
        start = time.time()
        while True:
            try:
                return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                if time.time() - start > self.lock_timeout_seconds:
                    raise TimeoutError("cache lock wait timeout")
                time.sleep(0.1)

    def _download_to_cache(self, source_url: str, key: str) -> Path:
        req = Request(source_url, headers={"User-Agent": "comfyui_web_media_node/0.1"})
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            content_type = str(
                resp.headers.get("Content-Type", "application/octet-stream")
            )
            ext = _guess_ext(source_url, content_type)
            final_path = self.cache_dir / f"{key}{ext}"
            tmp_path = self.cache_dir / f"{key}.part"
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > self.max_bytes:
                        raise ValueError("remote file exceeds max size")
                    f.write(chunk)
            if downloaded <= 0:
                raise ValueError("downloaded empty file")
            os.replace(tmp_path, final_path)
            self._write_meta(
                key=key,
                source_url=source_url,
                full_path=str(final_path),
                content_type=content_type,
                size=downloaded,
            )
            if self.disk_cache_max_bytes > 0:
                threading.Thread(
                    target=self._evict_disk_cache_if_needed, daemon=True
                ).start()
            return final_path

    def _write_meta(
        self,
        key: str,
        source_url: str,
        full_path: str,
        content_type: str,
        size: int,
    ) -> None:
        meta = {
            "key": key,
            "source_url": source_url,
            "full_path": full_path,
            "content_type": content_type,
            "size": size,
            "updated_at": _utc_now_iso(),
        }
        with open(self.cache_dir / f"{key}.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=True, indent=2)

    def _evict_disk_cache_if_needed(self) -> None:
        if self.disk_cache_max_bytes <= 0:
            return

        metas = []
        total_size = 0
        for json_path in self.cache_dir.glob("*.json"):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    metas.append((json_path, meta))
                    total_size += meta.get("size", 0)
            except Exception:
                continue

        if total_size <= self.disk_cache_max_bytes:
            return

        metas.sort(key=lambda x: x[1].get("updated_at", ""))

        for json_path, meta in metas:
            if total_size <= self.disk_cache_max_bytes:
                break

            try:
                full_path = Path(meta.get("full_path", ""))
                if full_path.exists() and full_path.parent == self.cache_dir:
                    full_path.unlink()

                key = meta.get("key", "")
                if key:
                    for ext in [".json", ".lock", ".part"]:
                        p = self.cache_dir / f"{key}{ext}"
                        if p.exists():
                            p.unlink()

                total_size -= meta.get("size", 0)
            except Exception:
                pass
