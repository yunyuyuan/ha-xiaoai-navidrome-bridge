# Home Assistant 原生播放面板

“小爱音乐”页面由自定义集成直接注册到 Home Assistant 侧栏。它不是 iframe，也不依赖外部页面、独立令牌或 Home Assistant 长期访问令牌。

## 运行方式

Panel 的 JavaScript 和 CSS 由 Home Assistant 静态路径提供。浏览、搜索、歌单、队列和控制命令通过 Home Assistant WebSocket API 发送到同一 Config Entry。Home Assistant 自定义 Panel 可以获得标准 `hass` 前端对象，集成 WebSocket 命令则继承当前登录用户身份。[1] [2]

所有 Panel WebSocket 命令和封面 HTTP 代理均要求管理员权限。侧栏条目也以 `require_admin=true` 注册，因此普通用户不会看到或调用该控制界面。

## 页面组成

| 区域 | 功能 |
|---|---|
| 顶部状态 | 集成名称、索引同步状态、日/夜/跟随系统主题 |
| 播放队列 | 当前曲目、输出播放器、上一首、播放、停止、下一首、清空、随机和循环 |
| 曲库 | 本地索引分页、搜索、立即播放、下一首播放、加入队列和曲目详情 |
| 歌单 | Navidrome 歌单搜索、展开曲目，以及从指定曲目开始播放完整歌单 |
| 详情 | 封面、标题、歌手、专辑、时长、格式、码率、年份等可用元数据 |

在宽屏布局中，曲库位于左侧、队列位于右侧。单栏和移动端布局会把队列移到曲库上方，保证播放控制优先可见。

## 队列语义

| 操作 | 队列变化 | 是否立即播放 |
|---|---|---|
| 曲目“立即播放” | 清空并替换为所选曲目 | 是 |
| 曲目“下一首播放” | 插入当前指针之后 | 否 |
| 曲目“加入队列” | 追加到队尾 | 否 |
| 歌单曲目点击播放 | 用完整歌单替换，并把点击曲目旋转到第一项 | 是 |
| 队列曲目点击 | 顺序不变，只移动当前指针 | 是 |
| 上一首 / 下一首 | 按当前顺序移动指针 | 是 |
| 停止 | 保留曲目与指针 | 否；停止自动推进 |
| 清空 | 删除全部项目并停止输出 | 否 |
| 随机 | 洗牌尚未播放项目 | 保持当前播放 |
| 单曲循环 | 自动曲终后重新播放当前项 | 是 |
| 列表循环 | 队尾后回到队首；随机开启时重新洗牌 | 是 |

语音口令、Home Assistant 服务动作和 Panel 使用同一个后端队列。通过语音启动歌单后，Panel 会从 WebSocket 订阅实时收到队列状态；不需要轮询页面或刷新浏览器。

## 播放器选择

Panel 只列出同时支持以下能力的 `media_player`：

1. `MediaPlayerEntityFeature.PLAY_MEDIA`；
2. `PAUSE` 或 `STOP` 中至少一项。

选择保存到队列持久状态。活动播放期间切换输出设备时，集成先停止旧设备，再保存新选择；为避免无意跨设备继续播放，当前队列会进入停止状态，用户需要手工点击播放。

停止时优先调用 `media_pause`，不支持暂停时才调用 `media_stop`。这兼容只提供暂停、不提供停止的小爱媒体实体。

## 状态与并发

Panel 首次载入时读取队列快照，随后订阅实时队列事件。每个变更命令携带当前 `expected_revision`。如果语音、自动推进或另一个浏览器页面已经修改队列，服务端拒绝过期命令，Panel 获取最新状态后再允许后续操作。

客户端还会串行发送命令并忽略 revision 倒退的过期响应，避免快速点击造成响应乱序。关闭 Panel 不会终止后端队列或自动切歌。

## 封面与详情

浏览器不直接访问带 Subsonic 凭据的 Navidrome URL。Panel 使用 HA 鉴权封面代理，代理只接受有限长度的封面 ID，限制响应体大小，并向 Navidrome 请求适合界面的缩略图。浏览器将响应读取为 Blob，并用有界对象 URL 缓存减少重复请求。

所有曲目、歌手、专辑和错误文本均通过 DOM `textContent` 写入，不将 Navidrome 元数据作为 HTML 解析。

## 主题

主题模式保存在浏览器本地设置，可选：

| 模式 | 行为 |
|---|---|
| 跟随 Home Assistant | 使用当前 HA 深浅主题 |
| 日间 | 固定浅色面板 |
| 夜间 | 固定深色面板 |

主题只影响当前浏览器，不写入队列或 Home Assistant Config Entry。

## 故障排查

如果侧栏没有出现“小爱音乐”，先确认 Config Entry 已成功加载并以管理员账户登录。浏览器强制刷新可清理升级前缓存；静态资源 URL 包含集成版本，正常升级会自动换用新资源。

如果播放器列表为空，在开发者工具中检查目标实体的 `supported_features`。如果队列可以建立但音箱不播放，问题通常位于 Navidrome share 公网地址或反向代理 `/share/`，而不是 Panel WebSocket。

如果多页面操作出现 revision 冲突，这是安全拒绝而不是数据损坏；Panel 会自动刷新。持续冲突时关闭其他正在控制队列的页面或自动化。

## References

[1]: https://developers.home-assistant.io/docs/frontend/custom-ui/creating-custom-panels/ "Home Assistant custom panel development"
[2]: https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/ "Home Assistant frontend hass object and WebSocket API"
[3]: https://developers.home-assistant.io/docs/core/entity/media-player/ "Home Assistant media player entity features"
[4]: https://developers.home-assistant.io/docs/integration_listen_events/ "Home Assistant event subscriptions"
