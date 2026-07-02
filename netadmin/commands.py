"""厂商命令映射 — 不同厂商相同语义映射到不同的执行命令

\b
华为          思科          语义
─────        ──────        ───────────────
display vlan  show vlan     查看 VLAN 列表
display interface   show interfaces     查看接口
display version     show version        查看版本
display current-configuration   show running-config   查看配置
display mac-address  show mac address-table   查看 MAC 表
display logbuffer    show log         查看日志
display cpu-usage    show processes cpu   查看 CPU
display memory       show memory         查看内存
display lldp neighbor    show lldp neighbors   查看 LLDP 邻居
display stp         show spanning-tree   查看 STP
save                write memory        保存配置
system-view         configure terminal  进入配置模式
"""

from __future__ import annotations

# ── 命令映射表 ───────────────────────────────────────────
# 语义 → { 厂商: 实际命令 }

COMMAND_MAP: dict[str, dict[str, str | list[str]]] = {
    # ── 查看类 ──
    "show_vlan": {
        "huawei": "display vlan",
        "cisco": "show vlan brief",
    },
    "show_interface": {
        "huawei": "display interface brief",
        "cisco": "show interfaces status",
    },
    "show_interface_detail": {
        "huawei": "display interface",
        "cisco": "show interfaces",
    },
    "show_version": {
        "huawei": "display version",
        "cisco": "show version",
    },
    "show_running_config": {
        "huawei": "display current-configuration",
        "cisco": "show running-config",
    },
    "show_mac_table": {
        "huawei": "display mac-address",
        "cisco": "show mac address-table",
    },
    "show_log": {
        "huawei": "display logbuffer",
        "cisco": "show log",
    },
    "show_cpu": {
        "huawei": "display cpu-usage",
        "cisco": "show processes cpu",
    },
    "show_memory": {
        "huawei": "display memory",
        "cisco": "show process memory",
    },
    "show_lldp_neighbors": {
        "huawei": "display lldp neighbor",
        "cisco": "show lldp neighbors",
    },
    "show_stp": {
        "huawei": "display stp brief",
        "cisco": "show spanning-tree brief",
    },
    "show_ntp": {
        "huawei": "display ntp status",
        "cisco": "show ntp status",
    },
    "show_snmp": {
        "huawei": "display snmp-agent sys-info",
        "cisco": "show snmp",
    },
    "show_environment": {
        "huawei": "display device temperature",
        "cisco": "show environment",
    },
    "show_interface_description": {
        "huawei": "display interface description",
        "cisco": "show interfaces description",
    },
    # ── 操作类 ──
    "save_config": {
        "huawei": "save",
        "cisco": "write memory",
    },
    "enter_config_mode": {
        "huawei": "system-view",
        "cisco": "configure terminal",
    },
    "show_link_aggregation": {
        "huawei": "display eth-trunk",
        "cisco": "show etherchannel summary",
    },
    "show_stp_detail": {
        "huawei": "display stp",
        "cisco": "show spanning-tree",
    },
    "show_ip_interface": {
        "huawei": "display ip interface brief",
        "cisco": "show ip interface brief",
    },
    "show_arp": {
        "huawei": "display arp",
        "cisco": "show ip arp",
    },
    "show_cdp": {
        "huawei": "display cdp",          # 部分华为也支持 CDP
        "cisco": "show cdp neighbors",
    },
}

# ── VLAN 配置模板 ────────────────────────────────────────

VLAN_COMMANDS: dict[str, dict[str, str | list[str]]] = {
    "create_vlan": {
        "huawei": [
            "vlan batch {vlan_id}",      # 批量创建
            "vlan {vlan_id}",
            "name {vlan_name}",
        ],
        "cisco": [
            "vlan {vlan_id}",
            "name {vlan_name}",
        ],
    },
    "delete_vlan": {
        "huawei": "undo vlan {vlan_id}",
        "cisco": "no vlan {vlan_id}",
    },
    "set_access_port": {
        "huawei": [
            "interface {port}",
            "port link-type access",
            "port default vlan {vlan_id}",
        ],
        "cisco": [
            "interface {port}",
            "switchport mode access",
            "switchport access vlan {vlan_id}",
        ],
    },
    "set_trunk_port": {
        "huawei": [
            "interface {port}",
            "port link-type trunk",
            "port trunk allow-pass vlan {vlan_ids}",
        ],
        "cisco": [
            "interface {port}",
            "switchport mode trunk",
            "switchport trunk allowed vlan {vlan_ids}",
        ],
    },
}


def resolve(cmd_name: str, vendor: str, **fmt_args: str) -> str | list[str]:
    """解析语义命令名为具体厂商命令，支持格式化

    Args:
        cmd_name: 语义命令名，如 "show_vlan"
        vendor: 厂商名 "huawei" 或 "cisco"
        **fmt_args: 格式化参数

    Returns:
        具体命令字符串或命令列表
    """
    vendor = vendor.lower()

    # 先查命令映射
    cmd_map = COMMAND_MAP.get(cmd_name) or VLAN_COMMANDS.get(cmd_name)
    if not cmd_map:
        return f"echo 'Unknown command: {cmd_name}'"

    entry = cmd_map.get(vendor, cmd_map.get("cisco", cmd_map.get("huawei", "echo 'No vendor mapping'")))
    if isinstance(entry, list):
        lines = [line.format(**fmt_args) for line in entry]
        return lines
    return entry.format(**fmt_args)


def list_commands(vendor: str) -> list[tuple[str, str]]:
    """列出指定厂商的所有可用命令"""
    result: list[tuple[str, str]] = []
    for name, mapping in COMMAND_MAP.items():
        cmd = mapping.get(vendor) or mapping.get("cisco", "")
        if isinstance(cmd, list):
            cmd = "; ".join(cmd)
        result.append((name, str(cmd)))
    return sorted(result)