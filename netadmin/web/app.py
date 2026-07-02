"""netadmin Web 仪表盘 — FastAPI + Jinja2 + HTMX

使用:
    netadmin web                          # 默认 0.0.0.0:8099
    netadmin web --host 127.0.0.1 --port 8080

依赖:
    pip install fastapi uvicorn jinja2 httpx
    或 pip install -e ".[web]"
"""

from __future__ import annotations

import base64
import hmac
import os
import typing as t
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from netadmin.backup import BackupManager
from netadmin.checker import HealthChecker, SecurityAuditor
from netadmin.config import Settings
from netadmin.scheduler import BackupScheduler

settings = Settings()
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="netadmin Dashboard", version="0.1.0")

# ── Basic Auth ────────────────────────────────────────────────
# 通过环境变量 NETADMIN_WEB_USER / NETADMIN_WEB_PASS 配置
# 不配置则默认无认证（仅监听 127.0.0.1）

_WEB_USER = os.environ.get("NETADMIN_WEB_USER", "")
_WEB_PASS = os.environ.get("NETADMIN_WEB_PASS", "")


def _check_auth(request: Request) -> bool:
    """验证 Basic Auth（常量时间比较）"""
    if not _WEB_USER and not _WEB_PASS:
        return True  # 未配置认证，放行
    if not _WEB_USER or not _WEB_PASS:
        return False  # 只配了一半，拒绝
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        user, _, passwd = decoded.partition(":")
        return hmac.compare_digest(user, _WEB_USER) and hmac.compare_digest(passwd, _WEB_PASS)
    except Exception:
        return False


def _require_auth(request: Request) -> None:
    """如果配置了认证但请求未通过，抛出 401"""
    if not _check_auth(request):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="netadmin"'},
        )


# ── CSRF 保护 ─────────────────────────────────────────────────
# 验证 POST 请求的 Origin/Referer 头，防止跨站请求伪造

_CSRF_ORIGINS = [o.strip() for o in os.environ.get("NETADMIN_CSRF_ORIGINS", "").split(",") if o.strip()]
# 添加到默认允许列表（包含常见的带端口变体）
_DEFAULT_CSRF_ORIGINS = [
    "http://127.0.0.1", "http://127.0.0.1:8099", "http://127.0.0.1:8080",
    "http://localhost", "http://localhost:8099", "http://localhost:8080",
]


def _check_csrf(request: Request) -> None:
    """检查 POST 请求的 Origin/Referer"""
    if request.method != "POST":
        return
    origin = request.headers.get("Origin", "")
    referer = request.headers.get("Referer", "")
    # 无 Origin/Referer 的 POST 放行（CLI curl 等）
    if not origin and not referer:
        return
    # 检查是否匹配允许的来源
    allowed = _CSRF_ORIGINS or _DEFAULT_CSRF_ORIGINS
    for h in (origin, referer):
        if h:
            parsed = urlparse(h)
            origin_host = f"{parsed.scheme}://{parsed.netloc}"
            if origin_host in allowed:
                return
    # 不匹配则拒绝
    raise HTTPException(status_code=403, detail="CSRF check failed")


# ── 安全中间件 ────────────────────────────────────────────────


@app.middleware("http")
async def _security_middleware(request: Request, call_next: t.Any) -> Response:
    """全局安全中间件：Basic Auth + CSRF 保护"""
    try:
        _require_auth(request)
        _check_csrf(request)
    except HTTPException as e:
        return Response(
            content="Unauthorized" if e.status_code == 401 else "CSRF check failed",
            status_code=e.status_code,
            headers=e.headers or {},
        )
    return await call_next(request)


# 手动创建 Jinja2 环境（绕过 Starlette Jinja2Templates 与 Jinja2 3.1.6 的兼容问题）
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _render(name: str, request: Request, **context: object) -> HTMLResponse:
    """渲染模板"""
    template = _jinja_env.get_template(name)
    html = template.render(request=request, **context)
    return HTMLResponse(html)


# ── Jinja2 自定义过滤器 ──────────────────────────────────────


def _url_path_escape(s: str) -> str:
    """URL 路径转义（用于设备 host 中的点号等）"""
    from urllib.parse import quote
    return quote(s, safe="")


_jinja_env.filters["url_path"] = _url_path_escape


# ── 全局上下文 ───────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """仪表盘首页 — 设备总览"""
    devices = settings.all_devices()
    return _render("dashboard.html", request, devices=devices, total=len(devices))


@app.get("/device/{host:path}", response_class=HTMLResponse)
async def device_detail(host: str, request: Request) -> HTMLResponse:
    """单设备详情页"""
    host = urllib.parse.unquote(host)
    cfg = settings.resolve_device(host)

    # 健康检查
    checker = HealthChecker()
    health = checker.check(cfg)

    # 安全审计
    auditor = SecurityAuditor()
    audit = auditor.audit(cfg)

    # 备份历史
    mgr = BackupManager(settings)
    try:
        backups = mgr.list_backups(host)
    finally:
        mgr.close()

    return _render(
        "device.html", request,
        host=host, device=cfg, health=health, audit=audit, backups=backups,
    )


@app.get("/backups", response_class=HTMLResponse)
async def backup_list(request: Request) -> HTMLResponse:
    """备份历史"""
    mgr = BackupManager(settings)
    try:
        records = mgr.list_backups()
    finally:
        mgr.close()
    return _render("backups.html", request, backups=records)


@app.get("/backups/{backup_id}", response_class=HTMLResponse)
async def backup_content(backup_id: int, request: Request) -> HTMLResponse:
    """备份内容查看"""
    mgr = BackupManager(settings)
    try:
        content = mgr.get_backup_content(backup_id)
    finally:
        mgr.close()
    if content is None:
        return HTMLResponse("<div class='error'>Backup not found</div>", status_code=404)
    return HTMLResponse(f"<pre class='config-content'>{_escape_html(content)}</pre>")


@app.get("/backups/diff/{a}/{b}", response_class=HTMLResponse)
async def backup_diff(a: int, b: int, request: Request) -> HTMLResponse:
    """备份差异对比"""
    mgr = BackupManager(settings)
    try:
        diff_text = mgr.diff_backups(a, b)
    finally:
        mgr.close()
    if diff_text is None:
        return HTMLResponse("<div class='error'>Backup records not found</div>", status_code=404)
    if not diff_text:
        return HTMLResponse("<div class='info'>No differences</div>")
    return HTMLResponse(f"<pre class='diff-content'>{_escape_html(diff_text)}</pre>")


@app.get("/schedules", response_class=HTMLResponse)
async def schedule_list(request: Request) -> HTMLResponse:
    """调度任务管理"""
    sched = BackupScheduler(settings)
    try:
        entries = sched.list_schedules()
    finally:
        sched.close()
    return _render("schedules.html", request, schedules=entries)


@app.post("/schedules/add")
async def schedule_add(request: Request) -> HTMLResponse:
    """添加调度（HTMX 表单提交）"""
    form = await request.form()
    name = form.get("name", "").strip()
    interval = form.get("interval", "").strip()
    if not name or not interval:
        return HTMLResponse("<div class='error'>Name and interval required</div>", status_code=400)

    try:
        from netadmin.scheduler import CrontabExpression, parse_interval
        crontab = parse_interval(interval)
    except ValueError as e:
        return HTMLResponse(f"<div class='error'>{_escape_html(str(e))}</div>", status_code=400)

    sched = BackupScheduler(settings)
    try:
        expr = CrontabExpression(*crontab.split(), raw=crontab)
        sched.add(name, crontab, expr.describe())
    finally:
        sched.close()

    return RedirectResponse(url="/schedules", status_code=303)


@app.post("/schedules/{schedule_id}/toggle")
async def schedule_toggle(schedule_id: int) -> HTMLResponse:
    """启用/禁用调度（HTMX）"""
    sched = BackupScheduler(settings)
    try:
        entries = sched.list_schedules()
        entry = next((e for e in entries if e.id == schedule_id), None)
        if entry is None:
            return HTMLResponse("<div class='error'>Not found</div>", status_code=404)
        sched.toggle(schedule_id, not entry.enabled)
    finally:
        sched.close()
    return RedirectResponse(url="/schedules", status_code=303)


@app.post("/schedules/{schedule_id}/delete")
async def schedule_delete(schedule_id: int) -> HTMLResponse:
    """删除调度（HTMX）"""
    sched = BackupScheduler(settings)
    try:
        sched.remove(schedule_id)
    finally:
        sched.close()
    return RedirectResponse(url="/schedules", status_code=303)


@app.post("/schedules/run")
async def schedule_run() -> HTMLResponse:
    """立即执行所有调度（HTMX）"""
    sched = BackupScheduler(settings)
    try:
        results = sched.run_scheduled_backups()
    finally:
        sched.close()
    return RedirectResponse(url="/schedules", status_code=303)


@app.get("/health", response_class=HTMLResponse)
async def health_htmx(request: Request) -> HTMLResponse:
    """HTMX 端 — 返回设备健康卡片"""
    devices = settings.all_devices()
    checker = HealthChecker()
    cards: list[dict] = []
    for dev in devices:
        report = checker.check(dev)
        cards.append({
            "host": dev["host"],
            "name": dev.get("name", dev["host"]),
            "vendor": dev.get("vendor", ""),
            "error": report.get("error"),
            "cpu": report.get("cpu", "N/A"),
            "memory": report.get("memory", "N/A"),
            "temperature": report.get("temperature", "N/A"),
            "uptime": report.get("uptime", "N/A"),
            "log_errors": report.get("log_errors", "N/A"),
        })
    return _render("_health_cards.html", request, cards=cards)


# ── 辅助 ─────────────────────────────────────────────────────


def _escape_html(text: str) -> str:
    """HTML 转义"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── CLI 入口 ─────────────────────────────────────────────────


def run_web(host: str = "127.0.0.1", port: int = 8099, reload: bool = False) -> None:
    """启动 Web 服务器"""
    try:
        import uvicorn  # noqa: F811
    except ImportError:
        raise ImportError(
            "uvicorn is required for the web dashboard. "
            "Install with: pip install netadmin[web]"
        )
    if host == "0.0.0.0":
        import logging as _lg
        _lg.warning("Web dashboard listening on 0.0.0.0 — accessible to all network hosts. Set NETADMIN_WEB_USER and NETADMIN_WEB_PASS for authentication.")
    uvicorn.run("netadmin.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    run_web()