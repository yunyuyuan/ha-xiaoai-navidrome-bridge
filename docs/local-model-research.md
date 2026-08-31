# 本地多语种 Embedding 配置

Embedding 是可选召回通道。简繁、完整拼音、日语读音、假名、罗马字和字符距离索引不依赖模型；先关闭 Embedding 完成播放链路验收，再按需要启用语义匹配。

## 推荐模型

对于低功耗 Intel N5095 与 16 GB 内存，默认建议 **Qwen3-Embedding-0.6B**。官方模型支持多语言文本检索，并提供适合本地部署的 GGUF 版本。[1] [2]

| 方案 | 特点 | 建议用途 |
|---|---|---|
| 仅词法索引 | 占用最低、结果可解释、无外部服务 | 默认起点 |
| Qwen3-Embedding-0.6B | 跨语言召回较强，模型规模适中 | N5095/16 GB 首选语义方案 |
| multilingual-e5-small | 384 维、资源更低，但有固定前缀和 pooling 约定 | 资源更紧张时评估 |
| BGE-M3 | 召回能力强，计算与内存成本更高 | 更强主机 |

## 在 Home Assistant 中启用

进入 **设置 → 设备与服务 → XiaoAI Navidrome → 配置**，设置：

| 字段 | Ollama 建议值 |
|---|---|
| 启用语义匹配 | 开启 |
| Embedding 服务类型 | `ollama` |
| Embedding 服务地址 | `http://<OLLAMA_LAN_ADDRESS>:11434` |
| Embedding 模型 | `qwen3-embedding:0.6b` |
| Embedding API 密钥 | 留空 |
| Embedding 分数权重 | `0.35` |
| 语义自动播放最低分 | `0.60` |
| 语义自动播放最小分差 | `0.05` |

保存后 Config Entry 会重载。调用 `xiaoai_navidrome.sync_library` 或在 Panel 点击“同步曲库”，新索引会为尚无有效向量的曲目生成 embedding。模型名和曲目文档未变化时复用已有向量，不会因每次同步重新编码全部曲库。

Home Assistant 容器必须能访问填写的地址。Ollama 与 HA 在同一 Docker 主机但不在同一用户网络时，不要填写 `localhost`；应使用可从 Home Assistant 网络命名空间访问的主机地址或把两个容器加入同一 Docker 网络。

## Ollama 准备

先拉取模型：

```bash
ollama pull qwen3-embedding:0.6b
```

验证 API：

```bash
curl http://127.0.0.1:11434/api/embed \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-embedding:0.6b","input":["synthetic music query"]}'
```

响应应包含 `embeddings` 数组。集成使用批量 `/api/embed`，每次 HTTP 响应有大小上限和超时；模型故障时保留可用词法索引，而不是让集成加载失败。

## Intel N5095 / Jasper Lake iGPU

Ollama 的 Intel Vulkan 支持和实际性能取决于版本、驱动和模型。容器至少需要映射 `/dev/dri`，并允许访问 `renderD128`。可在现有 Ollama Compose 服务中加入：

```yaml
services:
  ollama:
    devices:
      - /dev/dri:/dev/dri
    environment:
      OLLAMA_VULKAN: "1"
      OLLAMA_IGPU_ENABLE: "1"
      GGML_VK_VISIBLE_DEVICES: "0"
```

宿主机 `/dev/dri/renderD128` 所属 GID 若不在容器用户附加组中，还需用 `group_add` 加入对应数字 GID。不要凭 `intel_gpu_top` 单次采样判断是否启用；结合 Ollama 日志和一次实际 embedding 请求检查：

```bash
docker logs <ollama-container> 2>&1 | \
  grep -Ei 'Vulkan|integrated GPU|offloaded|fallback|error'

docker exec <ollama-container> ollama ps
```

成功路径通常会出现 Vulkan backend 或 offload 相关日志，并且不再提示丢弃集成 GPU。CPU 仍负责调度和部分算子，因此 GPU 工作时 CPU 不会降到零。

N5095 iGPU 规模较小，Vulkan 可能主要降低 CPU 峰值，而不一定缩短总耗时。首次全库同步完成后，日常查询只编码一条短文本；是否保留 GPU 应以查询延迟、整机功耗和稳定性实测决定。

## OpenAI 兼容接口

选择 `openai` provider 时，集成调用 `/v1/embeddings`，使用标准 `input` 与 `model` 字段，并在配置 API Key 后发送 bearer 认证。适用于 llama.cpp 或其他兼容服务器。

Qwen3 Embedding 通过 llama.cpp 部署时应按模型要求使用 embedding 模式和正确 pooling：

```bash
llama-server \
  -m Qwen3-Embedding-0.6B-Q8_0.gguf \
  --embedding \
  --pooling last \
  --host 0.0.0.0 \
  --port 8080
```

Home Assistant 中配置：

| 字段 | 示例 |
|---|---|
| Embedding 服务类型 | `openai` |
| Embedding 服务地址 | `http://<SERVER_LAN_ADDRESS>:8080` |
| Embedding 模型 | `Qwen3-Embedding-0.6B` |
| API 密钥 | 仅服务器要求 bearer 认证时填写 |

## 阈值说明

Options Flow 暴露五个参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| 词法自动播放最低分 | `0.72` | 第一候选最低词法置信度 |
| 词法自动播放最小分差 | `0.08` | 第一与第二候选最低差值 |
| Embedding 分数权重 | `0.35` | 混合排序中语义通道权重 |
| 语义自动播放最低分 | `0.60` | 纯语义自动播放最低余弦分 |
| 语义自动播放最小分差 | `0.05` | 第一与其他语义候选最低差值 |

不要只为提高成功率而同时降低最低分和分差。合理方法是保留合成公开测试，使用不提交仓库的私有标注集统计错误自动播放率、拒绝率、Recall@1、MRR 和查询 p95，再小步调整。

## 隐私与日志

索引保存在 Home Assistant `.storage`，包含曲目元数据和向量，因此应沿用 HA 配置目录的访问控制与备份策略。Embedding API 会接收结构化曲目元数据和用户当前查询；使用远端服务前需接受这一数据边界。本项目诊断与日志不输出完整查询、曲目列表、向量、密码或 API Key。

## References

[1]: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B "Qwen3-Embedding-0.6B model card"
[2]: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF "Qwen3-Embedding-0.6B GGUF model card"
[3]: https://huggingface.co/intfloat/multilingual-e5-small "multilingual-e5-small model card"
[4]: https://huggingface.co/BAAI/bge-m3 "BGE-M3 model card"
[5]: https://docs.ollama.com/gpu "Ollama GPU documentation"
[6]: https://github.com/ollama/ollama/blob/main/envconfig/config.go "Ollama environment configuration source"
