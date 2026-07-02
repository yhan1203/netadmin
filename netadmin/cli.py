"""netadmin CLI — Click 入口

所有命令都走这里。使用 Rich 输出终端样式。
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box

from netadmin import __version__
from netadmin.config import Settings
from netadmin.connector import Connector, test_connection, ConnectorError
from netadmin.commands import list_commands
from netadmin.backup import BackupManager
from netadmin.learn import ConfigLearner
from netadmin.apply import ConfigApplier
from netadmin.interface import InterfaceInfo
from netadmin.vlan import VlanManager
from netadmin.scanner import NetworkScanner
from netadmin.checker import HealthChecker
from netadmin.scheduler import BackupScheduler, CrontabExpression, parse_interval
from netadmin.notifier import AlertNotifier

console = Console()
settings = Settings()

# pylint: disable=too-many-arguments,no-value-for-parameter


# ── 全局选项 ─────────────────────────────────────────────


@click.group(invoke_without_command=False)
@click.version_option(version=__version__, prog_name="netadmin")
@click.option("--config", "-c", help="配置文件路径", envvar="NETADMIN_CONFIG")
def cli(config: str | None) -> None:
    """netadmin — 华为/思科统一交换机管理工具

    一个 CLI 工具，同时管理华为和思科网络设备。
    """
    global settings  # noqa: PLW0603
    if config:
        settings = Settings(config)


# ── connect ──────────────────────────────────────────────


@cli.command()
@click.argument("host")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
@click.option("--device-type", "-t", help="设备类型 (huawei/cisco_ios)")
@click.option("--port", default=22, help="SSH 端口", type=int)
def connect(host: str, username: str | None, password: str | None, device_type: str | None, port: int) -> None:
    """SSH 连接到设备并检测"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "", port=port)
    if device_type:
        cfg["device_type"] = device_type

    with console.status(f"Connecting to {host}..."):
        result = test_connection(
            host=host,
            username=username or cfg["username"],
            password=password or cfg["password"],
            port=port or cfg["port"],
            device_type=device_type or cfg["device_type"],
        )

    if result["success"]:
        console.print(Panel.fit(
            f"[bold green]✓ Connected[/]\n"
            f"  Prompt: {result['prompt']}\n"
            f"  Vendor: {result['vendor']}\n"
            f"  Time:   {result['elapsed']}s",
            title=f"Device {host}",
        ))
    else:
        console.print(f"[bold red]✗ Connection failed:[/] {result['error']}")
        sys.exit(1)


# ── exec ─────────────────────────────────────────────────


@cli.command()
@click.argument("host")
@click.argument("command")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def exec_cmd(host: str, command: str, username: str | None, password: str | None) -> None:
    """在单台设备上执行命令"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    try:
        with Connector(cfg) as conn:
            console.print(f"[dim]{conn.get_prompt()}[/]")
            output = conn.send_command(command)
            console.print(Syntax(output, "bash", theme="monokai", word_wrap=True))
    except ConnectorError as e:
        console.print(f"[bold red]✗ {e}[/]")
        sys.exit(1)


@cli.command(name="exec-all")
@click.argument("command")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
@click.option("--device", "-d", multiple=True, help="目标设备（可多次），不传则对所有设备执行")
def exec_all(command: str, username: str | None, password: str | None, device: tuple[str, ...]) -> None:
    """批量在所有（或指定）设备上执行命令"""
    devices = _resolve_devices(device, username, password)
    table = Table(title="Batch Execute Results", box=box.ROUNDED)
    table.add_column("Device", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Output (first 5 lines)", overflow="fold")

    failed = 0
    for dev in devices:
        try:
            with Connector(dev) as conn:
                output = conn.send_command(command)
            lines = output.split("\n")[:5]
            snippet = "\n".join(lines) if lines else "(empty)"
            table.add_row(dev["host"], "[green]OK[/]", snippet)
        except ConnectorError as e:
            table.add_row(dev["host"], "[red]FAIL[/]", str(e)[:80])
            failed += 1

    console.print(table)
    if failed:
        console.print(f"\n[yellow]⚠ {failed}/{len(devices)} devices failed[/]")
        if failed == len(devices):
            sys.exit(1)


# ── commands ─────────────────────────────────────────────


@cli.command()
@click.option("--vendor", "-v", default="cisco", help="厂商 (huawei/cisco)")
def commands(vendor: str) -> None:
    """列出内置命令模板"""
    cmds = list_commands(vendor)
    table = Table(title=f"Available Commands ({vendor})", box=box.SIMPLE)
    table.add_column("Semantic Name", style="cyan")
    table.add_column("Command", style="green")
    for name, cmd in cmds:
        table.add_row(name, cmd)
    console.print(table)


# ── vlan ─────────────────────────────────────────────────


@cli.group()
def vlan() -> None:
    """VLAN 管理"""


@vlan.command(name="list")
@click.argument("host")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def vlan_list(host: str, username: str | None, password: str | None) -> None:
    """查看设备的 VLAN 列表"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    mgr = VlanManager(cfg)
    table = mgr.get_vlan_table()
    console.print(table)


@vlan.command()
@click.argument("host")
@click.argument("vlan_id", type=int)
@click.argument("name", default="")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def create(host: str, vlan_id: int, name: str, username: str | None, password: str | None) -> None:
    """创建 VLAN"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    mgr = VlanManager(cfg)
    result = mgr.create_vlan(vlan_id, name)
    console.print(f"[green]✓[/] {result}")


@vlan.command()
@click.argument("host")
@click.argument("vlan_id", type=int)
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def delete(host: str, vlan_id: int, username: str | None, password: str | None) -> None:
    """删除 VLAN"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    mgr = VlanManager(cfg)
    result = mgr.delete_vlan(vlan_id)
    console.print(f"[green]✓[/] {result}")


@vlan.command()
@click.argument("host")
@click.argument("port")
@click.argument("vlan_id", type=int)
@click.option("--mode", default="access", help="端口模式: access|trunk")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def assign(host: str, port: str, vlan_id: int, mode: str, username: str | None, password: str | None) -> None:
    """端口分配 VLAN"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    mgr = VlanManager(cfg)
    result = mgr.assign_port(port, vlan_id, mode)
    console.print(f"[green]✓[/] {result}")


# ── interface ────────────────────────────────────────────


@cli.group()
def interface() -> None:
    """接口状态管理"""


@interface.command(name="list")
@click.argument("host")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def interface_list(host: str, username: str | None, password: str | None) -> None:
    """查看设备接口状态"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    info = InterfaceInfo(cfg)
    table = info.get_interface_table()
    console.print(table)


@interface.command()
@click.argument("host")
@click.argument("interface_name")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def detail(host: str, interface_name: str, username: str | None, password: str | None) -> None:
    """查看单个接口详情"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    info = InterfaceInfo(cfg)
    details = info.get_interface_detail(interface_name)
    console.print(Panel(details, title=f"Interface {interface_name}"))


# ── backup ───────────────────────────────────────────────


@cli.group()
def backup() -> None:
    """配置备份管理"""


@backup.command()
@click.argument("host", required=False)
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
@click.option("--comment", "-m", help="备份备注")
def run(host: str | None, username: str | None, password: str | None, comment: str | None) -> None:
    """备份设备配置（不指定 host 则备份全部）"""
    mgr = BackupManager(settings)

    if host:
        cfg = settings.resolve_device(host, username=username or "", password=password or "")
        devices_to_backup = [cfg]
    else:
        devices_to_backup = _resolve_devices(()) if not settings.all_devices() else settings.all_devices()

    for dev in devices_to_backup:
        with console.status(f"Backing up {dev['host']}..."):
            try:
                path, version = mgr.backup(dev, comment or "")
                console.print(f"[green]✓[/] {dev['host']} → [{version}] {path}")
            except ConnectorError as e:
                console.print(f"[red]✗[/] {dev['host']}: {e}")


@backup.command(name="list")
@click.option("--host", help="筛选设备")
def backup_list(host: str | None) -> None:
    """查看备份历史"""
    mgr = BackupManager(settings)
    records = mgr.list_backups(host)
    table = Table(title="Backup History", box=box.ROUNDED)
    table.add_column("ID", style="dim")
    table.add_column("Device", style="cyan")
    table.add_column("Version")
    table.add_column("Time", style="green")
    table.add_column("Size", style="blue")
    table.add_column("Comment")
    for r in records:
        table.add_row(str(r["id"]), r["device"], r["version"], r["timestamp"], r["size"], r.get("comment", ""))
    console.print(table)


@backup.command()
@click.argument("id_a", type=int)
@click.argument("id_b", type=int)
def diff(id_a: int, id_b: int) -> None:
    """对比两个备份版本的差异"""
    mgr = BackupManager(settings)
    diff_text = mgr.diff_backups(id_a, id_b)
    if diff_text is None:
        console.print("[red]Backup record not found[/]")
        sys.exit(1)
    if not diff_text:
        console.print("[yellow]No differences[/]")
        return
    console.print(Syntax(diff_text, "diff", theme="monokai", word_wrap=True))


@backup.command()
@click.argument("id", type=int)
def restore(id: int) -> None:
    """查看某个备份版本的内容"""
    mgr = BackupManager(settings)
    content = mgr.get_backup_content(id)
    if content is None:
        console.print("[red]Backup record not found[/]")
        sys.exit(1)
    console.print(Syntax(content, "bash", theme="monokai", word_wrap=True))


# ── backup schedule ──────────────────────────────────────────


@backup.group()
def schedule() -> None:
    """定时备份调度管理"""


@schedule.command()
@click.option("--name", "-n", required=True, help="调度任务名称")
@click.option("--interval", "-i", required=True, help="时间间隔: 30m, 1h, daily, hourly, 或 crontab 表达式 (如 '0 2 * * *')")
@click.option("--desc", "-d", default="", help="描述")
def add(name: str, interval: str, desc: str) -> None:
    """添加定时备份任务"""
    try:
        crontab = parse_interval(interval)
    except ValueError as e:
        console.print(f"[red]✗ {e}[/]")
        sys.exit(1)

    sched = BackupScheduler(settings)
    try:
        expr = CrontabExpression(*crontab.split(), raw=crontab)
        description = desc or expr.describe()
        sched_id = sched.add(name, crontab, description)
        console.print(f"[green]✓[/] Schedule added (ID: {sched_id}) — [bold]{name}[/]")
        console.print(f"    Cron: {crontab} ({description})")
    finally:
        sched.close()


@schedule.command(name="list")
def schedule_list() -> None:
    """查看所有定时备份任务"""
    sched = BackupScheduler(settings)
    try:
        entries = sched.list_schedules()
        if not entries:
            console.print("[yellow]No schedules configured[/]")
            console.print("  Use: [bold]netadmin backup schedule add --name NAME --interval INTERVAL[/]")
            return

        table = Table(title="Backup Schedules", box=box.ROUNDED)
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Crontab")
        table.add_column("Description")
        table.add_column("Enabled")
        table.add_column("Last Run")
        table.add_column("Result")

        for e in entries:
            enabled = "[green]✓[/]" if e.enabled else "[dim]✗[/]"
            last_run = e.last_run or "[dim]never[/]"
            result = e.last_result or ""
            if result == "OK":
                result = "[green]OK[/]"
            elif result == "FAIL":
                result = "[red]FAIL[/]"
            table.add_row(str(e.id), e.name, e.crontab, e.description,
                          enabled, last_run, result)
        console.print(table)
    finally:
        sched.close()


@schedule.command()
@click.argument("schedule_id", type=int)
def remove(schedule_id: int) -> None:
    """删除定时备份任务"""
    sched = BackupScheduler(settings)
    try:
        if sched.remove(schedule_id):
            console.print(f"[green]✓[/] Schedule {schedule_id} removed")
        else:
            console.print(f"[red]✗[/] Schedule {schedule_id} not found")
            sys.exit(1)
    finally:
        sched.close()


@schedule.command()
@click.argument("schedule_id", type=int)
@click.argument("enabled", type=click.Choice(["true", "false"]))
def toggle(schedule_id: int, enabled: str) -> None:
    """启用/禁用定时备份任务"""
    sched = BackupScheduler(settings)
    try:
        is_enabled = enabled == "true"
        if sched.toggle(schedule_id, is_enabled):
            status = "enabled" if is_enabled else "disabled"
            console.print(f"[green]✓[/] Schedule {schedule_id} {status}")
        else:
            console.print(f"[red]✗[/] Schedule {schedule_id} not found")
            sys.exit(1)
    finally:
        sched.close()


@schedule.command()
def run() -> None:
    """立即执行所有定时备份任务"""
    sched = BackupScheduler(settings)
    try:
        entries = sched.list_schedules()
        enabled_entries = [e for e in entries if e.enabled]
        if not enabled_entries:
            console.print("[yellow]No enabled schedules to run[/]")
            return

        console.print(f"Running [bold]{len(enabled_entries)}[/] schedule(s)...\n")
        results = sched.run_scheduled_backups()

        for r in results:
            status = "[green]OK[/]" if r["success"] else "[red]FAIL[/]"
            console.print(f"  [{r['schedule_id']}] {r['name']} — {status}")
            for dev in r.get("devices", []):
                if dev.get("success"):
                    console.print(f"       ✓ {dev['host']} → {dev['version']}")
                else:
                    console.print(f"       ✗ {dev['host']}: {dev.get('error', 'unknown')}")
            if "error" in r:
                console.print(f"       [yellow]⚠ {r['error']}[/]")

        success_count = sum(1 for r in results if r["success"])
        console.print(f"\n[bold]{'All schedules completed' if success_count == len(results) else f'{success_count}/{len(results)} schedules OK'}[/]")
    finally:
        sched.close()


# ── learn (照猫) ─────────────────────────────────────────


@cli.command()
@click.argument("host")
@click.option("--output", "-o", help="输出模板路径（默认打印到终端）")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
def learn(host: str, output: str | None, username: str | None, password: str | None) -> None:
    """从设备学习配置，生成可复用模板（照猫）"""
    cfg = settings.resolve_device(host, username=username or "", password=password or "")
    learner = ConfigLearner(cfg)

    with console.status(f"Learning from {host}..."):
        template = learner.learn()

    if output:
        dst = Path(output)
        dst.write_text(template.raw_yaml, encoding="utf-8")
        console.print(f"[green]✓[/] Template saved to [bold]{dst}[/]")
    else:
        console.print(Syntax(template.raw_yaml, "yaml", theme="monokai", word_wrap=True))

    console.print(f"\n[dim]Learned: VLANs={len(template.vlans)}, Interfaces={len(template.interfaces)}, "
                  f"NTP={'yes' if template.ntp else 'no'}, SNMP={'yes' if template.snmp else 'no'}[/]")


# ── apply (画虎) ─────────────────────────────────────────


@cli.command()
@click.argument("template")
@click.option("--device", "-d", required=True, help="目标设备 host（支持逗号分隔多个）")
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
@click.option("--dry-run", is_flag=True, help="试运行，不实际执行")
def apply(template: str, device: str, username: str | None, password: str | None, dry_run: bool) -> None:
    """按模板配置目标设备（画虎）"""

    targets = [h.strip() for h in device.split(",")]
    applier = ConfigApplier()

    for target_host in targets:
        cfg = settings.resolve_device(target_host, username=username or "", password=password or "")

        console.rule(f"[bold]Applying to {target_host}")
        if dry_run:
            console.print("[yellow]Dry run mode — no changes will be made[/]")

        results = applier.apply(template, cfg, dry_run=dry_run)

        # 结果表格
        result_table = Table(box=box.SIMPLE)
        result_table.add_column("#", style="dim")
        result_table.add_column("Action", style="cyan")
        result_table.add_column("Status")
        result_table.add_column("Detail", overflow="fold")

        success_count = 0
        for i, r in enumerate(results, 1):
            status_icon = "[green]✓[/]" if r["success"] else "[red]✗[/]"
            result_table.add_row(str(i), r["command"], status_icon, r.get("output", "")[:60])
            if r["success"]:
                success_count += 1

        console.print(result_table)
        if success_count == len(results):
            console.print(f"[bold green]✓ All {len(results)} steps applied successfully[/]")
        else:
            console.print(f"[yellow]⚠ {len(results) - success_count}/{len(results)} steps failed[/]")


# ── scan ─────────────────────────────────────────────────


@cli.command()
@click.argument("subnet", required=False)
@click.option("--timeout", default=3, help="Ping 超时（秒）", type=int)
@click.option("--threads", default=50, help="并发数", type=int)
def scan(subnet: str, timeout: int, threads: int) -> None:
    """扫描网段发现网络设备"""
    if not subnet:
        subnet = "192.168.1.0/24"
        console.print("[yellow]No subnet specified, defaulting to 192.168.1.0/24[/]")

    scanner = NetworkScanner()
    with console.status(f"Scanning {subnet}..."):
        devices = scanner.scan(subnet, timeout=timeout, max_workers=threads)

    if not devices:
        console.print("[yellow]No devices found[/]")
        return

    table = Table(title=f"Discovered Devices ({len(devices)})", box=box.ROUNDED)
    table.add_column("IP", style="cyan")
    table.add_column("Hostname")
    table.add_column("Vendor")
    table.add_column("Open Ports")
    table.add_column("Response Time")

    for d in devices:
        table.add_row(d["ip"], d.get("hostname", ""), d.get("vendor", ""),
                      d.get("open_ports", ""), d.get("response_time", ""))

    console.print(table)


# ── check ────────────────────────────────────────────────


@cli.command()
@click.argument("host", required=False)
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
@click.option("--all", "check_all", is_flag=True, help="检查所有设备")
@click.option("--notify", "-n", is_flag=True, help="发现异常时推送通知（需配置 config.yaml notifications）")
def check(host: str | None, username: str | None, password: str | None, check_all: bool, notify: bool) -> None:
    """设备健康检查（CPU/内存/温度/日志错误）"""
    checker = HealthChecker()
    notifier = AlertNotifier(settings.notifications) if notify else None

    if check_all or not host:
        targets = _resolve_devices(())
    elif host:
        targets = [settings.resolve_device(host, username=username or "", password=password or "")]
    else:
        targets = _resolve_devices(())

    any_issue = False

    for dev in targets:
        with console.status(f"Checking {dev['host']}..."):
            report = checker.check(dev)

        if "error" in report:
            console.print(f"[red]✗ {dev['host']}: {report['error']}[/]")
            any_issue = True
            continue

        p = Panel.fit(
            f"[bold]CPU:[/]       {report.get('cpu', 'N/A')}\n"
            f"[bold]Memory:[/]    {report.get('memory', 'N/A')}\n"
            f"[bold]Temp:[/]      {report.get('temperature', 'N/A')}\n"
            f"[bold]Uptime:[/]    {report.get('uptime', 'N/A')}\n"
            f"[bold]Log Errors:[/] {report.get('log_errors', 'N/A')}\n"
            f"[bold]Model:[/]     {report.get('model', 'N/A')}\n"
            f"[bold]Version:[/]   {report.get('version', 'N/A')}",
            title=f"Health — {dev['host']}",
        )
        console.print(p)

        # 推送通知
        if notifier:
            sent = notifier.send_health_alert(report, dev["host"])
            if sent:
                console.print(f"  [dim]🔔 Alert sent via {', '.join(sent)}[/]")

    if notify and not notifier.is_configured():
        console.print("[yellow]⚠ --notify specified but no notification channels configured in config.yaml[/]")


# ── audit ────────────────────────────────────────────────


@cli.command()
@click.argument("host", required=False)
@click.option("--username", "-u", help="用户名")
@click.option("--password", "-p", help="密码")
@click.option("--all", "audit_all", is_flag=True, help="审计所有设备")
@click.option("--notify", "-n", is_flag=True, help="发现风险时推送通知（需配置 config.yaml notifications）")
def audit(host: str | None, username: str | None, password: str | None, audit_all: bool, notify: bool) -> None:
    """安全合规审计"""
    from netadmin.checker import SecurityAuditor

    auditor = SecurityAuditor()
    notifier = AlertNotifier(settings.notifications) if notify else None

    if audit_all or not host:
        targets = _resolve_devices(())
    elif host:
        targets = [settings.resolve_device(host, username=username or "", password=password or "")]
    else:
        targets = _resolve_devices(())

    for dev in targets:
        with console.status(f"Auditing {dev['host']}..."):
            report = auditor.audit(dev)

        if "error" in report:
            console.print(f"[red]✗ {dev['host']}: {report['error']}[/]")
            continue

        # 安全评分
        score = report.get("score", 0)
        color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        console.print(f"\n[bold]{dev['host']}[/] — Security Score: [{color}]{score}/100[/]")

        findings_table = Table(box=box.SIMPLE)
        findings_table.add_column("Check", style="cyan")
        findings_table.add_column("Status")
        findings_table.add_column("Detail", overflow="fold")

        for finding in report.get("findings", []):
            status_icon = "[green]PASS[/]" if finding["passed"] else "[red]FAIL[/]"
            findings_table.add_row(finding["check"], status_icon, finding.get("detail", ""))
        console.print(findings_table)

        # 推送通知
        if notifier:
            sent = notifier.send_audit_alert(report, dev["host"])
            if sent:
                console.print(f"  [dim]🔔 Alert sent via {', '.join(sent)}[/]")

    if notify and not notifier.is_configured():
        console.print("[yellow]⚠ --notify specified but no notification channels configured in config.yaml[/]")


# ── 辅助 ─────────────────────────────────────────────────


def _resolve_devices(hosts: tuple[str, ...] | None = None,
                     username: str | None = None,
                     password: str | None = None) -> list:
    """解析设备列表"""
    if hosts:
        return [settings.resolve_device(h, username=username or "", password=password or "") for h in hosts]

    devices = settings.all_devices()
    if not devices:
        if username or password:
            console.print("[yellow]No devices configured in config.yaml. Use -d HOST to target specific devices, or create a config.yaml with your devices.[/]")
        else:
            console.print("[yellow]No devices configured. Create a config.yaml file or pass device details via command line options.[/]")
        sys.exit(1)
    if username or password:
        for d in devices:
            if username:
                d["username"] = username
            if password:
                d["password"] = password
    return devices


# ── web ──────────────────────────────────────────────────────


@cli.command()
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", "-p", default=8099, type=int, help="监听端口")
@click.option("--reload", is_flag=True, help="热重载（开发用）")
def web(host: str, port: int, reload: bool) -> None:
    """启动 Web 仪表盘 (FastAPI + HTMX)"""
    console.print(f"[bold green]✓[/] Starting web dashboard at [underline]http://{host}:{port}[/]")
    console.print("[dim]Press Ctrl+C to stop[/]")
    from netadmin.web.app import run_web
    run_web(host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()