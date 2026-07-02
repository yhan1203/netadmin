"""VLAN 管理 — 查看、创建、删除、端口分配"""

from __future__ import annotations

from rich.table import Table
from rich.box import ROUNDED

from netadmin.config import DeviceConfig
from netadmin.commands import resolve
from netadmin.connector import Connector


class VlanManager:
    """VLAN 管理，封装厂商差异"""

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.vendor = config.get("vendor", "cisco").lower()

    def get_vlan_table(self) -> Table:
        """获取 VLAN 列表的 Rich 表格"""
        cmd = resolve("show_vlan", self.vendor)

        with Connector(self.config) as conn:
            output = conn.send_command(str(cmd))

        table = Table(title=f"VLAN List — {self.config['host']}", box=ROUNDED)
        table.add_column("VLAN ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Status")
        table.add_column("Ports", overflow="fold")

        # 解析输出（不同厂商格式不同）
        rows = self._parse_vlan_output(output)
        for row in rows:
            table.add_row(str(row["id"]), row["name"], row["status"], row.get("ports", ""))

        return table

    def create_vlan(self, vlan_id: int, name: str = "") -> str:
        """创建 VLAN"""
        cmds = resolve("create_vlan", self.vendor, vlan_id=str(vlan_id), vlan_name=name or f"VLAN_{vlan_id}")
        if isinstance(cmds, str):
            cmds = [cmds]

        with Connector(self.config) as conn:
            conn.send_config_set(cmds)
            save_cmd = resolve("save_config", self.vendor)
            self._save_with_confirm(conn, str(save_cmd))

        return f"VLAN {vlan_id} created" + (f" ({name})" if name else "")

    def delete_vlan(self, vlan_id: int) -> str:
        """删除 VLAN"""
        cmd = resolve("delete_vlan", self.vendor, vlan_id=str(vlan_id))

        with Connector(self.config) as conn:
            conn.send_config_set([str(cmd)])
            save_cmd = resolve("save_config", self.vendor)
            self._save_with_confirm(conn, str(save_cmd))

        return f"VLAN {vlan_id} deleted"

    def assign_port(self, port: str, vlan_id: int, mode: str = "access") -> str:
        """端口分配 VLAN

        Args:
            port: 接口名，如 "GigabitEthernet0/0/1"
            vlan_id: VLAN ID
            mode: access | trunk
        """
        if mode == "trunk":
            cmds = resolve("set_trunk_port", self.vendor, port=port, vlan_ids=str(vlan_id))
        else:
            cmds = resolve("set_access_port", self.vendor, port=port, vlan_id=str(vlan_id))

        if isinstance(cmds, str):
            cmds = [cmds]

        with Connector(self.config) as conn:
            conn.send_config_set(cmds)
            save_cmd = resolve("save_config", self.vendor)
            self._save_with_confirm(conn, str(save_cmd))

        return f"Port {port} assigned to VLAN {vlan_id} ({mode})"

    @staticmethod
    def _save_with_confirm(conn: Connector, save_cmd: str) -> None:
        """执行保存命令，处理华为的 [Y/N] 确认弹窗"""
        output = conn.send_command_timing(save_cmd, delay_factor=1)
        if "[Y/N]" in output or "[y/n]" in output.lower():
            conn.send_command_timing("Y", delay_factor=1)
        elif "(y/n)" in output.lower():
            conn.send_command_timing("y", delay_factor=1)

    def _parse_vlan_output(self, output: str) -> list[dict]:
        """解析 VLAN 输出，兼容华为和思科格式"""
        rows: list[dict] = []
        lines = output.strip().splitlines()

        vendor = self.vendor
        # 尝试从输出内容自动识别
        if "The total number of vlans" in output or "display vlan" in output.lower():
            vendor = "huawei"

        for line in lines:
            line = line.strip()
            if not line or line.startswith("-") or line.startswith("VLAN"):
                continue

            if vendor == "huawei":
                # 华为格式: 1    default    enable    GE0/0/1(U)
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    vlan_id = int(parts[0])
                    name = parts[1] if len(parts) > 1 else ""
                    status = parts[2] if len(parts) > 2 else "up"
                    ports = " ".join(parts[3:]) if len(parts) > 3 else ""
                    rows.append({"id": vlan_id, "name": name, "status": status, "ports": ports})
            else:
                # 思科格式: 1    default    active    Et0/0, Et0/1
                parts = line.split()
                if len(parts) >= 1 and parts[0].isdigit():
                    vlan_id = int(parts[0])
                    name = parts[1] if len(parts) > 1 else ""
                    status = parts[2] if len(parts) > 2 else "active"
                    ports = " ".join(parts[3:]) if len(parts) > 3 else ""
                    rows.append({"id": vlan_id, "name": name, "status": status, "ports": ports})

        return rows