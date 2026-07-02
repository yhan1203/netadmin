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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])