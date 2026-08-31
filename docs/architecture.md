# 架构

## 设计目标

控制平面完整运行在 Home Assistant 内，自定义集成同时承担配置、Navidrome 访问、多语种索引、队列、语音事件、播放器状态同步和 Panel API。音频数据平面不经过 Home Assistant 或额外代理，而由小爱音箱直接从 Navidrome 的限时公开分享流读取。

```text
conversation sensor ──┐
HA service actions ───┼──> XiaoAI Navidrome integration
HA native Panel ──────┘          │
                                 ├── Config Entry secrets
                                 ├── .storage index and queue
                                 ├── state_changed listeners
                                 ├── optional HTTP embeddings
                                 └── Navidrome Subsonic + native API
                                               │
                                               └── temporary MP3 share
                                                        │
HA media_player.play_media <── /share/s/<signed-id> ─────┘
             │
             └──> XiaoAI speaker downloads from Navidrome
```

## Home Assistant 运行时

每个 Config Entry 创建一个运行时对象，其中包含 Navidrome 客户端、匹配索引和持久播放队列。集成清单限制为单一 Config Entry，从而使侧栏 Panel 和没有显式 `entry_id` 的服务动作具有确定目标。

| 生命周期阶段 | 行为 |
|---|---|
| `async_setup_entry` | 验证 Navidrome、恢复索引、恢复停止状态的队列、注册事件监听、启动后台同步 |
| Options 更新 | Home Assistant 重新加载 Config Entry；卸载旧运行时后用新参数重建 |
| Home Assistant 关闭或卸载 | 取消同步与计时任务，停止活动输出并尽力删除临时 share |
| Home Assistant 重启 | 恢复曲目、队列位置、随机与循环模式，但不自动恢复声音 |

长时间工作只包括可取消的后台曲库同步和当前歌曲的单次计时任务。集成不建立自有常驻 WebSocket、不轮询播放器，也不需要独立 webhook。

## Navidrome API 分工

Subsonic/OpenSubsonic API 使用 token 与 salt 鉴权，负责 ping、全曲库分页、搜索、歌单、曲目详情和封面。Navidrome 原生 API 使用短期 bearer token，负责创建和删除可指定 MP3 格式、最大码率与过期时间的分享。

Navidrome v0.63.2 的公共路由提供 `/share/s/{id}` 音频处理和 `/{id}/m3u` 播放列表。[1] 媒体文件分享按请求中的 `ResourceIDs` 顺序加载曲目，并为每首曲目生成带签名的公开流 ID。[2] [3]

队列首次播放或队列顺序变化时，集成为整组曲目创建一个分享并解析 M3U。API 地址与 `ND_SHAREURL` 不同时，Config Flow 可单独保存预期的公开 share base；M3U URL 必须与该 origin、有效端口和 base path 完全一致，位于 `/share/s/` 下，且不得包含查询参数、userinfo、fragment 或编码路径穿越。只要曲目 ID 顺序不变且分享剩余时间超过五分钟，上一首、下一首和跳转复用同一组 URL。活动 share 和待撤销 ID 都写入 private Store；替换队列、清空队列或关闭运行时时删除旧分享，临时失败则以一到六十分钟指数退避重试，并在重启后继续撤销。

## 曲库同步

曲库同步使用 Navidrome 支持的空查询 `search3` 分页扩展。同步期间继续使用旧索引，所有页面成功获取后才替换内存快照并持久化。空结果或新曲目数低于旧索引安全比例时拒绝覆盖，降低 Navidrome 扫描期间部分结果破坏旧索引的风险。

索引存入 Home Assistant `Store`，只包含曲目展示元数据、规范化检索键、可选 embedding 和内容指纹，不包含 Navidrome 密码、Subsonic token、用户查询或语音历史。模型标识和内容指纹均未变化时复用已有向量；新增和变更曲目才重新编码。

## 多语种检索

查询与曲目分别生成 Unicode NFKC、大小写折叠、简繁转换、完整拼音、日语读音、平假名、片假名和罗马字键。拼音、假名和罗马字是身份转写，只参与精确与字符距离比较；高分包含匹配仅允许原文与简繁等表面变体。索引明确不生成拼音首字母。

词法与语义通道分别评分。可选 embedding 用于无字符重合的跨语言召回，但不会覆盖强精确词法结果。自动播放同时受第一候选阈值和第一、第二候选分差约束；不满足时服务动作返回错误，语音路径记录脱敏警告且不播放。

## 队列一致性

队列变更由异步操作锁串行执行。Panel 命令携带 `expected_revision`，过期 revision 被拒绝；语音与 HA 原生服务不依赖浏览器 revision，但仍经过同一个锁。分享创建、`media_player.play_media` 调用、状态落盘和计时器更新处于同一串行操作中，避免停止与慢速分享请求交错后重新播放。

| 状态 | 含义 |
|---|---|
| `stopped` | 无自动推进任务；可以保留队列和当前位置 |
| `loading` | 正在创建或解析 share，并向 HA 播放器下发 URL |
| `playing` | 已下发当前 URL，并按元数据时长安排自动推进 |
| `error` | share、Navidrome 或 HA 服务调用失败；错误摘要写入队列状态 |

随机模式只洗牌尚未播放部分。单曲循环让自动推进保持当前项；列表循环在队尾回到队首。非传输型队列变更仍会按当前 `ends_at` 和新 revision 重建计时器，避免开启循环或追加歌曲后丢失自动推进。

## 播放器状态同步

运行时直接订阅 Home Assistant 全局 `state_changed`，但只处理当前队列所选 `media_player`。内部队列播放期间，实体进入 `paused`、`off`、`standby` 或 `unavailable` 时立即停止并取消计时器，不要求事件前态恰好为 `playing`，因此 `playing → buffering → paused` 也能正确终止。`idle` 可能是自然曲终，因此先排除预计结束前后三十秒窗口，再要求状态连续保持五秒。

事件时间必须不早于当前曲目 `started_at`。状态判断进入队列锁后会再次校验当前播放器、当前状态和事件时间，从而防止上一首曲目的延迟暂停事件停止刚开始的新曲目。

## Panel 与权限

集成注册一个管理员可见的 Home Assistant 侧栏 Panel。静态 JavaScript 和 CSS 由 HA HTTP 组件提供；数据与命令走自定义 WebSocket API，因此继承 HA 登录会话。每个 WebSocket 命令使用 `require_admin`，封面代理同样要求管理员。

Panel 不保存 Navidrome 密码、HA token 或独立 Panel Token。曲目文本通过 DOM `textContent` 写入，封面使用 HA 鉴权请求取得 Blob，并以有界对象 URL 缓存展示。

## 安全边界

| 边界 | 控制 |
|---|---|
| HA 到 Navidrome | TLS 验证默认开启；Config Flow 可显式关闭，仅适合可信网络 |
| Panel 到 HA | HA 已有登录会话、管理员 WebSocket 权限和管理员 HTTP 视图 |
| 音箱到 Navidrome | 限时分享 URL；不包含查询参数或账户凭据 |
| 持久数据 | Home Assistant private `Store`、原子写入；诊断排除敏感配置与曲库内容 |
| HTTP 响应 | JSON、M3U、封面和 embedding 均有响应体上限与请求超时 |
| 后台任务 | Config Entry unload 取消并等待任务；异常不会阻止 HA 关闭 |

分享 URL 是临时 bearer capability：即使没有查询参数，任何在有效期内获得完整 URL 的客户端都可访问对应媒体。因此应使用 HTTPS，不应把日志或 URL 公开到不受信任位置。

## References

[1]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/public.go "Navidrome v0.63.2 public share routes"
[2]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/handle_streams.go "Navidrome v0.63.2 shared stream handler"
[3]: https://github.com/navidrome/navidrome/blob/v0.63.2/persistence/share_repository.go "Navidrome v0.63.2 share media ordering"
[4]: https://developers.home-assistant.io/docs/config_entries_index/ "Home Assistant Config Entry lifecycle"
[5]: https://developers.home-assistant.io/docs/integration_listen_events/ "Home Assistant event subscriptions"
[6]: https://developers.home-assistant.io/docs/frontend/custom-ui/creating-custom-panels/ "Home Assistant custom panel development"
