"""定时备份调度 — 基于 crontab 表达式的设备配置自动备份

将调度规则持久化到 SQLite，由 cron/systemd timer 驱动执行。

用法:
  netadmin backup schedule add --interval "0 2 * * *"          # 每天凌晨 2 点
  netadmin backup schedule add --interval "30m"                 # 每 30 分钟
  netadmin backup schedule add --interval "1h"                  # 每小时
  netadmin backup schedule list                                  # 查看调度任务
  netadmin backup schedule remove <id>                           # 删除调度任务
  netadmin backup schedule run                                   # 立即执行所有调度任务
"""

from __future__ import annotations

import datetime
import re
import sqlite3
import typing as t
from dataclasses import dataclass

from netadmin.config import Settings
from netadmin.backup import BackupManager


# ── crontab 表达式解析 ──────────────────────────────────────────

@dataclass
class CrontabExpression:
    """解析后的 crontab 表达式"""
    minute: str
    hour: str
    day_of_month: str
    month: str
    day_of_week: str
    raw: str

    def describe(self) -> str:
        """生成人类可读的描述"""
        if self.minute == "*" and self.hour == "*" and self.day_of_month == "*" and self.month == "*" and self.day_of_week == "*":
            return "每分钟"
        if self.minute == "0" and self.hour.isdigit() and self.day_of_month == "*" and self.month == "*" and self.day_of_week == "*":
            return f"每天 {self.hour}:00"
        if self.minute.isdigit() and self.hour == "*" and self.day_of_month == "*" and self.month == "*" and self.day_of_week == "*":
            return f"每小时 {self.minute} 分"
        if "*/" in self.minute and self.hour == "*":
            interval = self.minute.split("*/")[1]
            return f"每 {interval} 分钟"
        if self.minute == "0" and "*/" in self.hour:
            interval = self.hour.split("*/")[1]
            return f"每 {interval} 小时"
        if self.day_of_week.isdigit() and self.hour.isdigit() and self.minute == "0":
            days = ["日", "一", "二", "三", "四", "五", "六"]
            day_name = days[int(self.day_of_week)] if int(self.day_of_week) < 7 else self.day_of_week
            return f"每周{day_name} {self.hour}:00"
        return self.raw


def parse_interval(interval: str) -> str:
    """将人类可读间隔转为 crontab 表达式

    Args:
        interval: 如 "30m", "1h", "2h", "daily", "hourly", "0 2 * * *" (原生 crontab)

    Returns:
        str: crontab 表达式（5字段）
    """
    interval = interval.strip().lower()

    # 已经是 crontab 格式（5字段）
    if re.match(r"^[\d/*,\-]+\s+[\d/*,\-]+\s+[\d/*,\-]+\s+[\d/*,\-]+\s+[\d/*,\-]+$", interval):
        return interval

    # 简单格式: 30m, 1h, 2h
    m = re.match(r"^(\d+)([mh])$", interval)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        if unit == "m":
            if value < 60:
                return f"*/{value} * * * *"
            return f"*/{value // 60} * * * *"
        if unit == "h":
            if value > 23:
                value = 24  # 上限24小时
            return f"0 */{value} * * *"

    # daily / hourly
    if interval in ("daily", "每日", "每天"):
        return "0 2 * * *"  # 默认凌晨 2 点
    if interval in ("hourly", "每小时"):
        return "0 * * * *"

    raise ValueError(f"Unrecognized interval: {interval}. Use formats like '30m', '1h', 'daily', 'hourly', or crontab '0 2 * * *'")


# ── 调度管理器 ──────────────────────────────────────────────────


@dataclass
class ScheduleEntry:
    id: int
    name: str
    crontab: str
    description: str
    enabled: bool
    created_at: str
    last_run: str | None
    last_result: str | None


class BackupScheduler:
    """定时备份调度管理器"""

    SCHEDULE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS backup_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            crontab TEXT NOT NULL,
            description TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            last_run TEXT,
            last_result TEXT
        )
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._db: sqlite3.Connection | None = None

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self.settings.db_path)
            self._db.execute(self.SCHEDULE_TABLE_SQL)
        return self._db

    def add(self, name: str, crontab: str, description: str = "") -> int:
        """添加调度任务

        Returns:
            int: 新任务的 ID
        """
        now = datetime.datetime.now().isoformat()
        cursor = self.db.execute(
            "INSERT INTO backup_schedules (name, crontab, description, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
            (name, crontab, description, now),
        )
        self.db.commit()
        return cursor.lastrowid or 0

    def remove(self, schedule_id: int) -> bool:
        """删除调度任务"""
        cursor = self.db.execute("DELETE FROM backup_schedules WHERE id = ?", (schedule_id,))
        self.db.commit()
        return cursor.rowcount > 0

    def list_schedules(self) -> list[ScheduleEntry]:
        """列出所有调度任务"""
        rows = self.db.execute(
            "SELECT id, name, crontab, description, enabled, created_at, last_run, last_result "
            "FROM backup_schedules ORDER BY id"
        ).fetchall()
        return [
            ScheduleEntry(
                id=r[0], name=r[1], crontab=r[2], description=r[3] or "",
                enabled=bool(r[4]), created_at=r[5], last_run=r[6], last_result=r[7],
            )
            for r in rows
        ]

    def toggle(self, schedule_id: int, enabled: bool) -> bool:
        """启用/禁用调度任务"""
        cursor = self.db.execute(
            "UPDATE backup_schedules SET enabled = ? WHERE id = ?", (1 if enabled else 0, schedule_id),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def run_scheduled_backups(self) -> list[dict]:
        """执行所有已启用的调度任务（供 cron/systemd timer 调用）

        对每个任务，备份所有已配置的设备。
        """
        schedules = self.list_schedules()
        results: list[dict] = []
        mgr = BackupManager(self.settings)

        for sched in schedules:
            if not sched.enabled:
                continue

            sched_result = {"schedule_id": sched.id, "name": sched.name, "devices": [], "success": True}

            devices = self.settings.all_devices()
            if not devices:
                sched_result["success"] = False
                sched_result["error"] = "No devices configured"
            else:
                for dev in devices:
                    try:
                        path, version = mgr.backup(dev, comment=f"scheduled: {sched.name}")
                        sched_result["devices"].append({"host": dev["host"], "path": path, "version": version, "success": True})
                    except Exception as e:
                        sched_result["devices"].append({"host": dev["host"], "error": str(e), "success": False})
                        sched_result["success"] = False

            # 更新 last_run
            now = datetime.datetime.now().isoformat()
            status = "OK" if sched_result["success"] else "FAIL"
            self.db.execute(
                "UPDATE backup_schedules SET last_run = ?, last_result = ? WHERE id = ?",
                (now, status, sched.id),
            )
            self.db.commit()
            sched_result["timestamp"] = now
            results.append(sched_result)

        return results

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None