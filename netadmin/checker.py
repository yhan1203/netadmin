"""设备健康检查 + 安全审计 — CPU/内存/温度 + 合规检查"""

from __future__ import annotations

import re

from netadmin.config import DeviceConfig
from netadmin.commands import resolve
from netadmin.connector import Connector, ConnectorError


def _resolve_cmd(name: str, vendor: str) -> str:
    """安全解析命令，确保返回 str 而非 list"""
    cmd = resolve(name, vendor)
    if isinstance(cmd, list):
        return cmd[0]  # 取第一条命令
    return cmd


class HealthChecker:
    """设备健康检查"""

    def __init__(self) -> None:
        pass

    def check(self, config: DeviceConfig) -> dict:
        """检查一台设备的健康状态"""
        vendor = config.get("vendor", "cisco").lower()
        report: dict = {}

        try:
            with Connector(config) as conn:
                # CPU
                cpu_output = conn.send_command(_resolve_cmd("show_cpu", vendor))
                report["cpu"] = self._parse_cpu(cpu_output, vendor)

                # Memory
                mem_output = conn.send_command(_resolve_cmd("show_memory", vendor))
                report["memory"] = self._parse_memory(mem_output, vendor)

                # Version
                ver_output = conn.send_command(_resolve_cmd("show_version", vendor))
                report["version"] = self._parse_version_line(ver_output)
                report["model"] = self._parse_model(ver_output, vendor)
                report["uptime"] = self._parse_uptime(ver_output, vendor)

                # Temperature (华为)
                if vendor == "huawei":
                    try:
                        env_output = conn.send_command(_resolve_cmd("show_environment", vendor))
                        report["temperature"] = self._parse_temperature(env_output, vendor)
                    except ConnectorError:
                        report["temperature"] = "N/A"
                else:
                    report["temperature"] = "N/A"

                # Log errors
                log_output = conn.send_command(_resolve_cmd("show_log", vendor))
                report["log_errors"] = self._count_log_errors(log_output)

        except ConnectorError as e:
            report["error"] = str(e)

        return report

    @staticmethod
    def _parse_cpu(output: str, vendor: str) -> str:
        if vendor == "huawei":
            m = re.search(r"CPU Usage\s*:\s*(\d+)%", output)
            if m:
                cpu = int(m.group(1))
                return f"{cpu}%" + (" [red]HIGH[/]" if cpu > 80 else " [green]OK[/]")
            # 中文 locale: "CPU 占用率 : 45%"
            m = re.search(r"CPU.{0,8}占用率.*?(\d+)%", output)
            if m:
                cpu = int(m.group(1))
                return f"{cpu}%" + (" [red]HIGH[/]" if cpu > 80 else " [green]OK[/]")
            m = re.search(r"(\d+)%\s*in\s+last", output)
            if m:
                cpu = int(m.group(1))
                return f"{cpu}%" + (" [red]HIGH[/]" if cpu > 80 else " [green]OK[/]")
        else:
            m = re.search(r"CPU utilization for five seconds: (\d+)%", output)
            if m:
                cpu = int(m.group(1))
                return f"{cpu}%" + (" [red]HIGH[/]" if cpu > 80 else " [green]OK[/]")
            m = re.search(r"CPU\s+(\d+)%", output)
            if m:
                cpu = int(m.group(1))
                return f"{cpu}%" + (" [red]HIGH[/]" if cpu > 80 else " [green]OK[/]")
        return "N/A"

    @staticmethod
    def _parse_memory(output: str, vendor: str) -> str:
        if vendor == "huawei":
            m = re.search(r"Memory Using Percentage:\s*(\d+)%", output)
            if m:
                pct = int(m.group(1))
                return f"{pct}%" + (" [red]HIGH[/]" if pct > 80 else " [green]OK[/]")
            # 中文 locale: "内存利用率 : 67%"
            m = re.search(r"内存.{0,8}利用率.*?(\d+)%", output)
            if m:
                pct = int(m.group(1))
                return f"{pct}%" + (" [red]HIGH[/]" if pct > 80 else " [green]OK[/]")
            # 另一种格式
            m = re.search(r"Memory\s+:\s+(\d+)%\s+used", output)
            if m:
                pct = int(m.group(1))
                return f"{pct}%" + (" [red]HIGH[/]" if pct > 80 else " [green]OK[/]")
        else:
            # Cisco: "Processor Pool Total: 1000000 Used: 500000"
            m = re.search(r"Total:\s*(\d+)\s+Used:\s*(\d+)", output)
            if m:
                total = int(m.group(1))
                used = int(m.group(2))
                if total > 0:
                    pct = round(used / total * 100)
                    return f"{pct}%" + (" [red]HIGH[/]" if pct > 80 else " [green]OK[/]")
        return "N/A"

    @staticmethod
    def _parse_version_line(output: str) -> str:
        for line in output.splitlines():
            if "Version" in line or "版本" in line:
                return line.strip()[:60]
        return output.split("\n")[0][:60] if output else "N/A"

    @staticmethod
    def _parse_model(output: str, vendor: str) -> str:
        if vendor == "huawei":
            m = re.search(r"(S\d+|CE\d+|CloudEngine\S+)", output)
            if m:
                return m.group(1)
        else:
            m = re.search(r"(WS-\S+|C\d+-\S+)", output)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _parse_uptime(output: str, vendor: str) -> str:
        if vendor == "huawei":
            m = re.search(r"(\d+\s+(?:year|years|day|days|hour|hours|minute|minutes).*?)(?:\n|$)", output)
            if m:
                return m.group(1).strip()
        else:
            # Cisco: "WS-C2960X-24PS-L uptime is 2 years, 5 days, 10 hours, 30 minutes"
            m = re.search(r"uptime\s+is\s+(.+)", output, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    @staticmethod
    def _parse_temperature(output: str, vendor: str) -> str:
        if vendor == "huawei":
            m = re.search(r"Temperature\s*:\s*(\d+)", output)
            if m:
                t = int(m.group(1))
                return f"{t}°C" + (" [red]HIGH[/]" if t > 65 else " [green]OK[/]")
            # 中文 locale: "系统温度 : 45 摄氏度"
            m = re.search(r"系统温度.*?(\d+)", output)
            if m:
                t = int(m.group(1))
                return f"{t}°C" + (" [red]HIGH[/]" if t > 65 else " [green]OK[/]")
        return "N/A"

    @staticmethod
    def _count_log_errors(output: str) -> str:
        errors = 0
        for line in output.splitlines():
            if re.search(r"error|err|fail|down|critical", line, re.IGNORECASE):
                errors += 1
        return str(errors) if errors else "0 (clean)"


class SecurityAuditor:
    """安全合规审计"""

    def __init__(self) -> None:
        self._findings: list[dict] = []
        self._score = 100

    def audit(self, config: DeviceConfig) -> dict:
        """对设备执行安全审计"""
        vendor = config.get("vendor", "cisco").lower()
        self._findings = []
        self._score = 100

        try:
            with Connector(config) as conn:
                config_text = conn.send_command(_resolve_cmd("show_running_config", vendor))

                self._check_password_encryption(config_text, vendor)
                self._check_snmp_community(config_text)
                self._check_ssh_version(config_text)
                self._check_vty_acl(config_text, vendor)
                self._check_banner(config_text)
                self._check_default_vlan(config_text, vendor)
                self._check_logging(config_text)
                self._check_ntp(config_text, vendor)

        except ConnectorError as e:
            return {"error": str(e), "score": 0, "findings": [{"check": "connection", "passed": False, "detail": str(e)}]}

        return {
            "host": config["host"],
            "score": self._score,
            "findings": self._findings,
        }

    def _add_finding(self, check: str, passed: bool, detail: str = "") -> None:
        self._findings.append({"check": check, "passed": passed, "detail": detail})
        if not passed:
            self._score = max(0, self._score - 10)

    def _check_password_encryption(self, config: str, vendor: str) -> None:
        if vendor == "huawei":
            if "password cipher" in config or "password encryption" in config:
                self._add_finding("Password Encryption", True, "Passwords are encrypted")
            else:
                self._add_finding("Password Encryption", False,
                                  "Use 'password cipher' to encrypt passwords")
        else:
            if "service password-encryption" in config:
                self._add_finding("Password Encryption", True, "service password-encryption enabled")
            else:
                self._add_finding("Password Encryption", False,
                                  "Enable 'service password-encryption'")
            if "enable secret" in config:
                self._add_finding("Enable Secret", True, "enable secret is configured")
            else:
                self._add_finding("Enable Secret", False,
                                  "Use 'enable secret' instead of 'enable password'")

    def _check_snmp_community(self, config: str) -> None:
        m = re.search(r"(?:snmp-agent community|snmp-server community)\s+(\S+)", config)
        if m:
            community = m.group(1)
            if community in ("public", "private", "default"):
                self._add_finding("SNMP Community", False,
                                  f"Default SNMP community '{community}' detected — CHANGE IT")
            else:
                self._add_finding("SNMP Community", True, "Custom community string in use")
        else:
            self._add_finding("SNMP Community", True, "SNMP not configured (no exposure)")

    def _check_ssh_version(self, config: str) -> None:
        if "ssh version 2" in config.lower() or "ssh server" in config.lower():
            self._add_finding("SSH Version", True, "SSH v2 configured")
        elif "ip ssh version" in config:
            if "version 2" in config:
                self._add_finding("SSH Version", True, "SSH v2 configured")
            else:
                self._add_finding("SSH Version", False, "SSH v1 configured — upgrade to v2")
        else:
            self._add_finding("SSH Version", False, "No explicit SSH version config — configure SSH v2 for security")

    def _check_vty_acl(self, config: str, vendor: str) -> None:
        if vendor == "huawei":
            if "acl" in config and "vty" in config:
                self._add_finding("VTY ACL", True, "ACL applied to VTY")
            else:
                self._add_finding("VTY ACL", False,
                                  "No ACL on VTY lines — management access unrestricted")
        else:
            if re.search(r"access-class\s+\d+\s+in", config):
                self._add_finding("VTY ACL", True, "access-class applied to VTY")
            else:
                self._add_finding("VTY ACL", False,
                                  "No access-class on VTY lines")

    def _check_banner(self, config: str) -> None:
        if "banner" in config.lower() or "header" in config.lower():
            self._add_finding("Login Banner", True, "Banner is configured")
        else:
            self._add_finding("Login Banner", False,
                              "No legal warning banner — configure 'banner motd'")

    def _check_default_vlan(self, config: str, vendor: str) -> None:
        if vendor == "huawei":
            if re.search(r"port default vlan\s+1", config):
                self._add_finding("Default VLAN 1", False,
                                  "Ports using default VLAN 1 — use a separate management VLAN")
            else:
                self._add_finding("Default VLAN 1", True, "VLAN 1 not used on access ports")
        else:
            if re.search(r"switchport access vlan\s+1", config):
                self._add_finding("Default VLAN 1", False,
                                  "Ports using native VLAN 1 — reconfigure to dedicated VLAN")
            else:
                self._add_finding("Default VLAN 1", True, "VLAN 1 not in use on ports")

    def _check_logging(self, config: str) -> None:
        if re.search(r"log(?:ging|buffer|_host)", config, re.IGNORECASE):
            self._add_finding("Logging", True, "Logging configured")
        else:
            self._add_finding("Logging", False, "No logging configured")

    def _check_ntp(self, config: str, vendor: str) -> None:
        if "ntp" in config.lower():
            self._add_finding("NTP", True, "NTP configured")
        else:
            self._add_finding("NTP", False, "No NTP configured — clocks may drift")