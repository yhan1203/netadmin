"""设备连接器 — 统一华为/思科 SSH 连接

对上层屏蔽厂商差异，上层只需调用：
    async with Connector(config) as conn:
        output = await conn.send_command("display vlan")
"""

from __future__ import annotations

import re
import time
import typing as t

from netmiko import ConnectHandler
from netmiko.base_connection import BaseConnection

from netadmin.config import DeviceConfig

# ── 厂商识别 ─────────────────────────────────────────────

VENDOR_PATTERNS: dict[str, list[str]] = {
    "huawei": [r"(?i)huawei", r"<[\w-]+>", r"\[~?[\w-]+\]"],
    "cisco": [r"(?i)cisco", r"[\w-]+#", r"[\w-]+>"],
}

VENDOR_ALIASES: dict[str, str] = {
    "huawei": "huawei",
    "华为": "huawei",
    "cisco": "cisco",
    "思科": "cisco",
}


def normalize_vendor(vendor: str) -> str:
    return VENDOR_ALIASES.get(vendor.lower(), vendor.lower())


# ── 连接异常 ─────────────────────────────────────────────


class ConnectorError(Exception):
    """连接或执行出错"""
    def __init__(self, message: str, device: str = "", command: str = "") -> None:
        self.device = device
        self.command = command
        super().__init__(f"[{device}] {message}" + (f" (cmd: {command})" if command else ""))


def _check_password(password: str, host: str) -> None:
    """检查密码是否为空，空密码时输出明确提示"""
    if not password:
        raise ConnectorError(
            "Password is empty. Set it in config.yaml or via NETADMIN_PASS_<HOST> environment variable.\n"
            f"  config.yaml: devices[host={host}].password = \"...\"\n"
            f"  env var:     export NETADMIN_PASS_{host.replace('.', '_')}=...",
            device=host,
        )


# ── 连接器 ───────────────────────────────────────────────


class Connector:
    """网络设备连接器，封装 Netmiko 的连接管理"""

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self._conn: BaseConnection | None = None

    def connect(self) -> None:
        """建立 SSH 连接"""
        _check_password(self.config.get("password", ""), self.config["host"])
        try:
            self._conn = ConnectHandler(
                device_type=self.config["device_type"],
                host=self.config["host"],
                port=self.config["port"],
                username=self.config["username"],
                password=self.config["password"],
                timeout=self.config.get("timeout", 30),
                global_delay_factor=2,  # 华为设备有时反应慢
                fast_cli=False,         # 兼容性优先
            )
            # 尝试进入 enable/privileged 模式
            # 华为设备有时不支持 enable 模式，静默跳过
            try:
                self._conn.enable()
            except Exception:
                pass
        except Exception as e:
            raise ConnectorError(str(e), device=self.config["host"]) from e

    def send_command(self, command: str) -> str:
        """发送命令并返回输出"""
        if not self._conn:
            raise ConnectorError("Not connected", device=self.config["host"])
        try:
            output = self._conn.send_command(
                command,
                delay_factor=2,
                expect_string=r"[#>\]]$",  # 通用提示符匹配
            )
            return output.strip()
        except Exception as e:
            raise ConnectorError(str(e), device=self.config["host"], command=command) from e

    def send_command_timing(self, command: str, delay_factor: int = 1) -> str:
        """发送命令并返回输出（基于时间等待，不匹配提示符）

        用于 save 等需要响应 [Y/N] 确认弹窗的命令。
        """
        if not self._conn:
            raise ConnectorError("Not connected", device=self.config["host"])
        try:
            output = self._conn.send_command_timing(
                command,
                delay_factor=delay_factor,
            )
            return output.strip()
        except Exception as e:
            raise ConnectorError(str(e), device=self.config["host"], command=command) from e

    def send_config_set(self, commands: list[str]) -> str:
        """发送配置模式命令集"""
        if not self._conn:
            raise ConnectorError("Not connected", device=self.config["host"])
        try:
            output = self._conn.send_config_set(commands)
            return output.strip()
        except Exception as e:
            raise ConnectorError(str(e), device=self.config["host"], command=" | ".join(commands[:3]))

    def get_prompt(self) -> str:
        """获取当前提示符"""
        if not self._conn:
            raise ConnectorError("Not connected", device=self.config["host"])
        return self._conn.find_prompt()

    def detect_vendor(self) -> str:
        """通过 SSH banner 和 prompt 自动识别厂商"""
        prompt = self.get_prompt()
        for vendor, patterns in VENDOR_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, prompt):
                    return vendor
        # 再试 login banner
        try:
            vendor = self.config.get("vendor", "").lower()
            output = self.send_command("display version" if vendor == "huawei" else "show version")
            if re.search(r"(?i)huawei|vrp", output):
                return "huawei"
            if re.search(r"(?i)cisco|ios", output):
                return "cisco"
        except Exception:
            pass
        return "unknown"

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.disconnect()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> Connector:
        self.connect()
        return self

    def __exit__(self, *args: t.Any) -> None:
        self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and self._conn.is_alive()


# ── 便捷方法 ─────────────────────────────────────────────


def test_connection(host: str, username: str, password: str, port: int = 22, device_type: str = "cisco_ios") -> dict:
    """测试连接，返回结果信息"""
    cfg = DeviceConfig(host=host, username=username, password=password, port=port, device_type=device_type, name=host, vendor=detect_vendor_from_short(device_type))
    start = time.time()
    try:
        with Connector(cfg) as conn:
            prompt = conn.get_prompt()
            elapsed = round(time.time() - start, 2)
            vendor = conn.detect_vendor()
            return {"success": True, "prompt": prompt, "vendor": vendor, "elapsed": elapsed}
    except ConnectorError as e:
        return {"success": False, "error": str(e), "elapsed": round(time.time() - start, 2)}
    except Exception as e:
        return {"success": False, "error": f"Unknown error: {e}", "elapsed": round(time.time() - start, 2)}


def detect_vendor_from_short(vendor: str) -> str:
    """从短名称或 device_type 返回标准厂商名"""
    v = vendor.lower()
    if "huawei" in v:
        return "huawei"
    return "cisco"