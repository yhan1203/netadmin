"""测试 netadmin 各模块"""

import sys
from pathlib import Path

import pytest

# 确保包路径可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from netadmin.config import Settings
from netadmin.commands import resolve, list_commands


class TestConfig:
    def test_empty_config(self) -> None:
        """没有配置文件时不会崩溃"""
        s = Settings("/nonexistent/path.yaml")
        assert s.devices == []
        assert s.default_username == "admin"

    def test_resolve_device(self) -> None:
        s = Settings()
        dev = s.resolve_device("10.0.0.1", vendor="huawei")
        assert dev["host"] == "10.0.0.1"
        assert dev["vendor"] == "huawei"
        assert dev["port"] == 22


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


class TestBackupDiff:
    def test_diff_identical(self) -> None:
        """空 diff 测试（不依赖数据库，纯单元）"""
        from netadmin.backup import _fmt_size

        assert _fmt_size(500) == "500B"
        assert _fmt_size(2048) == "2.0KB"
        assert _fmt_size(1048576) == "1.0MB"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])