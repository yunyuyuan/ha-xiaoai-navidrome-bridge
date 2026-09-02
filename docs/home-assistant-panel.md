# Home Assistant 原生播放面板

侧栏播放页面由自定义集成直接注册到 Home Assistant。它不是 iframe，也不依赖外部页面、独立令牌或 Home Assistant 长期访问令牌。

## 运行方式

Panel 的 JavaScript 和 CSS 由 Home Assistant 静态路径提供。浏览、搜索、歌单、队列和控制命令通过 Home Assistant WebSocket API 发送到同一 Config Entry。Home Assistant 自定义 Panel 可以获得标准 `hass` 前端对象，集成 WebSocket 命令则继承当前登录用户身份。[1] [2]

所有 Panel WebSocket 命令和封面 HTTP 代理均要求管理员权限。侧栏条目也以 `require_admin=true` 注册，因此普通用户不会看到或调用该控制界面。

## 侧栏管理

该页面是集成注册的原生 `panel_custom`，不是 Lovelace 仪表盘，因此不出现在 Home Assistant 的“仪表盘”管理页。管理员可进入 **设置 → 设备与服务 → XiaoAI Navidrome → 配置**，修改 **侧栏和页面名称**，或关闭 **显示侧栏面板**。名称会同时用于侧栏条目和页面标题。关闭开关只注销侧栏入口；集成运行时、语音口令、服务动作、持久队列和自动切歌保持运行。重新打开开关会在配置重载后恢复入口。

## 页面组成

| 区域 | 功能 |
|---|---|
| 顶部状态 | 移动端 Home Assistant 侧栏菜单、集成名称、索引同步状态、日/夜/跟随系统主题 |
| 播放器 | 旋转 CD、当前曲目、进度、上一首、播放/暂停、下一首、三态播放模式、音量和静音 |
| 播放队列 | 输出播放器、可跳转的曲目队列和图标式清空操作 |
| 曲库 | 标签顺序为歌单、曲目，默认打开歌单；曲目支持本地索引分页和搜索，点击封面、标题或元数据区域可立即播放 |
| 歌单 | Navidrome 歌单搜索；桌面端点击整张封面卡片、移动端点击无封面的紧凑列表行进入曲目列表，点击歌单曲目的主体区域从该曲目开始播放完整歌单 |
| 详情 | 封面、标题、歌手、专辑、时长、格式、码率、年份等可用元数据 |

在宽屏双栏布局中，曲库位于左侧、队列位于右侧；右侧队列面板使用 `position: sticky` 和 `top: 12px`，页面滚动时持续保留播放器控制。宽度不超过 `1050px` 的单栏布局以及 Home Assistant 标记的窄屏布局会显式恢复 `position: static`，并把队列移到曲库上方。移动端歌单使用单列文本行；首次窄屏渲染不创建歌单封面节点，从宽屏切换到窄屏时则原位重绘曲库并移除已有封面节点。窄屏标题左侧显示菜单按钮并派发原生 `hass-toggle-menu` 事件；kiosk 模式保持隐藏。[8] [9]

## 首页仪表盘控制

集成不注册额外 Lovelace 前端资源。首页的暂停、恢复、上一首和下一首可以用 Home Assistant 原生按钮卡片直接调用 `xiaoai_navidrome.pause`、`xiaoai_navidrome.resume`、`xiaoai_navidrome.previous` 和 `xiaoai_navidrome.next`。

动态歌单入口使用标准 `SelectEntity`。实体的 `options` 来自运行时短时歌单缓存，普通属性读取只访问内存；首次添加实体及显式更新时才通过运行时刷新缓存，符合 Home Assistant 的实体规范。[10] 并发刷新由单飞锁合并，旧请求不能反向覆盖较新的名称映射。每个显示名称映射到精确歌单 ID；重复名称增加稳定序号，ID 不暴露为实体选项。选择后调用与 Panel 相同的 `async_add_playlist(..., "replace")`，因此共享同一持久队列、revision 和播放器。成功后实体回到“播放歌单”提示项，以便重复播放同一歌单；同名歌单自动显示为“播放歌单 (2)”。带用户身份的调用要求管理员权限；无用户身份的 Home Assistant 内部自动化仍可执行。

## 队列语义

| 操作 | 队列变化 | 是否立即播放 |
|---|---|---|
| 曲目“立即播放” | 清空并替换为所选曲目 | 是 |
| 曲目“下一首播放” | 插入当前指针之后 | 否 |
| 曲目“加入队列” | 追加到队尾 | 否 |
| 歌单曲目点击播放 | 用完整歌单替换并固定点击曲目为第一项；随机模式只打乱后续曲目 | 是 |
| 队列曲目点击 | 顺序不变，只移动当前指针 | 是 |
| 上一首 / 下一首 | 按当前顺序移动指针 | 是 |
| 暂停 | 保留曲目与指针 | 否；停止自动推进 |
| 继续播放 | 保留曲目与指针 | 是；播放器支持 `PLAY` 时从暂停位置恢复，否则重新下发当前曲目 |
| 清空 | 删除全部项目并停止输出 | 否 |
| 顺序循环 | 按队列顺序播放，队尾后回到队首 | 是 |
| 随机播放 | 洗牌尚未播放项目，下一轮继续随机 | 保持当前播放 |
| 单曲循环 | 自动曲终后重新播放当前项 | 是 |

语音口令、Home Assistant 服务动作和 Panel 使用同一个后端队列。通过语音启动歌单后，Panel 会从 WebSocket 订阅实时收到队列状态；不需要轮询页面或刷新浏览器。conversation 传感器可能周期性刷新最近一条识别记录，集成优先使用记录时间戳、conversation ID 或 sequence 去重，没有这些字段时使用 Home Assistant 的状态变更时间；属性刷新不能重新执行同一条点歌命令。

## 播放器选择

Panel 只列出同时支持以下能力的 `media_player`：

1. `MediaPlayerEntityFeature.PLAY_MEDIA`；
2. `PAUSE` 或 `STOP` 中至少一项。

选择保存到队列持久状态。活动播放期间切换输出设备时，集成先停止旧设备，再保存新选择；为避免无意跨设备继续播放，当前队列会进入停止状态，用户需要手工点击播放。

停止时优先调用 `media_pause`，播放器未提供暂停能力时才调用 `media_stop`。

播放器卡片读取实体内存中的 `supported_features`，仅在实体声明 `SEEK`、`VOLUME_SET` 或 `VOLUME_MUTE` 时启用对应进度、音量或静音控件。命令分别调用 Home Assistant 的 `media_seek`、`volume_set` 和 `volume_mute` 动作；未支持的控件保持禁用并说明原因，不会尝试绕过实体能力。[3]

## 状态与并发

Panel 首次载入或从其他页面返回时，并行读取配置、播放器能力和队列快照，随后订阅实时队列事件；这些数据都来自 Home Assistant 内存，不等待 Navidrome 曲库或歌单请求。曲库和歌单在播放器控制就绪后继续后台刷新。所选播放器的状态、音量和进度属性也由 Home Assistant `state_changed` 事件推送到相同订阅，不轮询播放器。播放期间，Panel 只在浏览器内根据最近的 HA 位置时间戳平滑显示秒数；拖动进度后仍由 Home Assistant 实体执行实际跳转。拖动会话中的进度预览持续到 `change`、失焦或当前曲目改变，不会被同曲目的状态事件和秒级显示计时器覆盖。音量命令在等待实体状态事件确认期间保留目标值，避免旧属性造成滑杆回弹。[3] [4]

Home Assistant 外层 Panel 在普通状态变化时只向既有自定义元素转发变化的属性，不会重新创建元素。[1] [5] Panel 的全部渲染路径都在现有 DOM 上逐项同步属性、文本、事件处理器和控件状态；队列事件、通知、主题和数据刷新不会替换根树、队列容器、CD、按钮、滑杆或封面标识相同的图片节点。Home Assistant 重复设置相同的 `narrow`、`hass` 或 Panel 配置时同样保持现有 Shadow DOM 节点。

每个变更命令携带当前 `expected_revision`。单曲和歌单语音任务在开始匹配前记录 revision，并在最终替换队列时校验；匹配期间只要暂停、清空、切换队列、自动推进或另一个页面已经修改队列，服务端就拒绝迟到结果。Panel 的过期命令同样会获取最新状态，而不是覆盖较新的操作。

客户端还会串行发送命令并忽略 revision 倒退的过期响应，避免快速点击造成响应乱序。Panel 被 Home Assistant 移出页面时会同步使当前初始化代次失效、取消未完成的前端请求等待并释放命令链；重新挂载会立即启动新初始化。重连过程中发生的操作会等待当前配置、播放器能力和队列快照就绪后再发送。关闭 Panel 不会终止后端队列或自动切歌。[5]

## 封面与详情

浏览器不直接访问带 Subsonic 凭据的 Navidrome URL。Panel 使用 HA 鉴权封面代理，代理只接受有限长度的封面 ID 和 64、96、128、160、192、256、320、384 px 八种尺寸，限制响应体大小，并通过 OpenSubsonic `getCoverArt` 的 `size` 参数让 Navidrome 生成缩略图。[6] 客户端依据曲目、队列、旋转 CD、详情或歌单的 CSS 尺寸以及 `devicePixelRatio` 选择不小于目标尺寸的最小档位；像素密度按 1.5 倍封顶，在清晰度与传输速度之间取平衡。Navidrome 会缓存缩放后的封面。[7] 浏览器按“尺寸 + 封面 ID”缓存 Blob 对象 URL，防止不同用途错误共用低清图片；数量上限覆盖默认完整队列，内存仍受总字节上限约束。

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
[5]: https://github.com/home-assistant/frontend/blob/350fae410719663c18f72180d83cfeea542288f3/src/panels/custom/ha-panel-custom.ts "Home Assistant custom panel container source"
[6]: https://opensubsonic.netlify.app/docs/endpoints/getcoverart/ "OpenSubsonic getCoverArt endpoint"
[7]: https://www.navidrome.org/docs/usage/library/artwork/ "Navidrome artwork resolution and image encoding"
[8]: https://github.com/home-assistant/frontend/blob/350fae410719663c18f72180d83cfeea542288f3/src/layouts/home-assistant-main.ts "Home Assistant main layout sidebar event handling"
[9]: https://github.com/home-assistant/frontend/blob/350fae410719663c18f72180d83cfeea542288f3/src/components/ha-menu-button.ts "Home Assistant menu button implementation"
[10]: https://developers.home-assistant.io/docs/core/entity/select/ "Home Assistant Select entity"
