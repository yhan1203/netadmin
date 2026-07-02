"""配置备份 + 差异对比 — 备份 running-config + SQLite 版本索引 + unified diff"""

from __future__ import annotations

import datetime
import os
import sqlite3
import difflib
from pathlib import Path

from netadmin.config import DeviceConfig, Settings
from netadmin.commands import resolve
from netadmin.connector import Connector


class BackupManager:
    """配置备份管理器"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._db: sqlite3.Connection | None = None

    # ── 数据库 ──

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.settings.db_path)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device TEXT NOT NULL,
                    version TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    content TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    comment TEXT DEFAULT ''
                )
            """)
            self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_backups_device
                ON backups(device)
            """)
        return self._db

    def backup(self, config: DeviceConfig, comment: str = "") -> tuple[str, str]:
        """备份一台设备的配置

        Returns:
            (文件路径, 版本号)
        """
        cmd = resolve("show_running_config", config["vendor"])
        if isinstance(cmd, list):
            cmd = cmd[0]

        with Connector(config) as conn:
            output = conn.send_command(cmd)

        # 版本号: 时间戳
        now = datetime.datetime.now()
        version = now.strftime("%Y%m%d_%H%M%S")

        # 存文件
        backup_dir = Path(self.settings.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{config['host']}_{version}.cfg"
        path = str(backup_dir / filename)
        Path(path).write_text(output, encoding="utf-8")

        # 写入数据库
        self.db.execute(
            "INSERT INTO backups (device, version, timestamp, content, size, comment) VALUES (?, ?, ?, ?, ?, ?)",
            (config["host"], version, now.isoformat(), output, len(output), comment),
        )
        self.db.commit()

        return path, version

    def list_backups(self, device: str | None = None) -> list[dict]:
        """列出备份记录"""
        if device:
            rows = self.db.execute(
                "SELECT id, device, version, timestamp, size, comment FROM backups WHERE device = ? ORDER BY id DESC LIMIT 50",
                (device,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, device, version, timestamp, size, comment FROM backups ORDER BY id DESC LIMIT 200"
            ).fetchall()

        return [
            {
                "id": r[0],
                "device": r[1],
                "version": r[2],
                "timestamp": r[3],
                "size": _fmt_size(r[4]),
                "comment": r[5] or "",
            }
            for r in rows
        ]

    def get_backup_content(self, backup_id: int) -> str | None:
        """获取某次备份的内容"""
        row = self.db.execute(
            "SELECT content FROM backups WHERE id = ?", (backup_id,)
        ).fetchone()
        return row[0] if row else None

    def diff_backups(self, id_a: int, id_b: int) -> str | None:
        """对比两个备份版本的差异"""
        content_a = self.get_backup_content(id_a)
        content_b = self.get_backup_content(id_b)
        if content_a is None or content_b is None:
            return None
        if content_a == content_b:
            return ""

        lines_a = content_a.splitlines()
        lines_b = content_b.splitlines()
        diff = difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=f"backup #{id_a}",
            tofile=f"backup #{id_b}",
            lineterm="",
        )
        return "\n".join(diff)

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024 / 1024:.1f}MB"