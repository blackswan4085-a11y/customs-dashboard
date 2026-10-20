"""설정 로딩. 외부 의존성 없이 config.yaml 의 단순 서브셋을 파싱한다.

PyYAML 이 설치돼 있으면 그것을 쓰고, 없으면 내장된 최소 파서를 사용한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _coerce(val: str) -> Any:
    s = val.strip()
    if s == "" or s.lower() in ("null", "none", "~"):
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if (s[0], s[-1]) in (('"', '"'), ("'", "'")):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _minimal_yaml(text: str) -> dict:
    root: dict = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        key, _, val = line.strip().partition(":")
        key = key.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val.strip() == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce(val)
    return root


def _load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_yaml(text)


def load_env_key() -> str | None:
    env_path = os.path.join(HERE, ".env")
    if os.environ.get("ESTAT_APP_ID"):
        return os.environ["ESTAT_APP_ID"]
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ESTAT_APP_ID="):
                    return line.split("=", 1)[1]
    return None


@dataclass
class Config:
    base_dir: str = HERE
    port: int = 8002
    auto_open: bool = True
    app_id: str | None = None
    years: int = 5
    db_path: str = os.path.join(HERE, "data", "jptrade.db")

    @property
    def db_abspath(self) -> str:
        if os.path.isabs(self.db_path):
            return self.db_path
        return os.path.join(self.base_dir, self.db_path)


def load_config(path: str | None = None) -> Config:
    path = path or os.path.join(HERE, "config.yaml")
    data = _load_yaml(path)
    estat = data.get("estat", {}) or {}
    cfg = Config()
    cfg.port = int(data.get("port", cfg.port))
    cfg.auto_open = bool(data.get("auto_open", cfg.auto_open))
    cfg.years = int(estat.get("years", cfg.years))
    if estat.get("db_path"):
        cfg.db_path = estat["db_path"]
    cfg.app_id = estat.get("app_id") or load_env_key()
    return cfg
