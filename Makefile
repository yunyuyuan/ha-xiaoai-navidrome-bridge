PYTHON := .venv/bin/python
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

.PHONY: setup format lint typecheck test frontend-check json-check check

setup:
	uv python install 3.14
	uv venv --python 3.14 .venv
	uv pip install --python $(PYTHON) \
		'homeassistant==2026.8.3' \
		'home-assistant-frontend==20260729.7' \
		'pytest-homeassistant-custom-component==0.13.357' \
		'pytest==9.0.3' \
		'pytest-asyncio==1.4.0' \
		'ruff==0.16.5' \
		'mypy==2.3.1' \
		'opencc-python-reimplemented==0.1.7' \
		'pypinyin==0.55.0' \
		'pykakasi==2.3.0'

format:
	$(RUFF) check custom_components tests --fix
	$(RUFF) format custom_components tests

lint:
	$(RUFF) check custom_components tests
	$(RUFF) format --check custom_components tests
	$(PYTHON) -m compileall -q custom_components tests

typecheck:
	$(MYPY) custom_components/xiaoai_navidrome

test:
	$(PYTHON) -m pytest

frontend-check:
	node --check custom_components/xiaoai_navidrome/frontend/panel.js
	node --test tests/frontend_panel.test.mjs

json-check:
	$(PYTHON) -m json.tool custom_components/xiaoai_navidrome/manifest.json >/dev/null
	$(PYTHON) -m json.tool custom_components/xiaoai_navidrome/strings.json >/dev/null
	$(PYTHON) -m json.tool custom_components/xiaoai_navidrome/translations/en.json >/dev/null
	$(PYTHON) -m json.tool custom_components/xiaoai_navidrome/translations/zh-Hans.json >/dev/null
	$(PYTHON) -m json.tool custom_components/xiaoai_navidrome/icons.json >/dev/null
	$(PYTHON) -m json.tool hacs.json >/dev/null

check: lint typecheck test frontend-check json-check
