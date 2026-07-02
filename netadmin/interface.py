"""接口状态 — 查看接口列表和详细信息"""

from __future__ import annotations

from rich.table import Table
from rich.box import ROUNDED

from netadmin.config import DeviceConfig
from netadmin.commands import resolve
from netadmin.connector import Connector


class InterfaceInfo:
    """接口信息查询"""

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.vendor = config.get("vendor", "cisco").lower()

    def get_interface_table(self) -> Table:
        """获取接口状态表格"""
        cmd = resolve("show_interface", self.vendor)

        with Connector(self.config) as conn:
            output = conn.send_command(str(cmd))

        table = Table(title=f"Interface Status — {self.config['host']}", box=ROUNDED)
        table.add_column("Interface", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Protocol")
        table.add_column("VLAN", style="green")
        table.add_column("Description", overflow="fold")
        table.add_column("Speed/Duplex")

        rows = self._parse_interface_output(output)
        for row in rows:
            status_style = "green" if row["status"] == "up" else "red" if row["status"] == "down" else "yellow"
            table.add_row(
                row["interface"],
                f"[{status_style}]{row['status']}[/]",
                row.get("protocol", ""),
                row.get("vlan", ""),
                row.get("description", ""),
                row.get("speed", ""),
            )
        return table

    def get_interface_detail(self, interface: str) -> str:
        """获取单个接口详情"""
        cmd = resolve("show_interface_detail", self.vendor)

        with Connector(self.config) as conn:
            output = conn.send_command(f"{cmd} {interface}")
        return output

    def _parse_interface_output(self, output: str) -> list[dict]:
        """解析接口状态输出，兼容华为和思科"""
        rows: list[dict] = []
        lines = output.strip().splitlines()

        if self.vendor == "huawei":
            # 华为 display interface brief 格式:
            # Interface     IP Address      Physical  Protocol  VRF
            # GE0/0/1       unassigned      up        up        ...
            for line in lines:
                parts = line.split()
                if not parts or parts[0].startswith("-") or parts[0].startswith("Interface"):
                    continue
                # 跳过华为的 header
                if any(kw in line for kw in ["PHY", "Physical", "Protocol"]):
                    continue
                if len(parts) >= 4:
                    rows.append({
                        "interface": parts[0],
                        "status": parts[2].lower() if len(parts) > 2 else "unknown",
                        "protocol": parts[3].lower() if len(parts) > 3 else "",
                        "vlan": "",
                        "description": "",
                        "speed": "",
                    })
        else:
            # 思科 show interfaces status
            for line in lines:
                parts = line.split()
                if not parts or parts[0].startswith("-") or "Port" in line or "Name" in line:
                    continue
                if len(parts) >= 4:
                    rows.append({
                        "interface": parts[0],
                        "status": parts[1].lower() if len(parts) > 1 else "unknown",
                        "vlan": parts[2] if len(parts) > 2 else "",
                        "protocol": parts[3].lower() if len(parts) > 3 else "",
                        "description": "",
                        "speed": "",
                    })

        return rows