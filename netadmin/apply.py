"""配置应用（画虎）— 将 YAML 模板部署到目标设备

支持变量替换（{{HOSTNAME}} 等）和 Dry-run 模式。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from netadmin.config import DeviceConfig
from netadmin.commands import resolve
from netadmin.connector import Connector, ConnectorError


class ConfigApplier:
    """配置应用器 — 把模板部署到目标设备"""

    def __init__(self) -> None:
        self._results: list[dict] = []

    def apply(self, template_path: str, target_config: DeviceConfig, dry_run: bool = False) -> list[dict]:
        """应用配置到目标设备

        Args:
            template_path: YAML 模板路径
            target_config: 目标设备配置
            dry_run: 试运行模式，不实际写配置

        Returns:
            list[dict]: 执行结果列表
        """
        self._results = []
        template = self._load_template(template_path)
        commands = self._build_config_commands(template, target_config)

        if not commands:
            self._results.append({
                "command": "(no changes needed)",
                "success": True,
                "output": "Template has no configurable content",
            })
            return self._results

        if dry_run:
            for cmd in commands:
                self._results.append({
                    "command": cmd,
                    "success": True,
                    "output": "[dry-run] skipped",
                })
            return self._results

        with Connector(target_config) as conn:
            try:
                # 进入配置模式
                enter = resolve("enter_config_mode", target_config["vendor"])
                conn.send_command(str(enter))

                conn.send_config_set(commands)
            except ConnectorError as e:
                self._results.append({
                    "command": "(batch)",
                    "success": False,
                    "output": str(e),
                })
                return self._results

            # 保存
            try:
                save_cmd = resolve("save_config", target_config["vendor"])
                conn.send_command(str(save_cmd))
            except ConnectorError:
                pass

        # 解析输出
        for i, cmd in enumerate(commands):
            self._results.append({
                "command": cmd,
                "success": True,
                "output": f"OK (cmd {i + 1}/{len(commands)})",
            })

        return self._results

    def _load_template(self, path: str) -> dict:
        """加载 YAML 模板"""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Template not found: {path}")

        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_config_commands(self, template: dict, target: DeviceConfig) -> list[str]:
        """把模板转成目标设备的配置命令

        替换 {{HOSTNAME}} 等占位符为目标设备的值。

        Raises:
            ValueError: 模板字段类型不正确时
        """
        commands: list[str] = []

        if not isinstance(template, dict):
            raise ValueError("Template must be a YAML dictionary")

        vendor = target.get("vendor", "cisco").lower()
        hostname = target.get("name", target["host"])

        vars_map = {
            "HOSTNAME": hostname,
            "MGMT_IP": target["host"],
        }

        # 校验模板字段类型
        vlans = template.get("vlans", [])
        if not isinstance(vlans, list):
            raise ValueError("'vlans' must be a list")
        for v in vlans:
            if not isinstance(v, dict):
                raise ValueError(f"Each VLAN entry must be a dict, got {type(v).__name__}: {v}")

        interfaces = template.get("interfaces", [])
        if not isinstance(interfaces, list):
            raise ValueError("'interfaces' must be a list")
        for iface in interfaces:
            if not isinstance(iface, dict):
                raise ValueError(f"Each interface entry must be a dict, got {type(iface).__name__}: {iface}")

        for key in ("ntp", "snmp", "stp", "management"):
            val = template.get(key)
            if val is not None and not isinstance(val, dict):
                raise ValueError(f"'{key}' must be a dict, got {type(val).__name__}")

        # ── 基本配置 ──
        if vendor == "huawei":
            commands.append("sysname " + hostname.replace(".", "_"))
        else:
            commands.append(f"hostname {hostname}")

        # ── VLAN ──
        if vlans:
            if vendor == "huawei":
                vlan_ids = [str(v["id"]) for v in vlans if v["id"] > 1]
                if vlan_ids:
                    commands.append(f"vlan batch {' '.join(vlan_ids)}")
                for v in vlans:
                    if v["id"] > 1 and v.get("name"):
                        commands.append(f"vlan {v['id']}")
                        commands.append(f"name {v['name']}")
            else:
                for v in vlans:
                    if v["id"] > 1:
                        commands.append(f"vlan {v['id']}")
                        if v.get("name"):
                            commands.append(f"name {v['name']}")

        # ── 接口 ──
        for iface in template.get("interfaces", []):
            ifname = iface.get("name", "").strip()
            if not ifname:
                continue

            commands.append(f"interface {ifname}")

            if iface.get("description"):
                commands.append(f"description {_replace_vars(iface['description'], vars_map)}")

            mode = iface.get("mode", "")
            if mode == "access":
                if vendor == "huawei":
                    commands.append("port link-type access")
                    if iface.get("vlans"):
                        commands.append(f"port default vlan {iface['vlans']}")
                else:
                    commands.append("switchport mode access")
                    if iface.get("vlans"):
                        commands.append(f"switchport access vlan {iface['vlans']}")
            elif mode == "trunk":
                if vendor == "huawei":
                    commands.append("port link-type trunk")
                    if iface.get("vlans"):
                        commands.append(f"port trunk allow-pass vlan {iface['vlans']}")
                else:
                    commands.append("switchport mode trunk")
                    if iface.get("vlans"):
                        commands.append(f"switchport trunk allowed vlan {iface['vlans']}")
            elif mode == "hybrid":
                if vendor == "huawei":
                    commands.append("port link-type hybrid")

            if iface.get("shutdown"):
                commands.append("shutdown")
            else:
                commands.append("undo shutdown")

            # 退回到全局模式（思科不需要，但华为需要，保险起见都加）
            commands.append("quit")

        # ── NTP ──
        ntp = template.get("ntp", {})
        if ntp:
            for server in ntp.get("servers", []):
                srv = _replace_vars(server, vars_map)
                if vendor == "huawei":
                    commands.append(f"ntp server {srv}")
                else:
                    commands.append(f"ntp server {srv}")

        # ── SNMP ──
        snmp = template.get("snmp", {})
        if snmp:
            for community in snmp.get("community", []):
                if vendor == "huawei":
                    commands.append(f"snmp-agent community read {community}")
                else:
                    commands.append(f"snmp-server community {community} RO")

        # ── STP ──
        stp = template.get("stp", {})
        if stp:
            mode = stp.get("mode", "")
            if mode:
                if vendor == "huawei":
                    commands.append(f"stp mode {mode}")
                    if stp.get("root_primary"):
                        commands.append("stp root primary")
                else:
                    commands.append(f"spanning-tree mode {mode}")
                    if stp.get("root_primary"):
                        commands.append("spanning-tree vlan 1 root primary")

        # ── 管理配置 ──
        mgmt = template.get("management", {})
        if mgmt:
            if vendor == "huawei" and mgmt.get("ssh"):
                commands.append("stelnet server enable")
                commands.append("ssh server port 22")

        if vendor == "huawei":
            commands.append("return")
        else:
            commands.append("end")

        return commands

    @property
    def results(self) -> list[dict]:
        return self._results


def _replace_vars(text: str, vars_map: dict[str, str]) -> str:
    """替换 {{VAR}} 占位符"""
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        return vars_map.get(key, m.group(0))
    return re.sub(r"\{\{(\w+)\}\}", replacer, text)