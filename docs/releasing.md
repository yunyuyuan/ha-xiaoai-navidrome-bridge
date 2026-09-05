# HACS Integration Release Process

This project uses GitHub Releases as the HACS version source.

## Version Files

Before an official release, the following locations must contain the same semantic version:

| File | Field |
|---|---|
| `custom_components/xiaoai_navidrome/manifest.json` | `version` |
| `custom_components/xiaoai_navidrome/const.py` | `VERSION` |
| `pyproject.toml` | `project.version` |
| `CHANGELOG.md` | Corresponding version heading |

`release.yml` verifies that all four locations match again before creating the GitHub Release.

## Local Quality Gates

To prepare a test environment for the first time, run:

```bash
make setup
```

Before every release, run:

```bash
make check
```

This command runs Ruff, Mypy, Python compilation, Home Assistant 2026.8.3 tests, frontend JavaScript syntax checks, Node unit tests, and JSON parsing. GitHub CI additionally runs Hassfest and the HACS Action to validate the integration manifest, translations, service descriptions, and HACS repository structure. [1] [2]

Public tests must use only synthetic tracks, playlists, queries, URLs, and IDs. Do not commit real user music libraries, conversation text, credentials, temporary diagnostics, or deployment configuration to the repository.

## Release Steps

First, ensure that `main` is synchronized with the remote, the working tree is clean, and the latest CI run has passed:

```bash
git switch main
git pull --ff-only
git status --short
```

Create an immutable annotated tag:

```bash
version=$(python3 -c 'import json; print(json.load(open("custom_components/xiaoai_navidrome/manifest.json"))["version"])')
git tag -a "v${version}" -m "Release v${version}"
git push origin "v${version}"
```

The `Release HACS integration` workflow runs the complete quality gate again and then uses the GitHub CLI to create a GitHub Release from the tag with automatically generated notes. HACS reads the single `custom_components/xiaoai_navidrome` directory from the GitHub Release source archive by default; therefore, this project does not enable `zip_release`. [3]

## Post-Release Verification

| Check | Expected result |
|---|---|
| GitHub Actions | The release workflow succeeds. |
| GitHub Release | The tag is neither a draft nor a prerelease, and it targets the correct commit. |
| Release source archive | It contains the complete `custom_components/xiaoai_navidrome` directory. |
| HACS custom repository | It recognizes the latest version and permits download. |
| Home Assistant | After restart, the manifest version matches the release. |

After the first release, use a clean Home Assistant test instance to add the repository through HACS, download it, restart, complete the Config Flow, and verify one share playback. GitHub Actions unit tests do not replace an access test from a speaker to an actual public Navidrome share URL.

## Subsequent Patches

Do not delete, overwrite, or move an already released tag. A release fix must increment the patch version and create a new tag.

## References

[1]: https://developers.home-assistant.io/docs/development_validation/ "Home Assistant integration validation with Hassfest"
[2]: https://www.hacs.xyz/docs/publish/action/ "HACS GitHub Action validation"
[3]: https://www.hacs.xyz/docs/publish/integration/ "HACS integration repository and release structure"
