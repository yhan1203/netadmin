#!/usr/bin/env python3
"""
netadmin 产品演示脚本 — 无需真实设备，展示功能面貌

用法:
  python3 demo.py

效果:
  模拟各种命令的输出，展示 Rich 终端 UI 效果
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 确保包可导入
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box
from rich.columns import Columns

console = Console()


def demo_banner() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold cyan]netadmin[/] — [green]华为 & 思科统一交换机管理工具[/]\n"
        "[dim]以下为演示输出，无需真实设备[/]",
        border_style="cyan",
    ))
    console.print()


def demo_scan() -> None:
    console.rule("[bold]1. 网段设备发现 [dim]netadmin scan 192.168.1.0/24[/]")

    table = Table(box=box.ROUNDED)
    table.add_column("IP", style="cyan")
    table.add_column("Hostname")
    table.add_column("Vendor")
    table.add_column("Open Ports")
    table.add_column("Response Time")

    table.add_row("192.168.1.1", "core-sw-a", "huawei", "22, 161", "0.12s")
    table.add_row("192.168.1.2", "access-sw-b", "cisco", "22, 23, 161", "0.08s")
    table.add_row("192.168.1.3", "access-sw-c", "huawei", "22", "0.15s")
    table.add_row("192.168.1.100", "server-nas", "unknown", "22, 443, 80", "0.03s")
    table.add_row("192.168.1.254", "router-gw", "unknown", "22, 443", "0.05s")

    console.print(table)
    console.print("[dim]✓ 发现 5 台设备，其中 3 台交换机[/]\n")


def demo_backup() -> None:
    console.rule("[bold]2. 配置备份 [dim]netadmin backup run[/]")

    table = Table(box=box.SIMPLE)
    table.add_column("Device", style="cyan")
    table.add_column("Status")
    table.add_column("Path")

    table.add_row("192.168.1.1", "[green]✓[/]", "backups/192.168.1.1_20260702_093000.cfg")
    table.add_row("192.168.1.2", "[green]✓[/]", "backups/192.168.1.2_20260702_093002.cfg")
    table.add_row("192.168.1.3", "[green]✓[/]", "backups/192.168.1.3_20260702_093005.cfg")

    console.print(table)

    console.print("\n[bold]备份历史:[/]")
    hist = Table(box=box.SIMPLE)
    hist.add_column("ID", style="dim")
    hist.add_column("Device", style="cyan")
    hist.add_column("Version")
    hist.add_column("Time", style="green")
    hist.add_column("Size")
    hist.add_column("Comment")

    hist.add_row("1", "192.168.1.1", "20260702_093000", "2026-07-02T09:30:00", "12.5KB", "每日自动备份")
    hist.add_row("2", "192.168.1.2", "20260702_093002", "2026-07-02T09:30:02", "8.1KB", "")
    hist.add_row("3", "192.168.1.3", "20260702_093005", "2026-07-02T09:30:05", "8.3KB", "")

    console.print(hist)
    console.print()


def demo_learn_apply() -> None:
    console.rule("[bold]3. 🔥 照猫画虎 [dim]配置学习 → 模板 → 部署[/]")

    # Step 1: learn
    console.print("[bold]Step 1:[/] [cyan]netadmin learn 192.168.1.1 -o template.yaml[/]")

    template_yaml = """\
device:
  hostname: "{{HOSTNAME}}"
  vendor: huawei
  model: S5735S-L24T4S-A

vlans:
  - id: 10;  name: office
  - id: 20;  name: voip
  - id: 30;  name: guest
  - id: 99;  name: management

interfaces:
  - name: GigabitEthernet0/0/1;   mode: trunk;   vlans: "10 20 30"
  - name: GigabitEthernet0/0/2;   mode: access;  vlans: "10";    desc: "Office-01"
  - name: GigabitEthernet0/0/3;   mode: access;  vlans: "10";    desc: "Office-02"
  - name: GigabitEthernet0/0/24;  mode: trunk;   vlans: "99";    desc: "Management"

ntp:
  servers: ["ntp.example.com"]
  timezone: CST+8

snmp:
  community: ["netadmin-ro"]
  location: "IDC-Room-A"

stp:
  mode: mstp
  root_primary: true
"""

    console.print(Syntax(template_yaml, "yaml", theme="monokai", word_wrap=True))

    # Step 2: apply
    console.print("\n[bold]Step 2:[/] [cyan]netadmin apply template.yaml -d 192.168.1.2 --dry-run[/]")
    console.print("[yellow]Dry run mode — 以下命令将被执行到 192.168.1.2:[/]")

    dry_run_commands = [
        "sysname ACCESS-SW-B",
        "vlan batch 10 20 30 99",
        "vlan 10", "name office",
        "vlan 20", "name voip",
        "vlan 30", "name guest",
        "vlan 99", "name management",
        "interface GigabitEthernet0/0/1", "port link-type trunk", "port trunk allow-pass vlan 10 20 30",
        "interface GigabitEthernet0/0/2", "port link-type access", "port default vlan 10", "description Office-01",
        "interface GigabitEthernet0/0/3", "port link-type access", "port default vlan 10", "description Office-02",
        "interface GigabitEthernet0/0/24", "port link-type trunk", "port trunk allow-pass vlan 99", "description Management",
        "stp mode mstp", "stp root primary",
        "ntp server ntp.example.com",
        "snmp-agent community read netadmin-ro",
        "return", "save",
    ]

    result_table = Table(box=box.SIMPLE)
    result_table.add_column("#", style="dim", width=3)
    result_table.add_column("Command", overflow="fold")
    result_table.add_column("Status")

    for i, cmd in enumerate(dry_run_commands[:8], 1):
        result_table.add_row(str(i), cmd, "[yellow]dry-run[/]")

    result_table.add_row("...", f"... ({len(dry_run_commands)} commands total)", "[yellow]dry-run[/]")
    console.print(result_table)

    console.print("\n[yellow]⚠ 试运行模式 — 未实际执行，正式部署去掉 --dry-run 即可[/]")
    console.print()


def demo_check() -> None:
    console.rule("[bold]4. 健康检查 [dim]netadmin check --all[/]")

    p1 = Panel.fit(
        "[bold]CPU:[/]       23%\n"
        "[bold]Memory:[/]    45%\n"
        "[bold]Temp:[/]      42°C\n"
        "[bold]Uptime:[/]    120 days\n"
        "[bold]Log Errors:[/] 0 (clean)\n"
        "[bold]Model:[/]     S5735S-L24T4S-A",
        title="Health — 192.168.1.1 (huawei)",
        border_style="green",
    )
    p2 = Panel.fit(
        "[bold]CPU:[/]       67% [yellow]⚠[/]\n"
        "[bold]Memory:[/]    82% [red]⚠ HIGH[/]\n"
        "[bold]Temp:[/]      55°C [yellow]⚠[/]\n"
        "[bold]Uptime:[/]    365 days\n"
        "[bold]Log Errors:[/] 5\n"
        "[bold]Model:[/]     WS-C2960X-24PS-L",
        title="Health — 192.168.1.2 (cisco)",
        border_style="yellow",
    )
    p3 = Panel.fit(
        "[bold]CPU:[/]       5%\n"
        "[bold]Memory:[/]    22%\n"
        "[bold]Temp:[/]      38°C\n"
        "[bold]Uptime:[/]    30 days\n"
        "[bold]Log Errors:[/] 0 (clean)\n"
        "[bold]Model:[/]     S5735S-L24T4S-A",
        title="Health — 192.168.1.3 (huawei)",
        border_style="green",
    )

    console.print(Columns([p1, p2, p3]))
    console.print()


def demo_audit() -> None:
    console.rule("[bold]5. 安全审计 [dim]netadmin audit 192.168.1.1[/]")

    console.print("[bold]192.168.1.1[/] — Security Score: [green]80/100[/]")

    table = Table(box=box.SIMPLE)
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Detail")

    checks = [
        ("Password Encryption", "[green]PASS[/]", "service password-encryption enabled"),
        ("Enable Secret", "[red]FAIL[/]", "Use 'enable secret' instead of 'enable password'"),
        ("SNMP Community", "[green]PASS[/]", "Custom community string in use"),
        ("SSH Version", "[green]PASS[/]", "SSH v2 configured"),
        ("VTY ACL", "[red]FAIL[/]", "No ACL on VTY — management access unrestricted"),
        ("Login Banner", "[green]PASS[/]", "Banner is configured"),
        ("Default VLAN 1", "[green]PASS[/]", "VLAN 1 not in use on access ports"),
        ("Logging", "[green]PASS[/]", "Logging configured"),
        ("NTP", "[red]FAIL[/]", "No NTP configured — clocks may drift"),
    ]

    for check, status, detail in checks:
        table.add_row(check, status, detail)

    console.print(table)
    console.print()


def demo_vlan() -> None:
    console.rule("[bold]6. VLAN 管理 [dim]netadmin vlan list 192.168.1.1[/]")

    table = Table(title="VLAN List — 192.168.1.1", box=box.ROUNDED)
    table.add_column("VLAN ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Status")
    table.add_column("Ports")

    table.add_row("1", "default", "enable", "GE0/0/0(U)")
    table.add_row("10", "office", "enable", "GE0/0/2(U) GE0/0/3(U) GE0/0/4(U)")
    table.add_row("20", "voip", "enable", "GE0/0/5(U) GE0/0/6(U)")
    table.add_row("30", "guest", "enable", "GE0/0/7(U)")
    table.add_row("99", "management", "enable", "GE0/0/24(U)")

    console.print(table)
    console.print()


def demo_interface() -> None:
    console.rule("[bold]7. 接口状态 [dim]netadmin interface list 192.168.1.1[/]")

    table = Table(title="Interface Status — 192.168.1.1", box=box.ROUNDED)
    table.add_column("Interface", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Protocol")
    table.add_column("VLAN")
    table.add_column("Description")

    iface_data = [
        ("GE0/0/1", "up", "up", "trunk", "Uplink to Core"),
        ("GE0/0/2", "up", "up", "10", "Office-01"),
        ("GE0/0/3", "up", "up", "10", "Office-02"),
        ("GE0/0/4", "down", "down", "-", "[empty]"),
        ("GE0/0/5", "up", "up", "20", "VoIP-01"),
        ("GE0/0/6", "up", "up", "20", "VoIP-02"),
        ("GE0/0/7", "up", "up", "30", "Guest WiFi"),
        ("GE0/0/24", "up", "up", "99", "Management"),
    ]

    for name, status, proto, vlan, desc in iface_data:
        s = f"[green]{status}[/]" if status == "up" else f"[red]{status}[/]"
        table.add_row(name, s, proto, vlan, desc)

    console.print(table)
    console.print()


def main() -> None:
    demo_banner()
    demo_scan()
    demo_check()
    demo_backup()
    demo_vlan()
    demo_interface()
    demo_learn_apply()
    demo_audit()

    console.rule("[bold]🎬 演示结束[/]")
    console.print("\n以上输出仅为演示，模拟了 netadmin 各命令的终端效果。")
    console.print("有真实设备时运行 [bold]netadmin connect <host>[/] 开始连接。")
    console.print()
    console.print("[dim]需要截实际截图？连接真实设备后运行：[/]")
    console.print("[dim]  netadmin check --all[/]")
    console.print("[dim]  netadmin backup run[/]")
    console.print("[dim]  netadmin vlan list <host>[/]")


if __name__ == "__main__":
    main()