# Changelog

所有重要变更均记录在此文件。版本标签遵循语义化版本。

## [1.0.0] - 2026-08-31

### Added

- Home Assistant 原生 HACS 集成，使用 Config Flow、重新认证和 Options Flow 完成全部配置。
- Navidrome Subsonic/OpenSubsonic 曲库、歌单、详情和封面访问，以及原生限时 MP3 share 播放。
- Home Assistant 侧栏播放面板，支持搜索、歌单、封面、详情、日夜主题、动态播放器和响应式移动布局。
- Home Assistant `.storage` 持久队列，支持上一首、下一首、停止、清空、跳转、插入、追加、随机、单曲循环和列表循环。
- 直接监听 `state_changed` 同步播放器暂停、停止和不可用状态，不使用播放器轮询或额外长连接。
- conversation 传感器语音控制，以及管理员可用的 Home Assistant 原生服务动作。
- 简繁转换、中文完整拼音、日语读音、假名、罗马字和字符距离匹配；不生成拼音首字母。
- 可选 Ollama 与 OpenAI 兼容 Embedding，并支持向量增量复用和故障时词法降级。
- 管理员 WebSocket API、管理员封面代理、有限响应体、严格 share origin 校验和脱敏诊断。
- Ruff、Mypy、Home Assistant 测试、Node 前端测试、Hassfest 与 HACS GitHub Actions 校验。

### Fixed

- Navidrome 原生 share 创建和删除使用官方尾斜杠路由，避免直连内网地址时收到重定向并被判定为无效响应。
- Panel 将封面相对路径直接交给 Home Assistant `fetchWithAuth`，避免公开 HA 地址被重复拼接。
