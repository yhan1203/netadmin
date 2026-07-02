"""配置学习（照猫）— 连上一台设备，抓取配置，提取结构化模板

输出一个 YAML 模板，可直接用于 apply 命令部署到另一台设备。
"""

from __future__ import annotations

import datetime
import re
import typing as t

import yaml

from netadmin.config import DeviceConfig
from netadmin.commands import resolve
from netadmin.connector import Connector


class LearnedTemplate(t.NamedTuple):
    """学习到的配置模板"""
    hostname: str
    vendor: str
    model: str
    version: str
    vlans: list[dict]
    interfaces: list[dict]
    ntp: dict | None
    snmp: dict | None
    stp: dict | None
    management: dict | None
    raw_yaml: str


class ConfigLearner:
    """从设备学习配置，生成可复用模板"""

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.vendor = config.get("vendor", "cisco").lower()
        self._raw_config: str = ""

    def learn(self) -> LearnedTemplate:
        """连接设备并学习配置

        Returns:
            LearnedTemplate 包含所有结构化信息
        """
        with Connector(self.config) as conn:
            self._raw_config = self._fetch_config(conn)
            prompt = conn.get_prompt()
            hostname = prompt.rstrip("#>").strip()

            version_output = conn.send_command(str(resolve("show_version", self.vendor)))
            model, version = self._parse_version(version_output)

        vlans = self._extract_vlans()
        interfaces = self._extract_interfaces()
        ntp = self._extract_ntp()
        snmp = self._extract_snmp()
        stp = self._extract_stp()
        management = self._extract_management()

        yaml_output = self._to_yaml(hostname, self.vendor, model, version, vlans, interfaces, ntp, snmp, stp, management)

        return LearnedTemplate(
            hostname=hostname,
            vendor=self.vendor,
            model=model,
            version=version,
            vlans=vlans,
            interfaces=interfaces,
            ntp=ntp,
            snmp=snmp,
            stp=stp,
            management=management,
            raw_yaml=yaml_output,
        )

    def _fetch_config(self, conn: Connector) -> str:
        """抓取 running-config"""
        cmd = resolve("show_running_config", self.vendor)
        return conn.send_command(str(cmd))

    def _parse_version(self, output: str) -> tuple[str, str]:
        """从 version 输出中提取型号和版本号"""
        model = ""
        version = ""

        if self.vendor == "huawei":
            # Huawei: "Huawei S5735S-L24T4S-A" / "VRP (R) software, Version 5.170"
            m = re.search(r"(S\d+|CE\d+|CloudEngine\S+)", output)
            if m:
                model = m.group(1)
            m = re.search(r"Version ([\d.]+)", output)
            if m:
                version = f"VRP {m.group(1)}"
        else:
            # Cisco: "WS-C2960X-24PS-L" / "Version 15.2(7)E"
            m = re.search(r"(WS-\S+|C\d+-\S+)", output)
            if m:
                model = m.group(1)
            m = re.search(r"Version ([\d.]+(?:\(\d+\))?[A-Za-z]?)", output)
            if m:
                version = f"IOS {m.group(1)}"

        return model, version

    def _extract_vlans(self) -> list[dict]:
        """从配置中提取 VLAN 信息"""
        vlans: list[dict] = []
        config = self._raw_config

        if self.vendor == "huawei":
            # vlan batch 10 20 30
            m = re.search(r"vlan batch\s+(.+)$", config, re.MULTILINE)
            if m:
                for v in re.findall(r"\d+", m.group(1)):
                    vlans.append({"id": int(v), "name": ""})

            # vlan 10 / name office  — 使用 m.start() 定位而非 config.index()
            for m in re.finditer(r"^\s*vlan\s+(\d+)\s*$", config, re.MULTILINE):
                vlan_id = int(m.group(1))
                name = ""
                # 看下一行是不是 name
                remaining = config[m.end():]
                next_line = remaining.strip().split("\n")[0] if remaining.strip() else ""
                if next_line.startswith("name "):
                    name = next_line[5:].strip().strip('"')
                # 去重并补 name（batch 添加的 VLAN 没有 name）
                existing = next((v for v in vlans if v["id"] == vlan_id), None)
                if existing:
                    if name and not existing["name"]:
                        existing["name"] = name
                else:
                    vlans.append({"id": vlan_id, "name": name})
        else:
            # Cisco: vlan 10 / name office  — 使用 m.start() 定位而非 config.index()
            for m in re.finditer(r"^\s*vlan\s+(\d+)", config, re.MULTILINE):
                vlan_id = int(m.group(1))
                name = ""
                remaining = config[m.end():]
                next_line = remaining.strip().split("\n")[0] if remaining.strip() else ""
                if next_line.startswith("name "):
                    name = next_line[5:].strip().strip('"')
                if not any(v["id"] == vlan_id for v in vlans):
                    vlans.append({"id": vlan_id, "name": name})

        # 去掉 VLAN 1（默认存在）
        vlans = [v for v in vlans if v["id"] != 1]
        return vlans

    def _extract_interfaces(self) -> list[dict]:
        """从配置中提取接口配置"""
        interfaces: list[dict] = []
        config = self._raw_config

        if self.vendor == "huawei":
            # interface GigabitEthernet0/0/1 / port link-type ...
            for m in re.finditer(
                    r"^interface\s+(\S+?)(?:\s*\n(?!interface)(?!return)(?!\s*$)(?:.*\n)*?)(?=^\S|\Z)",
                    config, re.MULTILINE,
            ):
                block = m.group(0)
                iface_name = m.group(1)
                iface: dict = {"name": iface_name, "mode": "", "vlans": "", "description": "", "shutdown": False}
                if "port link-type trunk" in block:
                    iface["mode"] = "trunk"
                    m2 = re.search(r"port trunk allow-pass vlan\s+([\d\s,-]+)", block)
                    if m2:
                        iface["vlans"] = m2.group(1).strip()
                elif "port link-type access" in block:
                    iface["mode"] = "access"
                    m2 = re.search(r"port default vlan\s+(\d+)", block)
                    if m2:
                        iface["vlans"] = m2.group(1)
                elif "port hybrid" in block:
                    iface["mode"] = "hybrid"

                m2 = re.search(r"description\s+(.+)", block)
                if m2:
                    iface["description"] = m2.group(1).strip().strip('"')
                if "shutdown" in block:
                    iface["shutdown"] = True
                interfaces.append(iface)
        else:
            # Cisco: interface GigabitEthernet1/0/1 / switchport mode ...
            for m in re.finditer(
                    r"^interface\s+(\S+?)(?:\s*\n(?!interface)(?!end)(?!\s*$)(?:.*\n)*?)(?=^\S|\Z)",
                    config, re.MULTILINE,
            ):
                block = m.group(0)
                iface_name = m.group(1)
                iface: dict = {"name": iface_name, "mode": "", "vlans": "", "description": "", "shutdown": False}
                if "switchport mode trunk" in block:
                    iface["mode"] = "trunk"
                    m2 = re.search(r"switchport trunk allowed vlan\s+([\d\s,-]+)", block)
                    if m2:
                        iface["vlans"] = m2.group(1).strip()
                elif "switchport mode access" in block:
                    iface["mode"] = "access"
                    m2 = re.search(r"switchport access vlan\s+(\d+)", block)
                    if m2:
                        iface["vlans"] = m2.group(1)
                m2 = re.search(r"description\s+(.+)", block)
                if m2:
                    iface["description"] = m2.group(1).strip().strip('"')
                if "shutdown" in block:
                    iface["shutdown"] = True
                interfaces.append(iface)

        return interfaces

    def _extract_ntp(self) -> dict | None:
        """提取 NTP 配置"""
        config = self._raw_config
        ntp: dict = {"servers": [], "timezone": ""}

        for m in re.finditer(r"ntp[_\s]server\s+(\S+)", config, re.IGNORECASE):
            ntp["servers"].append(m.group(1))

        m = re.search(r"clock[_\s]timezone\s+(\S+)", config, re.IGNORECASE)
        if m:
            ntp["timezone"] = m.group(1)

        return ntp if ntp["servers"] else None

    def _extract_snmp(self) -> dict | None:
        """提取 SNMP 配置"""
        config = self._raw_config
        snmp: dict = {"community": [], "location": "", "contact": ""}

        for m in re.finditer(r"snmp-agent[_\s]community[_\s](?:read|write)\s+(\S+)", config, re.IGNORECASE):
            snmp["community"].append(m.group(1))
        for m in re.finditer(r"snmp[_-]server[_\s]community\s+(\S+)", config, re.IGNORECASE):
            snmp["community"].append(m.group(1))
        m = re.search(r"(?:snmp-server location|snmp-agent sys-info location|snmp[_-]location)\s+(.+)", config, re.IGNORECASE)
        if m:
            snmp["location"] = m.group(1).strip().strip('"')
        m = re.search(r"snmp[_-]contact\s+(.+)", config, re.IGNORECASE)
        if m:
            snmp["contact"] = m.group(1).strip().strip('"')

        return snmp if snmp["community"] or snmp["location"] else None

    def _extract_stp(self) -> dict | None:
        """提取 STP 配置"""
        config = self._raw_config
        stp: dict = {"mode": "", "root_primary": False}

        for mode in ["mstp", "rstp", "stp", "pvst", "rapid-pvst"]:
            if re.search(rf"(stp[_\s]mode|spanning-tree[_\s]mode)\s+{mode}", config, re.IGNORECASE):
                stp["mode"] = mode
                break

        if not stp["mode"]:
            if "stp enable" in config or "spanning-tree vlan" in config:
                stp["mode"] = "stp"

        stp["root_primary"] = "stp root primary" in config or "spanning-tree vlan 1 root primary" in config

        return stp if stp["mode"] else None

    def _extract_management(self) -> dict | None:
        """提取管理配置（SSH、用户、管理 IP）"""
        config = self._raw_config
        mgmt: dict = {"ssh": False, "users": [], "mgmt_ip": ""}

        mgmt["ssh"] = bool(re.search(r"ssh[_\s]server|ip[_\s]ssh[_\s]version|aaa new-model", config, re.IGNORECASE))

        # 管理 IP（从 interface vlanif 或 vlan 1 等取）
        m = re.search(r"interface (?:Vlanif|Vlan)\s*\d+.*?(?:\n.*?)*?ip address\s+(\S+)", config, re.DOTALL)
        if m:
            mgmt["mgmt_ip"] = m.group(1)

        return mgmt if mgmt["ssh"] or mgmt["mgmt_ip"] else None

    def _to_yaml(
        self,
        hostname: str,
        vendor: str,
        model: str,
        version: str,
        vlans: list,
        interfaces: list,
        ntp: dict | None,
        snmp: dict | None,
        stp: dict | None,
        management: dict | None,
    ) -> str:
        """生成 YAML 模板"""
        data = {
            "#meta": {
                "generated_by": f"netadmin learn {self.config['host']}",
                "generated_at": datetime.datetime.now().isoformat(),
                "source_device": self.config["host"],
            },
            "device": {
                "hostname": "{{HOSTNAME}}",  # 占位符，应用时替换
                "vendor": vendor,
                "model": model,
                "version": version,
            },
            "vlans": vlans or [],
            "interfaces": interfaces or [],
        }

        if ntp:
            data["ntp"] = {"servers": ntp["servers"], "timezone": ntp["timezone"]}
        if snmp:
            data["snmp"] = snmp
        if stp:
            data["stp"] = stp
        if management:
            data["management"] = management

        return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)