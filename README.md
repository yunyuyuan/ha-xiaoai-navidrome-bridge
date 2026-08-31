# XiaoAI Navidrome for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://www.hacs.xyz/)
[![Home Assistant 2026.8+](https://img.shields.io/badge/Home%20Assistant-2026.8%2B-18BCF2.svg)](https://www.home-assistant.io/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**XiaoAI Navidrome** 是一个通过 HACS 安装的 Home Assistant 自定义集成。它让小爱音箱播放 Navidrome 单曲与歌单，同时在 Home Assistant 侧栏提供完整的曲库、播放队列和输出设备控制。

Home Assistant 直接承担配置、索引、队列、语音事件和播放器状态同步；**不需要独立服务容器、Home Assistant 长期访问令牌、REST YAML 或额外反向代理路由**。集成使用 Navidrome 原生限时分享流，把不含查询参数和 Subsonic 凭据的公开音频 URL 下发给音箱。Navidrome v0.63.2 已提供 `/share/s/<signed-id>` 公开流与 Range 处理。[1] [2]

## 功能

| 能力 | 实现 |
|---|---|
| HACS 与 UI 配置 | Config Flow、重新认证和 Options Flow；无需手写 secrets 或 YAML |
| 单曲与歌单 | Home Assistant 原生服务动作、语音口令和侧栏 Panel 共用同一队列 |
| 音频 URL | Navidrome 原生限时 MP3 分享流；URL 无 `?`、`&`、用户名、salt 或 Subsonic token |
| 持久队列 | Home Assistant `.storage` 持久化；重启后恢复内容但保持停止状态 |
| 队列控制 | 上一首、下一首、停止、清空、跳转、插入下一首、追加、随机、单曲循环、列表循环 |
| 状态同步 | 直接监听 HA `state_changed`；外部暂停或停止后立即取消自动切歌，不轮询、不使用长连接或 webhook |
| 多语种匹配 | NFKC、大小写、简繁、中文全拼、日文读音、假名、罗马字和字符距离 |
| 防误播 | 低置信度和候选分差不足时拒绝自动播放 |
| 可选语义匹配 | 支持 Ollama 与 OpenAI 兼容 Embedding；模型故障时自动退化为词法匹配 |
| 原生 Panel | 日/夜主题、响应式布局、封面、详情、歌单、队列和动态播放器选择 |
| 权限边界 | Panel、WebSocket 命令、原生服务动作和封面代理均仅允许 Home Assistant 管理员访问 |

## 架构

```text
小爱 conversation 传感器 ──state_changed──┐
Home Assistant 原生服务动作 ───────────────┼──> HACS 集成
HA 侧栏 Panel ──鉴权 WebSocket────────────┘       │
                                                   ├── 本地多语种索引
                                                   ├── HA .storage 持久队列
                                                   ├── 可选 Ollama / OpenAI Embedding
                                                   └── Navidrome API 创建限时 MP3 share
                                                              │
HA media_player.play_media <── 无查询参数 share URL ───────────┘
             │
             └──> 小爱音箱直接从 Navidrome `/share/s/...` 拉取音频
```

Panel 通过 Home Assistant 已有登录会话调用集成 WebSocket 命令，不接触 Navidrome 密码。音箱只获得当前队列对应的限时分享能力 URL。完整设计见 [`docs/architecture.md`](docs/architecture.md)。

## 前提条件

| 组件 | 要求 |
|---|---|
| Home Assistant | **2026.8.0 或更高版本** |
| 安装方式 | 已安装 HACS；也可手工复制 `custom_components/xiaoai_navidrome` |
| Navidrome | **v0.63.2 或更高版本**，可从 Home Assistant 访问 |
| Navidrome 分享 | `EnableSharing=true`；官方默认开启。反向代理必须允许 `/share/` [3] |
| 分享公网地址 | 音箱必须能访问 Navidrome 生成的 share URL；内外地址不同需配置 `ND_SHAREURL`，并在集成中填写相同“对外分享地址” [4] |
| 播放实体 | 支持 `media_player.play_media`，并支持 `media_pause` 或 `media_stop` |
| 语音实体 | 可选；由米家集成提供、状态值包含小爱识别文本的 conversation `sensor` |

建议为本集成创建独立的普通 Navidrome 用户，只授予需要播放的媒体库权限。Navidrome 分享继承创建者的媒体库访问范围。[3]

## 安装

### 1. 通过 HACS 下载

在 HACS 中打开 **集成 → 右上角菜单 → 自定义存储库**，填入：

```text
https://github.com/yunyuyuan/ha-xiaoai-navidrome-bridge
```

类别选择 **Integration**，下载最新版本并重启 Home Assistant。HACS 自定义集成仓库要求运行文件位于唯一的 `custom_components/<domain>/` 目录，本仓库遵循该结构。[5]

手工安装时，将 `custom_components/xiaoai_navidrome` 完整复制到：

```text
/config/custom_components/xiaoai_navidrome
```

然后重启 Home Assistant。

### 2. 在 Home Assistant 中添加集成

进入 **设置 → 设备与服务 → 添加集成 → XiaoAI Navidrome**。安装向导分两步完成全部配置：

| 步骤 | 内容 |
|---|---|
| Navidrome 连接 | API 服务地址、可选对外分享地址、用户名、密码、TLS 证书验证 |
| 播放与匹配 | 默认小爱播放器、可选 conversation 传感器、语音前缀、队列参数和可选 Embedding |

连接验证会检查 Subsonic 鉴权、Navidrome 原生登录，以及在非空曲库中创建并删除一次五分钟测试 share。配置完成后，集成在后台同步曲库；刷新期间当前索引仍可使用。

Navidrome 通过反向代理公开时，建议填写音箱也能访问的 HTTPS 地址，例如：

```text
https://music.example.com
```

如果 Home Assistant 访问 Navidrome 的内部地址与音箱访问地址不同，请在 Navidrome 中设置：

```text
ND_SHAREURL=https://music.example.com
```

同时在 Config Flow 第一页的 **Navidrome 对外分享地址** 填写同一地址。集成始终通过内部 API 地址完成鉴权、曲库访问、share 创建和 M3U 获取，只把经过严格校验的公开 `/share/s/` 音频地址发给音箱。确认反向代理放行 `/share/`。

### 3. 首次检查

重启后打开侧栏 **小爱音乐**。在 Panel 顶部确认连接状态，在队列卡片选择输出音箱，并点击 **同步曲库**。如果配置时已经选择播放器，Panel 会直接显示该选择。

## 使用

### 原生侧栏 Panel

Panel 支持曲库和歌单分页、搜索、封面与详情、随机、循环和完整队列控制。移动端把播放队列放在曲库上方；主题可以跟随 Home Assistant，也可固定为日间或夜间。

| Panel 操作 | 行为 |
|---|---|
| 立即播放曲目 | 用该曲目替换队列并播放 |
| 下一首播放 | 插入到当前曲目之后 |
| 加入队列 | 追加到队尾 |
| 点击歌单内曲目 | 用完整歌单替换队列，并把所点曲目旋转到队首 |
| 点击队列曲目 | 不改变队列顺序，只切换当前指针并播放 |
| 停止 | 暂停或停止音箱，保留队列和当前位置 |
| 清空 | 停止音箱并删除整个队列 |

队列与索引由 Home Assistant 后端持有，关闭浏览器不会中断自动切歌。队列操作带 revision 乐观并发控制，过期的 Panel 命令会刷新状态而不是覆盖其他页面或语音刚完成的修改。

### 语音口令

在 Config Flow 中选择 conversation 传感器后，不需要自动化 YAML。默认识别以下口令：

```text
小爱同学，播放家庭音乐<曲目名称><歌手名称>
小爱同学，播放家庭歌单<歌单名称>
小爱同学，上一首家庭音乐
小爱同学，家庭音乐上一首
小爱同学，下一首家庭音乐
小爱同学，家庭音乐下一首
小爱同学，停止家庭音乐
小爱同学，家庭音乐停止
```

单曲、歌单、Panel 和服务动作共用同一个 Home Assistant 队列，因此语音启动歌单后会立即同步到 Panel，上一首、下一首和停止也控制同一状态。集成优先用 conversation timestamp、conversation ID 或 sequence 对事件去重；传感器不提供事件标识时才使用五秒文本窗口。新事件即使文本相同也可立即执行，旧事件的属性刷新不会重复点歌。

如果实体状态文本包含额外标点或礼貌词，集成会从最后一个配置的口令前缀之后提取查询。可以在 **设备与服务 → XiaoAI Navidrome → 配置** 中修改两个前缀。

### Home Assistant 服务动作

集成注册以下原生动作，可在自动化、脚本和开发者工具中使用：

| 动作 | 参数 | 返回 |
|---|---|---|
| `xiaoai_navidrome.play` | `query`，可选 `media_player` | 匹配详情和队列状态 |
| `xiaoai_navidrome.play_playlist` | `query`，可选 `media_player` | 歌单匹配和队列状态 |
| `xiaoai_navidrome.previous` | 无 | 队列状态 |
| `xiaoai_navidrome.next` | 无 | 队列状态 |
| `xiaoai_navidrome.stop` | 无 | 队列状态 |
| `xiaoai_navidrome.clear_queue` | 无 | 队列状态 |
| `xiaoai_navidrome.sync_library` | 无 | 索引状态 |

这些全局动作按 Home Assistant 管理员服务注册。无用户 context 的 HA 内部自动化仍可调用；普通非管理员账户不能通过通用 WebSocket 绕过 Panel 权限。

示例：

```yaml
action: xiaoai_navidrome.play
data:
  query: "Synthetic Track Example Artist"
```

## 多语种匹配

每首曲目建立原始元数据、Unicode NFKC、简繁转换、完整拼音、日文读音、平假名、片假名和罗马字检索键。**不会生成拼音首字母**。转写键只参与身份精确与字符距离匹配，不参与高分子串包含，从而降低短字符串碰撞。

无字符重合的跨语言关系由可选 Embedding 独立处理。语义相似度不能覆盖强精确词法命中；第一名分数或候选分差不足时，集成拒绝自动播放。模型不可用时，查询继续使用词法索引。模型名与曲目文档未变化时，同步会复用原有向量，只编码新增或变更曲目。

Ollama、Qwen3 Embedding 和低功耗 NAS 配置见 [`docs/local-model-research.md`](docs/local-model-research.md)。Embedding 不是必要组件，建议先用默认词法索引验证完整播放链路。

## 状态同步与自动切歌

自动切歌依据 Navidrome 曲目时长加配置的曲间缓冲。集成直接监听 Home Assistant `state_changed` 事件；内部队列播放期间，目标播放器进入 `paused`、`off`、`standby` 或 `unavailable` 时立即停止队列计时器，即使中间短暂经过 `buffering` 也不会漏掉。较容易出现在自然曲终的 `idle` 会经过五秒确认，并在预计曲终附近被忽略，避免干扰正常下一首。

这种机制没有轮询、Bridge webhook 或额外长连接。它只处理当前队列所选播放器，并以当前曲目启动时间排除过期状态事件。

## 安全模型

| 数据或接口 | 边界 |
|---|---|
| Navidrome 密码 | 只保存在 Home Assistant Config Entry；诊断会脱敏 |
| Subsonic token 与 salt | 只用于 HA 到 Navidrome 的请求，不发送到 Panel 或音箱 |
| Panel WebSocket | 使用 HA 登录会话并要求管理员权限 |
| 封面 | 经 HA 鉴权代理，限制响应大小；浏览器不获得 Navidrome 凭据 |
| 音频 share URL | 限时公开能力 URL；无查询参数，但在过期前持有者可访问 |
| 队列和索引 | 保存在 HA `.storage`；不包含 Navidrome 密码或语音历史 |

集成把活动和待撤销的 share ID 写入 private HA Store；替换队列、清空队列或卸载时删除不再使用的 Navidrome share。临时删除失败会在运行期指数退避重试，异常关机后下次加载继续撤销。无法恢复的 share 仍会在默认六小时有效期结束后失效。不要把正在有效期内的 share URL 发布到不受信任的位置。

## 故障排查

| 现象 | 优先检查 |
|---|---|
| Config Flow 提示无法连接 | Navidrome 地址、容器网络、TLS 证书和普通用户凭据 |
| 提示响应无效 | Navidrome 版本、分享功能和反向代理 `/share/` 路由 |
| Panel 有队列但音箱无声 | 音箱能否访问 `ND_SHAREURL` 生成的地址；播放器是否支持 URL `play_media` |
| 暂停后仍自动下一首 | HA 中该实体是否真的从 `playing` 变为 `paused/off/standby`；下载集成诊断并检查实体 ID |
| 曲库新增后未出现 | 等待刷新周期，或调用 `xiaoai_navidrome.sync_library` / Panel 的“同步曲库” |
| Embedding 数量不增加 | Ollama 模型是否已拉取、URL 是否可从 HA 访问；模型失败不影响词法同步 |
| 语音无反应 | conversation 传感器当前状态、配置的口令前缀、HA 日志中的集成警告 |

在 **设置 → 设备与服务 → XiaoAI Navidrome → 下载诊断** 获取脱敏状态。诊断不包含密码、API Key、曲目元数据、查询文本或语音记录。

## 开发与发布

本仓库只包含一个 HACS integration。运行 `make setup` 创建测试环境，运行 `make check` 执行 Ruff、Mypy、Home Assistant 2026.8.3 测试、前端语法和 Node 单元测试。HACS 与 Hassfest 另外在 GitHub Actions 中验证。发布规则见 [`docs/releasing.md`](docs/releasing.md)。

## References

[1]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/public.go "Navidrome v0.63.2 public share routes"
[2]: https://github.com/navidrome/navidrome/blob/v0.63.2/server/public/handle_streams.go "Navidrome v0.63.2 public shared stream handler"
[3]: https://www.navidrome.org/docs/usage/features/sharing/ "Navidrome sharing feature documentation"
[4]: https://www.navidrome.org/docs/usage/configuration/options/ "Navidrome configuration options"
[5]: https://www.hacs.xyz/docs/publish/integration/ "HACS integration repository requirements"
[6]: https://developers.home-assistant.io/docs/config_entries_config_flow_handler/ "Home Assistant Config Flow documentation"
[7]: https://developers.home-assistant.io/docs/integration_listen_events/ "Home Assistant event subscription documentation"
