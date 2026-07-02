"""配置加载 — 读取 YAML 设备清单 + 命令行参数覆盖"""

from __future__ import annotations

import os
import typing as t
from pathlib import Path

import yaml


class DeviceConfig(t.TypedDict, total=False):
    host: str
    name: str
    vendor: str  # huawei | cisco
    device_type: str
    port: int
    username: str
    password: str
    timeout: int


class Settings:
    """全局设置，从 config.yaml 加载"""

    def __init__(self, path: str | Path | None = None) -> None:
        path = path or self._find_config()
        raw = self._load(path)
        self.devices: list[DeviceConfig] = raw.get("devices", [])
        defaults = raw.get("defaults", {})
        self.default_username: str = defaults.get("username", "admin")
        self.default_password: str = defaults.get("password", "")
        self.default_port: int = defaults.get("port", 22)
        self.default_timeout: int = defaults.get("timeout", 30)
        self.backup_dir: str = raw.get("backup_dir", "./backups")
        self.db_path: str = raw.get("db_path", "./netadmin.db")
        self._config_path: str = str(path) if path else ""

        # 环境变量覆盖密码（安全）
        for dev in self.devices:
            env_key = f"NETADMIN_PASS_{dev['host'].replace('.', '_')}"
            if env_key in os.environ:
                dev["password"] = os.environ[env_key]

    def get_device(self, host: str) -> DeviceConfig | None:
        """按 host 或 name 查找设备"""
        for d in self.devices:
            if d["host"] == host or d.get("name") == host:
                return d
        return None

    def resolve_device(self, host: str, **overrides: t.Any) -> DeviceConfig:
        """获取设备配置，用参数覆盖 YAML 值，缺失字段用默认值补"""
        base = self.get_device(host) or DeviceConfig(host=host)
        return DeviceConfig(
            host=host,
            name=overrides.get("name") or base.get("name", host),
            vendor=overrides.get("vendor") or base.get("vendor", self._guess_vendor(host)),
            device_type=overrides.get("device_type") or base.get("device_type", "cisco_ios"),
            port=overrides.get("port") or base.get("port", self.default_port),
            username=overrides.get("username") or base.get("username", self.default_username),
            password=overrides.get("password") or base.get("password", self.default_password),
            timeout=overrides.get("timeout") or base.get("timeout", self.default_timeout),
        )

    def all_devices(self) -> list[DeviceConfig]:
        return self.devices

    @staticmethod
    def _load(path: str | Path | None) -> dict:
        if path and Path(path).exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f)
        return {"devices": [], "defaults": {}}

    @staticmethod
    def _find_config() -> str | None:
        """从当前目录向上找 config.yaml"""
        for p in [Path.cwd(), *Path.cwd().parents]:
            candidate = p / "config.yaml"
            if candidate.exists():
                return str(candidate)
        return None

    @staticmethod
    def _guess_vendor(host: str) -> str:
        """简单的厂商猜测（以后可以改成 SSH banner 识别）"""
        return "huawei" if not host.startswith("192.168.1.2") else "cisco"

    @property
    def config_path(self) -> str:
        return self._config_path