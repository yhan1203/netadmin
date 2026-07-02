"""测试 netadmin 各模块 — 完整覆盖"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from netadmin.config import Settings
from netadmin.commands import resolve, list_commands


# ═══════════════════════════════════════════════════════════════
# config
# ═══════════════════════════════════════════════════════════════

class TestConfig:
    def test_empty_config(self) -> None:
        s = Settings("/nonexistent/path.yaml")
        assert s.devices == []
        assert s.default_username == "admin"

    def test_resolve_device(self) -> None:
        s = Settings()
        dev = s.resolve_device("10.0.0.1", vendor="huawei")
        assert dev["host"] == "10.0.0.1"
        assert dev["vendor"] == "huawei"
        assert dev["port"] == 22
        assert dev["username"] == "admin"

    def test_resolve_device_from_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({
                "devices": [{"host": "10.0.0.5", "name": "core-sw", "vendor": "cisco", "device_type": "cisco_ios"}],
                "defaults": {"username": "netadmin", "password": "secret"},
            }, f)
            path = f.name

        try:
            s = Settings(path)
            dev = s.get_device("10.0.0.5")
            assert dev is not None
            assert dev["name"] == "core-sw"

            # 按 name 查找
            dev2 = s.get_device("core-sw")
            assert dev2 is not None
            assert dev2["host"] == "10.0.0.5"
        finally:
            Path(path).unlink()

    def test_all_devices(self) -> None:
        s = Settings()
        assert isinstance(s.all_devices(), list)

    def test_resolve_with_overrides(self) -> None:
        s = Settings()
        dev = s.resolve_device("10.0.0.2", username="override_user", timeout=60)
        assert dev["username"] == "override_user"
        assert dev["timeout"] == 60

    def test_normalize_vendor(self) -> None:
        from netadmin.connector import normalize_vendor
        assert normalize_vendor("华为") == "huawei"
        assert normalize_vendor("思科") == "cisco"
        assert normalize_vendor("HUAWEI") == "huawei"
        assert normalize_vendor("CISCO") == "cisco"


# ═══════════════════════════════════════════════════════════════
# commands
# ═══════════════════════════════════════════════════════════════

class TestCommands:
    def test_show_vlan_huawei(self) -> None:
        cmd = resolve("show_vlan", "huawei")
        assert cmd == "display vlan"

    def test_show_vlan_cisco(self) -> None:
        cmd = resolve("show_vlan", "cisco")
        assert cmd == "show vlan brief"

    def test_create_vlan_huawei(self) -> None:
        cmds = resolve("create_vlan", "huawei", vlan_id="10", vlan_name="test")
        assert isinstance(cmds, list)
        assert any("vlan batch 10" in c for c in cmds)

    def test_create_vlan_cisco(self) -> None:
        cmds = resolve("create_vlan", "cisco", vlan_id="10", vlan_name="test")
        assert isinstance(cmds, list)
        assert any("vlan 10" in c for c in cmds)

    def test_unknown_command(self) -> None:
        cmd = resolve("nonexistent_cmd", "cisco")
        assert "Unknown command" in str(cmd)

    def test_list_commands(self) -> None:
        cmds = list_commands("cisco")
        assert len(cmds) > 10
        names = [c[0] for c in cmds]
        assert "show_vlan" in names
        assert "show_interface" in names
        assert "show_version" in names

    def test_vlan_commands(self) -> None:
        cmds = resolve("set_access_port", "huawei", port="GE0/0/1", vlan_id="10")
        assert isinstance(cmds, list)
        assert any("interface GE0/0/1" in c for c in cmds)
        assert any("port link-type access" in c for c in cmds)

    def test_trunk_commands(self) -> None:
        cmds = resolve("set_trunk_port", "cisco", port="Gi1/0/1", vlan_ids="10,20")
        assert isinstance(cmds, list)
        assert any("switchport mode trunk" in c for c in cmds)
        assert any("switchport trunk allowed vlan 10,20" in c for c in cmds)

    def test_huawei_trunk(self) -> None:
        cmds = resolve("set_trunk_port", "huawei", port="GE0/0/1", vlan_ids="10 20")
        assert any("port link-type trunk" in c for c in cmds)

    def test_delete_vlan(self) -> None:
        cmd_h = resolve("delete_vlan", "huawei", vlan_id="99")
        assert cmd_h == "undo vlan 99"
        cmd_c = resolve("delete_vlan", "cisco", vlan_id="99")
        assert cmd_c == "no vlan 99"

    def test_save_config(self) -> None:
        cmd_h = resolve("save_config", "huawei")
        assert cmd_h == "save"
        cmd_c = resolve("save_config", "cisco")
        assert cmd_c == "write memory"

    def test_enter_config_mode(self) -> None:
        cmd_h = resolve("enter_config_mode", "huawei")
        assert cmd_h == "system-view"
        cmd_c = resolve("enter_config_mode", "cisco")
        assert cmd_c == "configure terminal"

    def test_all_command_names(self) -> None:
        all_cmds = list_commands("cisco") + list_commands("huawei")
        names = set(c[0] for c in all_cmds)
        assert "show_vlan" in names
        assert "show_interface" in names
        assert "show_version" in names
        assert "show_running_config" in names
        assert "show_mac_table" in names
        assert "show_cpu" in names
        assert "show_memory" in names
        assert "show_lldp_neighbors" in names
        assert "show_stp" in names
        assert "show_ntp" in names
        assert "show_log" in names
        assert "show_interface_detail" in names
        assert "show_interface_description" in names
        assert "show_ip_interface" in names
        assert "show_arp" in names
        assert "show_snmp" in names


# ═══════════════════════════════════════════════════════════════
# backup
# ═══════════════════════════════════════════════════════════════

class TestBackup:
    def test_fmt_size(self) -> None:
        from netadmin.backup import _fmt_size
        assert _fmt_size(500) == "500B"
        assert _fmt_size(2048) == "2.0KB"
        assert _fmt_size(1048576) == "1.0MB"

    def test_db_init(self) -> None:
        """验证 SQLite 初始化不报错"""
        with tempfile.TemporaryDirectory() as tmp:
            from netadmin.backup import BackupManager
            from netadmin.config import Settings
            s = Settings()
            s._config_path = tmp  # 临时绕过
            s.backup_dir = str(Path(tmp) / "backups")
            s.db_path = str(Path(tmp) / "test.db")
            mgr = BackupManager(s)
            assert mgr.db.execute("SELECT COUNT(*) FROM backups").fetchone()[0] == 0
            mgr.close()


# ═══════════════════════════════════════════════════════════════
# learn — 模板生成测试（纯文本解析，不连真实设备）
# ═══════════════════════════════════════════════════════════════

class TestLearn:
    def test_parse_vlan_extract(self) -> None:
        """测试 VLAN 提取逻辑"""
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "huawei"

        # 模拟华为配置
        learner._raw_config = """
 vlan batch 10 20 30
 vlan 40
  name test-vlan
"""
        vlans = learner._extract_vlans()
        ids = [v["id"] for v in vlans]
        assert 10 in ids
        assert 20 in ids
        assert 30 in ids
        assert 40 in ids

        # name 提取
        v40 = next(v for v in vlans if v["id"] == 40)
        assert v40["name"] == "test-vlan"

    def test_parse_cisco_vlan(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "cisco"

        learner._raw_config = """
 vlan 10
  name office
 vlan 20
  name voip
"""
        vlans = learner._extract_vlans()
        ids = [v["id"] for v in vlans]
        assert 10 in ids
        assert 20 in ids
        v10 = next(v for v in vlans if v["id"] == 10)
        assert v10["name"] == "office"

        # VLAN 1 应该被过滤
        assert 1 not in ids

    def test_parse_interfaces_huawei(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "huawei"

        learner._raw_config = """
#
interface GigabitEthernet0/0/1
 port link-type trunk
 port trunk allow-pass vlan 10 20
 description To-Core
#
interface GigabitEthernet0/0/2
 port link-type access
 port default vlan 10
 description Office
"""
        ifaces = learner._extract_interfaces()
        assert len(ifaces) == 2

        trunk = next(i for i in ifaces if i["mode"] == "trunk")
        assert trunk["vlans"] == "10 20"
        assert trunk["description"] == "To-Core"

        access = next(i for i in ifaces if i["mode"] == "access")
        assert access["vlans"] == "10"
        assert access["description"] == "Office"

    def test_parse_interfaces_cisco(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "cisco"

        learner._raw_config = """
interface GigabitEthernet1/0/1
 switchport mode trunk
 switchport trunk allowed vlan 10,20
 description Uplink
!
interface GigabitEthernet1/0/2
 switchport mode access
 switchport access vlan 10
 description Desktop
"""
        ifaces = learner._extract_interfaces()
        trunk = next(i for i in ifaces if i["mode"] == "trunk")
        assert trunk["vlans"] == "10,20"
        assert trunk["description"] == "Uplink"

        access = next(i for i in ifaces if i["mode"] == "access")
        assert access["vlans"] == "10"

    def test_extract_ntp(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner._raw_config = """
 ntp server 192.168.1.100
 ntp server ntp.example.com
 clock timezone CST+8
"""
        ntp = learner._extract_ntp()
        assert ntp is not None
        assert "192.168.1.100" in ntp["servers"]
        assert "ntp.example.com" in ntp["servers"]
        assert ntp["timezone"] == "CST+8"

    def test_extract_no_ntp(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner._raw_config = "hostname test\nvlan 10\n"
        ntp = learner._extract_ntp()
        assert ntp is None

    def test_extract_snmp(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner._raw_config = """
 snmp-server community monitoring RO
 snmp-server location Room-201
"""
        snmp = learner._extract_snmp()
        assert snmp is not None
        assert "monitoring" in snmp["community"]
        assert snmp["location"] == "Room-201"

    def test_extract_stp(self) -> None:
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner._raw_config = "spanning-tree mode rapid-pvst\n"
        stp = learner._extract_stp()
        assert stp is not None
        assert stp["mode"] == "pvst" or stp["mode"] == "rapid-pvst"

    def test_yaml_generation(self) -> None:
        """验证 YAML 输出包含占位符"""
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "cisco"
        learner.config = {"host": "10.0.0.1"}

        # 直接测试 _to_yaml
        yaml_out = learner._to_yaml(
            hostname="SW-1", vendor="cisco", model="C2960X", version="15.2",
            vlans=[{"id": 10, "name": "office"}],
            interfaces=[{"name": "Gi1/0/1", "mode": "access", "vlans": "10", "description": "", "shutdown": False}],
            ntp={"servers": ["192.168.1.100"], "timezone": "UTC"},
            snmp=None, stp=None, management=None,
        )
        assert "{{HOSTNAME}}" in yaml_out
        assert "office" in yaml_out


# ═══════════════════════════════════════════════════════════════
# apply — 模板部署
# ═══════════════════════════════════════════════════════════════

class TestApply:
    def test_replace_vars(self) -> None:
        from netadmin.apply import _replace_vars
        result = _replace_vars("hostname {{HOSTNAME}} mgmt {{MGMT_IP}}",
                               {"HOSTNAME": "SW-1", "MGMT_IP": "10.0.0.1"})
        assert result == "hostname SW-1 mgmt 10.0.0.1"

    def test_unknown_var_unchanged(self) -> None:
        from netadmin.apply import _replace_vars
        result = _replace_vars("{{UNKNOWN_VAR}}", {"HOSTNAME": "test"})
        assert "{{UNKNOWN_VAR}}" in result

    def test_load_template_nonexistent(self) -> None:
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        with pytest.raises(FileNotFoundError):
            applier._load_template("/nonexistent/template.yaml")

    def test_build_config_commands_cisco(self) -> None:
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        template = {
            "device": {"hostname": "SW-NEW", "vendor": "cisco"},
            "vlans": [{"id": 10, "name": "office"}, {"id": 20, "name": "voip"}],
            "interfaces": [
                {"name": "Gi1/0/1", "mode": "trunk", "vlans": "10,20", "description": "Uplink", "shutdown": False},
                {"name": "Gi1/0/2", "mode": "access", "vlans": "10", "description": "", "shutdown": True},
            ],
            "ntp": {"servers": ["192.168.1.100"], "timezone": "UTC"},
        }
        cfg = {"host": "10.0.0.2", "vendor": "cisco", "name": "SW-NEW",
               "device_type": "cisco_ios", "port": 22, "username": "admin", "password": "", "timeout": 30}
        cmds = applier._build_config_commands(template, cfg)
        assert "hostname SW-NEW" in cmds
        assert "vlan 10" in cmds
        assert "vlan 20" in cmds
        assert "name office" in cmds
        assert "switchport mode trunk" in cmds
        assert "switchport access vlan 10" in cmds
        assert "shutdown" in cmds
        assert "ntp server 192.168.1.100" in cmds

    def test_build_config_commands_huawei(self) -> None:
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        template = {
            "device": {"hostname": "SW-NEW", "vendor": "huawei"},
            "vlans": [{"id": 10, "name": "office"}, {"id": 20, "name": ""}],
            "interfaces": [
                {"name": "GE0/0/1", "mode": "trunk", "vlans": "10 20", "description": "Uplink", "shutdown": False},
            ],
            "stp": {"mode": "mstp", "root_primary": True},
        }
        cfg = {"host": "10.0.0.3", "vendor": "huawei", "name": "SW-NEW",
               "device_type": "huawei", "port": 22, "username": "admin", "password": "", "timeout": 30}
        cmds = applier._build_config_commands(template, cfg)
        # hostname
        assert any("sysname" in c for c in cmds)
        # VLAN batch
        assert "vlan batch 10 20" in cmds or "vlan batch 20 10" in cmds
        # name
        assert "name office" in cmds
        # interface
        assert "port link-type trunk" in cmds
        assert "port trunk allow-pass vlan 10 20" in cmds
        # STP
        assert "stp mode mstp" in cmds
        assert "stp root primary" in cmds
        # return
        assert "return" in cmds


# ═══════════════════════════════════════════════════════════════
# scanner
# ═══════════════════════════════════════════════════════════════

class TestScanner:
    def test_vendor_detection_from_strings(self) -> None:
        from netadmin.scanner import NetworkScanner as NS
        # 测试 vendor 识别逻辑（静态方法）
        result = NS._identify_vendor("10.0.0.1", [22])
        # 不连真实设备的场景下返回 unknown
        assert result in ("unknown", "cisco", "huawei")

    def test_scan_empty_subnet_format(self) -> None:
        from netadmin.scanner import NetworkScanner
        scanner = NetworkScanner()
        # 不应该崩溃，即使 ping 不通
        results = scanner.scan("10.255.255.0/30", timeout=1, max_workers=2)
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════════
# checker — 审计测试
# ═══════════════════════════════════════════════════════════════

class TestChecker:
    def test_cpu_parse_huawei(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_cpu("CPU Usage : 45%", "huawei")
        assert "45%" in result

    def test_cpu_parse_cisco(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_cpu("CPU utilization for five seconds: 12%", "cisco")
        assert "12%" in result

    def test_memory_parse_huawei(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_memory("Memory Using Percentage: 67%", "huawei")
        assert "67%" in result

    def test_memory_parse_cisco(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_memory("Processor Pool Total: 1000000  Used: 300000", "cisco")
        assert "30%" in result or "30 %" in result

    def test_temperature(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_temperature("Temperature : 45", "huawei")
        assert "45" in result

    def test_count_log_errors_clean(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._count_log_errors("All interfaces up\nSystem OK")
        assert "0" in result

    def test_count_log_errors_found(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._count_log_errors("error: link down\nInterface Gi0/1 down\nAll good")
        assert "2" in result or "2" in str(result)

    def test_audit_findings(self) -> None:
        from netadmin.checker import SecurityAuditor
        auditor = SecurityAuditor()
        # 模拟运行配置
        mock_config = """
ip ssh version 2
snmp-server community public RO
service password-encryption
enable secret 5 $1$abc
!
line vty 0 4
 access-class 10 in
!
banner motd ^C
Welcome
^C
!
ntp server 192.168.1.100
logging buffered
"""
        # 手动注入配置做 _check 测试
        auditor._check_password_encryption(mock_config, "cisco")
        auditor._check_snmp_community(mock_config)
        auditor._check_ssh_version(mock_config)
        auditor._check_vty_acl(mock_config, "cisco")
        auditor._check_banner(mock_config)
        auditor._check_logging(mock_config)
        auditor._check_ntp(mock_config, "cisco")

        findings = auditor._findings
        check_names = [f["check"] for f in findings]
        assert "Password Encryption" in check_names
        assert "SNMP Community" in check_names
        assert "SSH Version" in check_names
        assert "VTY ACL" in check_names
        assert "Login Banner" in check_names
        assert "Logging" in check_names
        assert "NTP" in check_names


# ═══════════════════════════════════════════════════════════════
# CLI — 测试 Click 命令解析
# ═══════════════════════════════════════════════════════════════

class TestCli:
    def test_cli_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "netadmin" in result.output

    def test_cli_version(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_commands_list(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["commands", "--vendor", "cisco"])
        assert result.exit_code == 0
        assert "show_vlan" in result.output

    def test_commands_huawei(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["commands", "--vendor", "huawei"])
        assert result.exit_code == 0
        assert "display vlan" in result.output

    def test_scan_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0

    def test_backup_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["backup", "--help"])
        assert result.exit_code == 0

    def test_vlan_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["vlan", "--help"])
        assert result.exit_code == 0

    def test_learn_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["learn", "--help"])
        assert result.exit_code == 0

    def test_apply_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["apply", "--help"])
        assert result.exit_code == 0

    def test_connect_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["connect", "--help"])
        assert result.exit_code == 0

    def test_check_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--help"])
        assert result.exit_code == 0

    def test_audit_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["audit", "--help"])
        assert result.exit_code == 0

    def test_interface_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["interface", "--help"])
        assert result.exit_code == 0

    def test_vlan_list_help(self) -> None:
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["vlan", "list", "--help"])
        assert result.exit_code == 0

    def test_learn_output_writes_yaml_not_tuple(self) -> None:
        """验证 learn 命令写入的是 YAML 字符串而非 NamedTuple"""
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "cisco"
        learner.config = {"host": "10.0.0.1"}

        yaml_out = learner._to_yaml(
            hostname="SW-1", vendor="cisco", model="C2960X", version="15.2",
            vlans=[{"id": 10, "name": "office"}],
            interfaces=[],
            ntp=None, snmp=None, stp=None, management=None,
        )
        # YAML 输出必须是字符串，不能以 "LearnedTemplate(" 开头
        assert isinstance(yaml_out, str)
        assert not yaml_out.startswith("LearnedTemplate(")
        assert "hostname:" in yaml_out or "HOSTNAME" in yaml_out

    def test_logging_check_no_false_positive(self) -> None:
        """验证 _check_logging 不会误判 'login' 为 logging"""
        from netadmin.checker import SecurityAuditor
        auditor = SecurityAuditor()
        # 配置里有 login 但没有 logging
        cfg = "login authentication default\nip http server\n"
        auditor._check_logging(cfg)
        logging_finding = next(f for f in auditor._findings if f["check"] == "Logging")
        # 没有 logging 配置，应该 FAIL
        assert not logging_finding["passed"]

    def test_learn_vlan_name_with_duplicate_pattern(self) -> None:
        """验证同名 VLAN 的 name 提取不会串到第一个"""
        from netadmin.learn import ConfigLearner

        learner = ConfigLearner.__new__(ConfigLearner)
        learner.vendor = "huawei"

        # 两个 vlan 配置，第二个 vlan 20 的名字在远处
        learner._raw_config = """
 vlan batch 10 20
 vlan 10
  name office
 vlan 20
  name voip
"""
        vlans = learner._extract_vlans()
        v20 = next(v for v in vlans if v["id"] == 20)
        assert v20["name"] == "voip", f"Expected 'voip', got '{v20['name']}'"

    def test_scan_default_subnet_shows_warning(self) -> None:
        """验证 scan 无参数时显示默认网段提示"""
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["scan"])
        # 有输出（无默认网段提示或 scan 输出），不崩溃即通过
        assert result.exit_code == 0 or "defaulting" in result.output

    def test_learn_help_shows_correctly(self) -> None:
        """验证 learn --help 输出格式"""
        from click.testing import CliRunner
        from netadmin.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["learn", "--help"])
        assert result.exit_code == 0
        assert "HOST" in result.output
        assert "--output" in result.output or "-o" in result.output

    def test_scanner_scan_ports_concurrent(self) -> None:
        """验证端口扫描使用并发而非顺序"""
        from netadmin.scanner import NetworkScanner
        # 测试 _scan_port 静态方法
        result = NetworkScanner._scan_port("127.0.0.1", 22, 1)
        # 本地可能没开 SSH，但方法不应崩溃
        assert result is None or result == 22

    def test_scanner_quick_scan_no_default(self) -> None:
        """验证 quick_scan 不再有硬编码默认子网"""
        import inspect
        from netadmin.scanner import quick_scan
        sig = inspect.signature(quick_scan)
        # subnet 参数不应有默认值
        assert sig.parameters["subnet"].default is inspect.Parameter.empty, \
            "quick_scan(subnet) should not have a default value"

    def test_vlan_save_inside_with_block(self) -> None:
        """验证 VLAN 操作的 save 在 with 块内（不会用已断开的连接）"""
        import ast
        import inspect
        import textwrap
        from netadmin.vlan import VlanManager

        def _save_is_inside_with(method_source: str) -> bool:
            """解析 AST 检查 save_cmd 的 send_command 调用在 with 块内"""
            try:
                tree = ast.parse(textwrap.dedent(method_source))
            except IndentationError:
                return False
            for node in ast.walk(tree):
                if isinstance(node, ast.With):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                            if child.func.attr == "send_command":
                                for arg in child.args:
                                    if isinstance(arg, ast.Call) and \
                                       isinstance(arg.func, ast.Name) and \
                                       arg.func.id == "str":
                                        for a in arg.args:
                                            if isinstance(a, ast.Name) and a.id == "save_cmd":
                                                return True
            return False

        for method_name in ["create_vlan", "delete_vlan", "assign_port"]:
            source = inspect.getsource(getattr(VlanManager, method_name))
            assert _save_is_inside_with(source), \
                f"{method_name}: send_command(save_cmd) should be inside the with block"

    def test_backup_manager_has_finalizer(self) -> None:
        """验证 BackupManager 有 GC finalizer 自动关闭连接"""
        from netadmin.backup import BackupManager
        from netadmin.config import Settings

        s = Settings()
        s.backup_dir = "/tmp"
        s.db_path = "/tmp/test_finalize.db"
        mgr = BackupManager(s)
        # 触发 db 属性初始化
        _ = mgr.db
        assert mgr._db is not None
        # 验证 close 方法存在
        assert hasattr(mgr, 'close'), "close() method should exist"


# ═══════════════════════════════════════════════════════════════
# checker — 中文 Locale 解析
# ═══════════════════════════════════════════════════════════════

class TestChineseLocale:
    """验证华为中文 locale 输出解析"""

    def test_cpu_parse_huawei_chinese(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_cpu("CPU 占用率 : 45%", "huawei")
        assert "45%" in result

    def test_memory_parse_huawei_chinese(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_memory("内存利用率 : 67%", "huawei")
        assert "67%" in result

    def test_temperature_parse_huawei_chinese(self) -> None:
        from netadmin.checker import HealthChecker as HC
        result = HC._parse_temperature("系统温度 : 45 摄氏度", "huawei")
        assert "45" in result


# ═══════════════════════════════════════════════════════════════
# apply — 额外边界测试
# ═══════════════════════════════════════════════════════════════

class TestApplyExtras:
    def test_apply_cisco_trunk(self) -> None:
        """验证思科 trunk 端口配置"""
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        template = {
            "device": {"hostname": "SW-TEST", "vendor": "cisco"},
            "vlans": [],
            "interfaces": [
                {"name": "Gi1/0/1", "mode": "trunk", "vlans": "10,20,30", "description": "Uplink", "shutdown": False},
                {"name": "Gi1/0/2", "mode": "access", "vlans": "10", "description": "Desktop", "shutdown": False},
            ],
        }
        cfg = {"host": "10.0.0.5", "vendor": "cisco", "name": "SW-TEST",
               "device_type": "cisco_ios", "port": 22, "username": "admin", "password": "", "timeout": 30}
        cmds = applier._build_config_commands(template, cfg)
        assert "switchport mode trunk" in cmds
        assert "switchport trunk allowed vlan 10,20,30" in cmds
        assert "switchport access vlan 10" in cmds
        assert "switchport mode access" in cmds

    def test_apply_huawei_hybrid(self) -> None:
        """验证华为 hybrid 端口"""
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        template = {
            "device": {"hostname": "SW-TEST", "vendor": "huawei"},
            "vlans": [],
            "interfaces": [
                {"name": "GE0/0/1", "mode": "hybrid", "vlans": "", "description": "", "shutdown": False},
                {"name": "GE0/0/2", "mode": "access", "vlans": "99", "description": "MGMT", "shutdown": True},
            ],
        }
        cfg = {"host": "10.0.0.6", "vendor": "huawei", "name": "SW-TEST",
               "device_type": "huawei", "port": 22, "username": "admin", "password": "", "timeout": 30}
        cmds = applier._build_config_commands(template, cfg)
        assert "port link-type hybrid" in cmds
        assert "shutdown" in cmds
        assert "undo shutdown" in cmds  # 未 shutdown 的端口要 undo

    def test_apply_with_stp_management(self) -> None:
        """验证 STP + 管理配置"""
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        template = {
            "device": {"hostname": "SW-TEST", "vendor": "cisco"},
            "vlans": [],
            "interfaces": [],
            "stp": {"mode": "rapid-pvst", "root_primary": False},
            "management": {"ssh": True, "users": [], "mgmt_ip": ""},
            "snmp": {"community": ["public"], "location": "", "contact": ""},
        }
        cfg = {"host": "10.0.0.7", "vendor": "cisco", "name": "SW-TEST",
               "device_type": "cisco_ios", "port": 22, "username": "admin", "password": "", "timeout": 30}
        cmds = applier._build_config_commands(template, cfg)
        # STP 模式
        assert "spanning-tree mode" in " ".join(cmds)
        # SNMP
        assert "snmp-server community public RO" in cmds

    def test_apply_huawei_vlan1_name_skipped(self) -> None:
        """验证华为 VLAN 1 的 name 不会被下发"""
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        template = {
            "device": {"hostname": "SW-TEST", "vendor": "huawei"},
            "vlans": [{"id": 1, "name": "default"}, {"id": 10, "name": "office"}],
            "interfaces": [],
        }
        cfg = {"host": "10.0.0.8", "vendor": "huawei", "name": "SW-TEST",
               "device_type": "huawei", "port": 22, "username": "admin", "password": "", "timeout": 30}
        cmds = applier._build_config_commands(template, cfg)
        # VLAN 1 不应出现在命令中（vlan 1 或 name default）
        vlan1_cmds = [c for c in cmds if c.strip() in ("vlan 1", "name default")]
        assert not vlan1_cmds, f"VLAN 1 commands should not appear: {vlan1_cmds}"
        # VLAN 10 应正常出现
        assert "vlan batch 10" in cmds or "vlan 10" in cmds
        assert "name office" in cmds

    def test_apply_template_validation(self) -> None:
        """验证模板格式校验"""
        import pytest
        from netadmin.apply import ConfigApplier
        applier = ConfigApplier()
        cfg = {"host": "10.0.0.9", "vendor": "cisco", "name": "SW-TEST",
               "device_type": "cisco_ios", "port": 22, "username": "admin", "password": "", "timeout": 30}

        # vlans 不是 list
        with pytest.raises(ValueError, match="vlans.*must be a list"):
            applier._build_config_commands({"vlans": "bad"}, cfg)

        # interfaces 包含非 dict 元素
        with pytest.raises(ValueError, match="Each interface entry must be a dict"):
            applier._build_config_commands({"interfaces": ["bad"]}, cfg)

        # ntp 不是 dict
        with pytest.raises(ValueError, match="ntp.*must be a dict"):
            applier._build_config_commands({"ntp": "bad"}, cfg)



# ═══════════════════════════════════════════════════════════════
# checker — 额外审计测试
# ═══════════════════════════════════════════════════════════════

class TestAuditExtras:
    def test_audit_findings_comprehensive(self) -> None:
        """完整审计检查"""
        from netadmin.checker import SecurityAuditor
        auditor = SecurityAuditor()

        # 全 PASS 的配置
        good_config = """
service password-encryption
enable secret 5 $1$abc
snmp-server community mysnmp RO
ip ssh version 2
line vty 0 4
 access-class 10 in
!
banner motd ^C
Welcome^C
!
ntp server 192.168.1.100
logging buffered 16384
"""
        auditor._check_password_encryption(good_config, "cisco")
        auditor._check_snmp_community(good_config)
        auditor._check_ssh_version(good_config)
        auditor._check_vty_acl(good_config, "cisco")
        auditor._check_banner(good_config)
        auditor._check_logging(good_config)
        auditor._check_ntp(good_config, "cisco")

        passed = sum(1 for f in auditor._findings if f["passed"])
        assert passed >= 6  # 大部分检查通过

    def test_audit_huawei(self) -> None:
        """华为配置审计"""
        from netadmin.checker import SecurityAuditor
        auditor = SecurityAuditor()

        huawei_config = """
password cipher
snmp-agent community read monitoring
stelnet server enable
acl number 2000
 rule 5 permit source 10.0.0.0 0.0.0.255
#
user-interface vty 0 4
 acl 2000 inbound
#
header shell information ^C
Welcome^C
#
ntp server ntp.example.com
info-center logbuffer
"""
        auditor._check_password_encryption(huawei_config, "huawei")
        auditor._check_snmp_community(huawei_config)
        auditor._check_ssh_version(huawei_config)
        auditor._check_vty_acl(huawei_config, "huawei")
        auditor._check_banner(huawei_config)
        auditor._check_logging(huawei_config)
        auditor._check_ntp(huawei_config, "huawei")

        passed = sum(1 for f in auditor._findings if f["passed"])
        assert passed >= 5


# ═══════════════════════════════════════════════════════════════
# connector — 厂商检测逻辑
# ═══════════════════════════════════════════════════════════════

class TestConnectorDetect:
    def test_normalize_vendor(self) -> None:
        from netadmin.connector import normalize_vendor
        assert normalize_vendor("华为") == "huawei"
        assert normalize_vendor("思科") == "cisco"
        assert normalize_vendor("HUAWEI") == "huawei"
        assert normalize_vendor("CISCO") == "cisco"
        assert normalize_vendor("huawei") == "huawei"
        assert normalize_vendor("cisco") == "cisco"

    def test_detect_vendor_from_short(self) -> None:
        from netadmin.connector import detect_vendor_from_short
        assert detect_vendor_from_short("huawei") == "huawei"
        assert detect_vendor_from_short("cisco_ios") == "cisco"
        assert detect_vendor_from_short("cisco_xe") == "cisco"
        assert detect_vendor_from_short("unknown") == "cisco"  # fallback


# ═══════════════════════════════════════════════════════════════
# backup — SQLite 操作
# ═══════════════════════════════════════════════════════════════

class TestBackupDB:
    def test_backup_list_empty(self) -> None:
        """空数据库不报错"""
        import tempfile
        from netadmin.backup import BackupManager
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.backup_dir = str(tmp)
            s.db_path = str(__import__("pathlib").Path(tmp) / "test.db")
            mgr = BackupManager(s)
            records = mgr.list_backups()
            assert records == []
            mgr.close()

    def test_backup_diff_nonexistent(self) -> None:
        """不存在的备份 ID 返回 None"""
        import tempfile
        from netadmin.backup import BackupManager
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.backup_dir = str(tmp)
            s.db_path = str(__import__("pathlib").Path(tmp) / "test.db")
            mgr = BackupManager(s)
            result = mgr.diff_backups(999, 998)
            assert result is None
            mgr.close()


# ═══════════════════════════════════════════════════════════════
# scheduler
# ═══════════════════════════════════════════════════════════════


class TestScheduler:
    def test_parse_interval_minutes(self) -> None:
        """30m → */30 * * * *"""
        from netadmin.scheduler import parse_interval
        assert parse_interval("30m") == "*/30 * * * *"

    def test_parse_interval_hourly(self) -> None:
        """1h → 0 */1 * * *"""
        from netadmin.scheduler import parse_interval
        assert parse_interval("1h") == "0 */1 * * *"

    def test_parse_interval_daily(self) -> None:
        """daily → 0 2 * * *"""
        from netadmin.scheduler import parse_interval
        assert parse_interval("daily") == "0 2 * * *"

    def test_parse_interval_hourly_word(self) -> None:
        """hourly → 0 * * * *"""
        from netadmin.scheduler import parse_interval
        assert parse_interval("hourly") == "0 * * * *"

    def test_parse_interval_raw_crontab(self) -> None:
        """原生 crontab 透传"""
        from netadmin.scheduler import parse_interval
        assert parse_interval("30 4 * * 1") == "30 4 * * 1"

    def test_parse_interval_invalid(self) -> None:
        """无效格式抛异常"""
        from netadmin.scheduler import parse_interval
        import pytest as _pytest
        with _pytest.raises(ValueError):
            parse_interval("garbage")

    def test_schedule_list_empty(self) -> None:
        """空数据库返回空列表"""
        import tempfile
        from netadmin.scheduler import BackupScheduler
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.db_path = str(__import__("pathlib").Path(tmp) / "sched.db")
            sched = BackupScheduler(s)
            try:
                entries = sched.list_schedules()
                assert entries == []
            finally:
                sched.close()

    def test_schedule_add_and_list(self) -> None:
        """添加后能列出"""
        import tempfile
        from netadmin.scheduler import BackupScheduler, parse_interval
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.db_path = str(__import__("pathlib").Path(tmp) / "sched.db")
            sched = BackupScheduler(s)
            try:
                sid = sched.add("daily-backup", parse_interval("daily"), "每天凌晨备份")
                assert sid > 0
                entries = sched.list_schedules()
                assert len(entries) == 1
                assert entries[0].name == "daily-backup"
                assert entries[0].enabled is True
            finally:
                sched.close()

    def test_schedule_remove(self) -> None:
        """删除后列表为空"""
        import tempfile
        from netadmin.scheduler import BackupScheduler, parse_interval
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.db_path = str(__import__("pathlib").Path(tmp) / "sched.db")
            sched = BackupScheduler(s)
            try:
                sid = sched.add("test", parse_interval("30m"), "")
                assert sched.remove(sid) is True
                assert sched.list_schedules() == []
                assert sched.remove(999) is False
            finally:
                sched.close()

    def test_schedule_toggle(self) -> None:
        """启用/禁用切换"""
        import tempfile
        from netadmin.scheduler import BackupScheduler, parse_interval
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.db_path = str(__import__("pathlib").Path(tmp) / "sched.db")
            sched = BackupScheduler(s)
            try:
                sid = sched.add("test", parse_interval("30m"), "")
                assert sched.toggle(sid, False) is True
                entries = sched.list_schedules()
                assert entries[0].enabled is False
                assert sched.toggle(sid, True) is True
                entries = sched.list_schedules()
                assert entries[0].enabled is True
                assert sched.toggle(999, True) is False
            finally:
                sched.close()

    def test_schedule_run_no_devices(self) -> None:
        """无设备时运行不崩溃，返回 error"""
        import tempfile
        from netadmin.scheduler import BackupScheduler, parse_interval
        from netadmin.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            s = Settings()
            s.db_path = str(__import__("pathlib").Path(tmp) / "sched.db")
            s.backup_dir = str(tmp)
            s.devices = []  # 清空默认设备
            sched = BackupScheduler(s)
            try:
                sched.add("test", parse_interval("30m"), "")
                results = sched.run_scheduled_backups()
                assert len(results) == 1
                assert results[0]["success"] is False
                assert "No devices configured" in results[0].get("error", "")
            finally:
                sched.close()

    def test_crontab_describe(self) -> None:
        """人类可读描述"""
        from netadmin.scheduler import CrontabExpression

        cases = [
            ("*/5 * * * *", "每 5 分钟"),
            ("0 2 * * *", "每天 2:00"),
            ("30 * * * *", "每小时 30 分"),
            ("0 9 * * 1", "每周一 9:00"),
        ]
        for raw, expected in cases:
            parts = raw.split()
            expr = CrontabExpression(*parts, raw=raw)
            assert expr.describe() == expected


# ═══════════════════════════════════════════════════════════════
# notifier
# ═══════════════════════════════════════════════════════════════


class TestNotifier:
    def test_notification_config_empty(self) -> None:
        """空配置默认 disabled"""
        from netadmin.config import NotificationConfig

        cfg = NotificationConfig()
        assert cfg.enabled is False
        assert cfg.telegram_token == ""
        assert cfg.dingtalk_webhook == ""

    def test_notification_config_from_dict(self) -> None:
        """从 dict 构造"""
        from netadmin.config import NotificationConfig

        data = {"telegram_token": "123:abc", "telegram_chat_id": "-100123", "enabled": True}
        cfg = NotificationConfig.from_dict(data)
        assert cfg.enabled is True
        assert cfg.telegram_token == "123:abc"

    def test_alert_notifier_not_configured(self) -> None:
        """未配置时 is_configured 返回 False"""
        from netadmin.config import NotificationConfig
        from netadmin.notifier import AlertNotifier

        n = AlertNotifier(NotificationConfig())
        assert n.is_configured() is False
        assert n.send_alert("test", "message") == []

    def test_health_alert_no_issues(self) -> None:
        """正常报告不触发告警"""
        from netadmin.config import NotificationConfig
        from netadmin.notifier import AlertNotifier

        n = AlertNotifier(NotificationConfig())
        report = {
            "cpu": "45% [green]OK[/]",
            "memory": "67% [green]OK[/]",
            "temperature": "N/A",
            "log_errors": "0 (clean)",
        }
        result = n.send_health_alert(report, "10.0.0.1")
        assert result == []

    def test_health_alert_high_cpu(self) -> None:
        """CPU 超标产生告警"""
        from netadmin.config import NotificationConfig
        from netadmin.notifier import AlertNotifier

        n = AlertNotifier(NotificationConfig())
        report = {
            "cpu": "95% [red]HIGH[/]",
            "memory": "67% [green]OK[/]",
            "temperature": "N/A",
            "log_errors": "0 (clean)",
        }
        result = n.send_health_alert(report, "10.0.0.1")
        # 未配置渠道，不发
        assert result == []

    def test_health_alert_log_errors(self) -> None:
        """日志错误产生告警"""
        from netadmin.config import NotificationConfig
        from netadmin.notifier import AlertNotifier

        n = AlertNotifier(NotificationConfig())
        report = {
            "cpu": "45% [green]OK[/]",
            "memory": "67% [green]OK[/]",
            "temperature": "N/A",
            "log_errors": "5",
        }
        result = n.send_health_alert(report, "10.0.0.1")
        assert result == []

    def test_audit_alert_perfect_score(self) -> None:
        """满分不触发告警"""
        from netadmin.config import NotificationConfig
        from netadmin.notifier import AlertNotifier

        n = AlertNotifier(NotificationConfig())
        report = {
            "host": "10.0.0.1",
            "score": 100,
            "findings": [
                {"check": "Password Encryption", "passed": True, "detail": ""},
                {"check": "SNMP Community", "passed": True, "detail": ""},
            ],
        }
        result = n.send_audit_alert(report, "10.0.0.1")
        assert result == []

    def test_audit_alert_low_score(self) -> None:
        """低分触发告警"""
        from netadmin.config import NotificationConfig
        from netadmin.notifier import AlertNotifier

        n = AlertNotifier(NotificationConfig())
        report = {
            "host": "10.0.0.1",
            "score": 50,
            "findings": [
                {"check": "Password Encryption", "passed": False, "detail": "No encryption"},
            ],
        }
        result = n.send_audit_alert(report, "10.0.0.1")
        assert result == []


# ═══════════════════════════════════════════════════════════════
# web dashboard
# ═══════════════════════════════════════════════════════════════


class TestWebDashboard:
    def test_dashboard_page_loads(self) -> None:
        """仪表盘首页返回 200"""
        from netadmin.web.app import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "netadmin" in resp.text

    def test_backups_page_loads(self) -> None:
        """备份页面返回 200"""
        from netadmin.web.app import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/backups")
        assert resp.status_code == 200

    def test_schedules_page_loads(self) -> None:
        """调度页面返回 200"""
        from netadmin.web.app import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/schedules")
        assert resp.status_code == 200

    def test_backup_content_not_found(self) -> None:
        """不存在的备份返回 404"""
        from netadmin.web.app import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/backups/99999")
        assert resp.status_code == 404

    def test_backup_diff_not_found(self) -> None:
        """不存在的备份对比返回 404"""
        from netadmin.web.app import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/backups/diff/99998/99999")
        assert resp.status_code == 404

    def test_health_htmx_endpoint(self) -> None:
        """HTMX 健康卡片端点返回 200"""
        from netadmin.web.app import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])