# Local Multilingual Embedding Configuration

Embeddings are an optional retrieval channel. Simplified and Traditional Chinese, full Pinyin, Japanese pronunciations, kana, romanization, and character-distance indexing do not depend on a model. First validate the playback path with embeddings disabled, then enable semantic matching as needed.

## Recommended Models

For a low-power Intel N5095 system with 16 GB of memory, **Qwen3-Embedding-0.6B** is the default recommendation. The official model supports multilingual text retrieval and has a GGUF release suitable for local deployment. [1] [2]

| Option | Characteristics | Recommended use |
|---|---|---|
| Lexical index only | Lowest resource use, explainable results, and no external service | Default starting point |
| Qwen3-Embedding-0.6B | Strong cross-language retrieval at a moderate model size | Preferred semantic option for N5095/16 GB |
| multilingual-e5-small | 384 dimensions and lower resource use, with fixed prefix and pooling conventions | Evaluate when resources are more constrained |
| BGE-M3 | Strong retrieval capability with higher compute and memory cost | More capable hosts |

## Enable in Home Assistant

Open **Settings → Devices & services → XiaoAI Navidrome → Configure** and set the following values.

| Field | Recommended Ollama value |
|---|---|
| Enable semantic matching | Enabled |
| Embedding provider | `ollama` |
| Embedding server URL | `http://<OLLAMA_LAN_ADDRESS>:11434` |
| Embedding model | `qwen3-embedding:0.6b` |
| Embedding API key | Leave blank |
| Embedding score weight | `0.35` |
| Semantic autoplay minimum score | `0.60` |
| Semantic autoplay minimum margin | `0.05` |

Saving reloads the Config Entry. Call `xiaoai_navidrome.sync_library` or select **Sync library** in the Panel. The new index generates embeddings for tracks that do not yet have valid vectors. Existing vectors are reused when the model name and track document are unchanged; the entire library is not re-encoded on every synchronization.

The Home Assistant container must be able to access the configured address. If Ollama and Home Assistant run on the same Docker host but not on the same user-defined network, do not use `localhost`. Use a host address accessible from the Home Assistant network namespace, or add both containers to the same Docker network.

## Ollama Setup

Pull the model first:

```bash
ollama pull qwen3-embedding:0.6b
```

Verify the API:

```bash
curl http://127.0.0.1:11434/api/embed \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-embedding:0.6b","input":["synthetic music query"]}'
```

The response should contain an `embeddings` array. The integration uses batched `/api/embed` requests, with a size limit and timeout for each HTTP response. If the model fails, the usable lexical index is retained rather than causing the integration to fail to load.

## Intel N5095 / Jasper Lake iGPU

Ollama's Intel Vulkan support and actual performance depend on the version, driver, and model. The container must at least map `/dev/dri` and allow access to `renderD128`. Add the following to the existing Ollama Compose service:

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

If the GID that owns host `/dev/dri/renderD128` is not among the container user's supplementary groups, add that numeric GID with `group_add`. Do not determine whether acceleration is enabled from a single `intel_gpu_top` sample. Check both Ollama logs and an actual embedding request:

```bash
docker logs <ollama-container> 2>&1 | \
  grep -Ei 'Vulkan|integrated GPU|offloaded|fallback|error'

docker exec <ollama-container> ollama ps
```

A successful path commonly shows Vulkan-backend or offload-related logs and no longer reports that the integrated GPU was discarded. The CPU still handles scheduling and some operators, so CPU utilization will not fall to zero while the GPU is working.

The N5095 iGPU is small. Vulkan may primarily reduce CPU peaks rather than total execution time. After the initial full-library synchronization, routine queries encode only one short text. Decide whether to retain GPU use through measured query latency, total-system power consumption, and stability.

## OpenAI-Compatible Interface

With the `openai` provider, the integration calls `/v1/embeddings` using the standard `input` and `model` fields, and sends bearer authentication after an API key is configured. This is suitable for llama.cpp and other compatible servers.

When Qwen3 Embedding is deployed through llama.cpp, use embedding mode and the pooling method required by the model:

```bash
llama-server \
  -m Qwen3-Embedding-0.6B-Q8_0.gguf \
  --embedding \
  --pooling last \
  --host 0.0.0.0 \
  --port 8080
```

Configure Home Assistant as follows.

| Field | Example |
|---|---|
| Embedding provider | `openai` |
| Embedding server URL | `http://<SERVER_LAN_ADDRESS>:8080` |
| Embedding model | `Qwen3-Embedding-0.6B` |
| Embedding API key | Enter a value only when the server requires bearer authentication |

## Thresholds

The Options Flow exposes five parameters.

| Parameter | Default | Purpose |
|---|---:|---|
| Lexical autoplay minimum score | `0.72` | Minimum lexical confidence for the first candidate |
| Lexical autoplay minimum margin | `0.08` | Minimum difference between the first and second candidates |
| Embedding score weight | `0.35` | Semantic-channel weight in hybrid ranking |
| Semantic autoplay minimum score | `0.60` | Minimum cosine score for semantic-only autoplay |
| Semantic autoplay minimum margin | `0.05` | Minimum difference between the first candidate and other semantic candidates |

Do not lower both the minimum score and the score gap solely to increase the success rate. Retain synthetic public tests, use a private labeled set that is not committed to the repository, measure false-autoplay rate, rejection rate, Recall@1, MRR, and query p95, then make small adjustments.

## Privacy and Logging

The index is stored in Home Assistant `.storage` and contains track metadata and vectors. Apply the access controls and backup policy used for the Home Assistant configuration directory. The embedding API receives structured track metadata and the current user query; accept this data boundary before using a remote service. This project's diagnostics and logs do not emit complete queries, track lists, vectors, passwords, or API keys.

## References

[1]: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B "Qwen3-Embedding-0.6B model card"
[2]: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF "Qwen3-Embedding-0.6B GGUF model card"
[3]: https://huggingface.co/intfloat/multilingual-e5-small "multilingual-e5-small model card"
[4]: https://huggingface.co/BAAI/bge-m3 "BGE-M3 model card"
[5]: https://docs.ollama.com/gpu "Ollama GPU documentation"
[6]: https://github.com/ollama/ollama/blob/main/envconfig/config.go "Ollama environment configuration source"
