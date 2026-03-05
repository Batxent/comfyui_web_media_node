from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from cache_service import PullThroughCacheService


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "image/png"):
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Type": content_type}

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._payload) - self._offset
        start = self._offset
        end = min(len(self._payload), start + n)
        self._offset = end
        return self._payload[start:end]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_pull_through_cache_hit(tmp_path, monkeypatch):
    calls = {"n": 0}

    def _fake_urlopen(_req, timeout=15):  # noqa: ARG001
        calls["n"] += 1
        return _FakeResponse(PNG_BYTES)

    monkeypatch.setattr("cache_service.urlopen", _fake_urlopen)
    svc = PullThroughCacheService(cache_dir=str(tmp_path))
    url = "https://cdn.example.com/image.png"

    first = svc.resolve(source_url=url, asset_key="agent_a")
    second = svc.resolve(source_url=url, asset_key="agent_a")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.full_path == second.full_path
    assert calls["n"] == 1


def test_pull_through_cache_force_refresh(tmp_path, monkeypatch):
    calls = {"n": 0}

    def _fake_urlopen(_req, timeout=15):  # noqa: ARG001
        calls["n"] += 1
        return _FakeResponse(PNG_BYTES)

    monkeypatch.setattr("cache_service.urlopen", _fake_urlopen)
    svc = PullThroughCacheService(cache_dir=str(tmp_path))
    url = "https://cdn.example.com/image.png"

    first = svc.resolve(source_url=url, asset_key="agent_b")
    second = svc.resolve(source_url=url, asset_key="agent_b", force_refresh=True)

    assert first.cache_hit is False
    assert second.cache_hit is False
    assert first.filename == second.filename
    assert calls["n"] == 2


def test_resolve_local_absolute_file(tmp_path):
    local = tmp_path / "local.png"
    local.write_bytes(PNG_BYTES)
    svc = PullThroughCacheService(cache_dir=str(tmp_path / "cache"))

    out = svc.resolve(source_url=str(local))
    assert out.cache_hit is True
    assert out.filename == "local.png"
    assert out.full_path == str(local.resolve())


def test_resolve_local_filename_in_cache_dir(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / "foo.png"
    local.write_bytes(PNG_BYTES)
    svc = PullThroughCacheService(cache_dir=str(cache_dir))

    out = svc.resolve(source_url="foo.png")
    assert out.cache_hit is True
    assert out.filename == "foo.png"
    assert out.full_path == str(local.resolve())
