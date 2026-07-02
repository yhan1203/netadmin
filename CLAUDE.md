# P001-netadmin — Claude 指令

## 项目简介
华为/思科统一交换机管理 CLI 工具。支持设备发现、配置备份、照猫画虎（配置克隆）、批量部署、安全审计。

## 环境
- Python 3.10+
- 依赖：`pip install -e ".[dev]"`
- 代理：`export http_proxy=http://127.0.0.1:10808 https_proxy=http://127.0.0.1:10808`

## 目录结构
```
P001-netadmin/
├── netadmin/        # 核心包
├── tests/           # pytest 测试
├── config.yaml      # 设备清单模板
├── pyproject.toml
├── README.md
├── CLAUDE.md
└── 复盘踩坑日志.md
```

## 常用命令
- 运行 CLI：`netadmin --help`
- 安装（开发模式）：`pip install -e ".[dev]"`
- 测试：`pytest`
- 测试 + 覆盖率：`pytest --cov netadmin --cov-report=term-missing`
- 推送到 GitHub：`git push`

## 项目特有规范
- 华为和思科的命令要通过 `commands.py` 映射，不要硬编码在 CLI 层
- 新增厂商命令映射需要更新 `commands.py` 的 `COMMAND_MAP`