# comfyui_web_media_node

这是一个 ComfyUI 自定义节点项目，专注于提供简单、可用于生产的媒体加载能力：

- 输入远程 URL 或本地文件名/路径。
- 自动做磁盘缓存（pull-through）。
- 可选内存 LRU 缓存（缓存解码后的 tensor）。
- 直接输出 ComfyUI `IMAGE`/`MASK`。

English version: [README.md](README.md)
许可证: [MIT](LICENSE)
贡献指南: [CONTRIBUTING.md](CONTRIBUTING.md)
行为准则: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 功能

- 一个节点同时支持 URL 和本地文件输入。
- 磁盘缓存，带锁避免并发重复下载。
- 可选内存缓存（LRU + TTL）。
- 缓存元数据写入 JSON，便于排查。

## 节点

- `MediaPullThroughCacheAsset`
  - 输入：`source_url`（URL 或本地文件名/路径）、可选 `asset_key`、`force_refresh`
  - 输出：`filename`, `subfolder`, `full_path`, `cache_hit`
- `MediaLoadCachedImage`
  - 输入：`full_path`, `memory_cache_enabled`, `memory_cache_max_items`, `memory_cache_ttl_seconds`
  - 输出：`IMAGE`, `MASK`, `width`, `height`
- `MediaLoadImageFromURLWithCache`
  - 输入：`source_url`（URL 或本地文件名/路径）、可选 `asset_key`、`force_refresh`、`memory_cache_enabled`、`memory_cache_max_items`、`memory_cache_ttl_seconds`
  - 输出：`IMAGE`, `MASK`, `width`, `height`, `cache_hit`, `full_path`

## 安装

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/your-username/comfyui_web_media_node.git
```

重启 ComfyUI。

## 配置

- `MEDIA_CACHE_DIR`：磁盘缓存目录，默认 `<project>/cache`
- `MEDIA_CACHE_MAX_BYTES`：单文件最大下载大小，默认 `104857600`
- `MEDIA_CACHE_TIMEOUT_SECONDS`：HTTP 超时秒数，默认 `15`
- `MEDIA_CACHE_LOCK_TIMEOUT_SECONDS`：锁等待超时秒数，默认 `10`
- `MEDIA_MEMORY_CACHE_ENABLED`：是否开启内存 LRU 缓存，默认 `false`
- `MEDIA_MEMORY_CACHE_MAX_ITEMS`：内存缓存最大条目，默认 `64`
- `MEDIA_MEMORY_CACHE_TTL_SECONDS`：内存缓存 TTL，默认 `300`

## 内存缓存行为

- 作用域：进程内（每个 ComfyUI worker 独立）。
- Key：`full_path + file mtime + file size`。
- 淘汰：LRU。
- 过期：TTL。
- 当 `memory_cache_enabled=true` 时，节点输入参数优先于环境变量。

## 性能基准模板

建议按下面格式补充你们实测数据：

| 场景 | p50 (ms) | p95 (ms) | 备注 |
|---|---:|---:|---|
| 首次 URL 加载 | TBD | TBD | 下载 + 解码 |
| 磁盘缓存命中 | TBD | TBD | 磁盘读 + 解码 |
| 内存缓存命中 | TBD | TBD | 直接命中 |

## 本地测试

```bash
cd comfyui_web_media_node
python -m pytest -q
```

## 示例

- 最小工作流片段：[`examples/workflow.example.json`](examples/workflow.example.json)
