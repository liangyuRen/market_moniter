"""配置加载工具 — YAML配置文件读取"""
import yaml
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).parent.parent / "config"

_cache: dict[str, dict] = {}


def _load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_settings() -> dict:
    """获取主配置"""
    if "settings" not in _cache:
        _cache["settings"] = _load_yaml("settings.yaml")
    return _cache["settings"]


def get_watchlist() -> list:
    """获取自选股列表"""
    if "stocks" not in _cache:
        data = _load_yaml("watchlist.yaml")
        _cache["stocks"] = data.get("stocks", [])
        _cache["indices"] = data.get("indices", [])
    return _cache["stocks"]


def get_indices() -> list:
    """获取监控指数列表"""
    if "indices" not in _cache:
        data = _load_yaml("watchlist.yaml")
        _cache["stocks"] = data.get("stocks", [])
        _cache["indices"] = data.get("indices", [])
    return _cache["indices"]


def get_alert_rules() -> list:
    """获取告警规则"""
    if "alert_rules" not in _cache:
        data = _load_yaml("alert_rules.yaml")
        _cache["alert_rules"] = data.get("rules", [])
    return _cache["alert_rules"]


def get_enabled_rules() -> list:
    """获取启用的告警规则"""
    return [r for r in get_alert_rules() if r.get("enabled", False)]


def reload_config():
    """强制重新加载所有配置"""
    _cache.clear()
