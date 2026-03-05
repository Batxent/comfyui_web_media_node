# comfyui_web_media_node

ComfyUI custom nodes for simple, production-friendly media loading:

- Input a remote URL or local filename/path.
- Auto cache to disk (pull-through).
- Optional in-memory LRU cache for decoded tensors.
- Output ComfyUI `IMAGE`/`MASK` directly.

Chinese version: [README.zh-CN.md](README.zh-CN.md)
License: [MIT](LICENSE)
Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)
Code of conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## Features

- URL and local file support in one node.
- Disk cache with lock-based single-flight download.
- Optional memory cache with LRU + TTL.
- Cache metadata stored as JSON for inspection.

## Nodes

- `MediaPullThroughCacheAsset`
  - Input: `source_url` (URL or local filename/path), optional `asset_key`, `force_refresh`
  - Output: `filename`, `subfolder`, `full_path`, `cache_hit`
- `MediaLoadCachedImage`
  - Input: `full_path`, `memory_cache_enabled`, `memory_cache_max_items`, `memory_cache_ttl_seconds`
  - Output: `IMAGE`, `MASK`, `width`, `height`
- `MediaLoadImageFromURLWithCache`
  - Input: `source_url` (URL or local filename/path), optional `asset_key`, `force_refresh`, `memory_cache_enabled`, `memory_cache_max_items`, `memory_cache_ttl_seconds`
  - Output: `IMAGE`, `MASK`, `width`, `height`, `cache_hit`, `full_path`

## Install

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/your-username/comfyui_web_media_node.git
```

Restart ComfyUI.

## Configuration

- `MEDIA_CACHE_DIR`: cache root directory. Default: `<project>/cache`
- `MEDIA_CACHE_MAX_BYTES`: max download size per file. Default: `104857600`
- `MEDIA_CACHE_TIMEOUT_SECONDS`: HTTP timeout. Default: `15`
- `MEDIA_CACHE_LOCK_TIMEOUT_SECONDS`: lock wait timeout. Default: `10`
- `MEDIA_MEMORY_CACHE_ENABLED`: enable memory LRU cache. Default: `false`
- `MEDIA_MEMORY_CACHE_MAX_ITEMS`: max memory entries. Default: `64`
- `MEDIA_MEMORY_CACHE_TTL_SECONDS`: memory TTL. Default: `300`

## Memory Cache Behavior

- Scope: process-local (per ComfyUI worker process).
- Key: `full_path + file mtime + file size`.
- Eviction: LRU.
- Expiration: TTL.
- Node input values take precedence when `memory_cache_enabled=true`.

## Benchmark Template

Use this format in your repo once you collect numbers:

| Scenario | p50 (ms) | p95 (ms) | Notes |
|---|---:|---:|---|
| Cold URL load | TBD | TBD | download + decode |
| Warm disk cache | TBD | TBD | disk hit + decode |
| Warm memory cache | TBD | TBD | memory hit |

## Local Test

```bash
cd comfyui_web_media_node
python -m pytest -q
```

## Example

- Minimal workflow snippet: [`examples/workflow.example.json`](examples/workflow.example.json)
