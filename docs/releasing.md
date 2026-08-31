# HACS 集成发布流程

本项目使用 GitHub Release 作为 HACS 版本来源。

## 版本文件

正式发布前，以下位置必须包含相同语义版本：

| 文件 | 字段 |
|---|---|
| `custom_components/xiaoai_navidrome/manifest.json` | `version` |
| `custom_components/xiaoai_navidrome/const.py` | `VERSION` |
| `pyproject.toml` | `project.version` |
| `CHANGELOG.md` | 对应版本标题 |

`release.yml` 会在创建 GitHub Release 前再次验证四处一致性。

## 本地质量门禁

首次准备测试环境：

```bash
make setup
```

每次发布前运行：

```bash
make check
```

该命令执行 Ruff、Mypy、Python 编译、Home Assistant 2026.8.3 测试、前端 JavaScript 语法、Node 单元测试和 JSON 解析。GitHub CI 另外运行 Hassfest 与 HACS Action，验证集成清单、翻译、服务描述和 HACS 仓库结构。[1] [2]

公开测试只能使用合成曲目、歌单、查询、URL 和 ID。不得把真实用户曲库、conversation 文本、凭据、临时诊断或部署配置提交到仓库。

## 发布步骤

首先确保 `main` 与远端一致、工作树干净，并确认最新 CI 全部通过：

```bash
git switch main
git pull --ff-only
git status --short
```

创建不可移动的 annotated tag：

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

`Release HACS integration` 工作流会重新执行完整质量门禁，然后通过 GitHub CLI 从该 tag 创建带自动生成说明的 GitHub Release。HACS 默认从 GitHub Release 的源码归档中读取唯一的 `custom_components/xiaoai_navidrome` 目录，因此本项目不启用 `zip_release`。[3]

## 发布后验证

| 检查 | 预期结果 |
|---|---|
| GitHub Actions | release workflow 成功 |
| GitHub Release | 标签非草稿、非 prerelease，目标提交正确 |
| Release source archive | 包含完整 `custom_components/xiaoai_navidrome` |
| HACS 自定义存储库 | 识别最新版本并允许下载 |
| Home Assistant | 重启后 manifest 版本与 release 一致 |

首次发布后，应在干净的 Home Assistant 测试实例中通过 HACS 添加仓库、下载、重启、完成 Config Flow，并验证一次 share 播放。GitHub Actions 的单元测试不能代替音箱对实际 Navidrome 公开 share URL 的访问测试。

## 后续补丁

不要删除、覆盖或移动已经发布的 tag。修复发布应递增 patch 版本并创建新 tag。

## References

[1]: https://developers.home-assistant.io/docs/development_validation/ "Home Assistant integration validation with Hassfest"
[2]: https://www.hacs.xyz/docs/publish/action/ "HACS GitHub Action validation"
[3]: https://www.hacs.xyz/docs/publish/integration/ "HACS integration repository and release structure"
