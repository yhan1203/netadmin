"""通知推送 — Telegram / 钉钉告警

在 check 和 audit 发现异常时推送告警到指定渠道。

用法:
    from netadmin.notifier import AlertNotifier

    notifier = AlertNotifier(settings.notifications)
    notifier.send_alert("192.168.1.1", "CPU 95% [red]HIGH[/]", title="健康检查告警")
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

from netadmin.config import NotificationConfig

logger = logging.getLogger(__name__)


# ── 异常 ─────────────────────────────────────────────────────


class NotificationError(Exception):
    """通知发送失败"""


# ── 告警级别 ─────────────────────────────────────────────────


@dataclass
class Alert:
    """一条告警"""
    device: str
    message: str
    level: str = "INFO"  # INFO | WARN | CRITICAL
    title: str = ""


# ── 通知器 ───────────────────────────────────────────────────


class AlertNotifier:
    """统一告警推送器，支持 Telegram 和钉钉"""

    def __init__(self, config: NotificationConfig) -> None:
        self.config = config

    def is_configured(self) -> bool:
        """检查是否配了至少一个通知渠道"""
        return self.config.enabled and bool(self.config.telegram_token or self.config.dingtalk_webhook)

    def send_alert(self, device: str, message: str, *, title: str = "", level: str = "INFO") -> list[str]:
        """向所有已配置的渠道推送告警"""
        sent: list[str] = []
        if not self.is_configured():
            logger.debug("Notifications not configured, skipping")
            return sent

        alert = Alert(device=device, message=message, level=level, title=title)

        if self.config.telegram_token and self.config.telegram_chat_id:
            try:
                self._send_telegram(alert)
                sent.append("telegram")
            except NotificationError as e:
                logger.warning("Telegram notify failed: %s", e)

        if self.config.dingtalk_webhook:
            try:
                self._send_dingtalk(alert)
                sent.append("dingtalk")
            except NotificationError as e:
                logger.warning("DingTalk notify failed: %s", e)

        return sent

    def _format_message(self, alert: Alert) -> str:
        """格式化告警文本（去掉 Rich 标记，转义 Markdown 特殊字符）"""
        # 去掉 Rich 标记 [red], [green], [/] 等
        msg = re.sub(r"\[/?\w+(?:\s+\w+)*\]", "", alert.message).strip()
        # 转义 Markdown 特殊字符（Telegram parse_mode=Markdown）
        msg = self._escape_markdown(msg)
        device = self._escape_markdown(alert.device)
        title = self._escape_markdown(alert.title) if alert.title else ""
        level = self._escape_markdown(alert.level)
        parts = [f"🏷 {title}"] if title else []
        parts.append(f"📟 {device}")
        parts.append(f"📝 {msg}")
        parts.append(f"🔔 {level}")
        parts.append(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(parts)

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """转义 Telegram Markdown 特殊字符"""
        for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
            text = text.replace(ch, f"\\{ch}")
        return text

    # ── Telegram ─────────────────────────────────────────────

    def _send_telegram(self, alert: Alert) -> None:
        """通过 Telegram Bot API 发送消息"""
        text = self._format_message(alert)
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.config.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")[:500]
                result = json.loads(body)
                if not result.get("ok", False):
                    desc = result.get("description", body)
                    raise NotificationError(f"Telegram API error: {desc}")
        except urllib.error.URLError as e:
            raise NotificationError(f"Telegram connection failed: {e}") from e

    # ── 钉钉 ─────────────────────────────────────────────────

    def _send_dingtalk(self, alert: Alert) -> None:
        """通过钉钉自定义机器人 Webhook 发送消息"""
        text = self._format_message(alert)
        url = self.config.dingtalk_webhook

        # 验证 URL 格式
        parsed = urlparse(url)
        if parsed.scheme not in ("https",):
            raise NotificationError(f"DingTalk webhook must use HTTPS, got: {parsed.scheme}")

        # 签名（如果配置了 secret），用 urlencode 正确拼接参数
        if self.config.dingtalk_secret:
            timestamp = str(round(time.time() * 1000))
            sign_str = f"{timestamp}\n{self.config.dingtalk_secret}"
            sign = hmac.new(
                self.config.dingtalk_secret.encode("utf-8"),
                sign_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            separator = "&" if parsed.query else "?"
            url += f"{separator}timestamp={timestamp}&sign={sign}"

        payload = json.dumps({
            "msgtype": "text",
            "text": {"content": text},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")[:500]
                try:
                    result = json.loads(body)
                except json.JSONDecodeError:
                    raise NotificationError(f"DingTalk returned non-JSON response: {body[:200]}")
                if result.get("errcode", -1) != 0:
                    raise NotificationError(f"DingTalk API error: {result.get('errmsg', body)}")
        except urllib.error.URLError as e:
            raise NotificationError(f"DingTalk connection failed: {e}") from e

    def send_health_alert(self, report: dict, host: str) -> list[str]:
        """检查健康报告是否超标，超标则推送"""
        checks: list[str] = []

        cpu = report.get("cpu", "")
        if "HIGH" in cpu:
            checks.append(f"CPU: {cpu}")

        mem = report.get("memory", "")
        if "HIGH" in mem:
            checks.append(f"内存: {mem}")

        temp = report.get("temperature", "")
        if "HIGH" in temp:
            checks.append(f"温度: {temp}")

        log_errors = report.get("log_errors", "0")
        try:
            err_count = int(log_errors.split()[0])
            if err_count > 0:
                checks.append(f"日志错误: {err_count} 条")
        except (ValueError, IndexError):
            pass

        if checks:
            message = "⚠ 健康检查异常\n" + "\n".join(checks)
            return self.send_alert(host, message, title="健康检查告警", level="WARN")
        return []

    def send_audit_alert(self, report: dict, host: str) -> list[str]:
        """检查审计报告，低分或失败项则推送"""
        alerts: list[str] = []
        fails: list[str] = []

        score = report.get("score", 100)
        for f in report.get("findings", []):
            if not f.get("passed", True):
                fails.append(f"  ✗ {f['check']}: {f.get('detail', '')[:60]}")

        if score < 80 or fails:
            message = f"安全评分: {score}/100\n"
            if fails:
                message += "违规项:\n" + "\n".join(fails)
            return self.send_alert(host, message, title="安全审计告警", level="WARN" if score < 60 else "INFO")
        return []