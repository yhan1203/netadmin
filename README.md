# netadmin

**华为 & 思科统一交换机管理工具** | *Unified Huawei & Cisco Switch Manager*

一个开箱即用的命令行网络设备管理工具。不是 Python 库，是运维可以直接用的瑞士军刀。

```bash
pip install netadmin
```

```bash
# 一键备份所有设备
netadmin backup run

# 照猫画虎：从设备学配置，部署到另一台
netadmin learn 10.0.1.1 -o template.yaml
netadmin apply template.yaml -d 10.0.1.2

# 审计合规
netadmin audit --all
```

![Demo](https://img.shields.io/badge/demo-live-brightgreen)
```text
╭──────────────────────────────────────────╮
│ netadmin — 华为 & 思科统一交换机管理工具  │
╰──────────────────────────────────────────╯

┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 健康 192.168.1.1 │ │ 健康 192.168.1.2 │ │ 健康 192.168.1.3 │
│ CPU: 23%         │ │ CPU: 67% ⚠       │ │ CPU: 5%          │
│ Memory: 45%      │ │ Memory: 82% ⚠    │ │ Memory: 22%      │
│ Temp: 42°C       │ │ Temp: 55°C ⚠     │ │ Temp: 38°C       │
│ Log: 0 (clean)   │ │ Log: 5 errors    │ │ Log: 0 (clean)   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

运行 `python3 demo.py` 查看更多演示效果。

---

## ✨ 功能矩阵

| 功能 | 命令 | 说明 |
|------|------|------|
| 设备发现 | `netadmin scan 192.168.1.0/24` | Ping 扫描 + SSH Banner 识别厂商 |
| 连接测试 | `netadmin connect <host>` | 测试 SSH 连接并自动识别厂商 |
| 命令执行 | `netadmin exec <host> "cmd"` | 单台执行 |
| 批量执行 | `netadmin exec-all "cmd"` | 全部设备同时执行 |
| VLAN 管理 | `netadmin vlan list/create/delete <host>` | 查看/创建/删除 VLAN |
| 端口分配 | `netadmin vlan assign <host> <port> <vlan>` | Access/Trunk 端口配置 |
| 接口状态 | `netadmin interface list <host>` | 接口 Up/Down 一目了然 |
| 配置备份 | `netadmin backup run` | 备份所有设备到本地 |
| 配置对比 | `netadmin backup diff <id1> <id2>` | 两次备份的差异对比 |
| 配置回滚 | `netadmin backup restore <id>` | 查看历史版本内容 |

### 🔥 照猫画虎（核心卖点）

```bash
# 照猫：从一台配好的设备学习配置
netadmin learn 10.0.1.1 -o template.yaml

# 模板内容（自动脱敏，IP/名称用占位符替换）
cat template.yaml
```

```yaml
device:
  hostname: "{{HOSTNAME}}"
  vendor: huawei
vlans:
  - id: 10;  name: office
  - id: 20;  name: voip
interfaces:
  - name: GigabitEthernet0/0/1;  mode: trunk;   vlans: "10 20"
  - name: GigabitEthernet0/0/2;  mode: access;  vlans: "10"
ntp:
  servers: ["ntp.example.com"]
```

```bash
# 画虎：把模板部署到目标设备
netadmin apply template.yaml -d 10.0.1.2

# 批量部署
netadmin apply template.yaml -d 10.0.1.2,10.0.1.3,10.0.1.4

# 试运行（不做实际变更）
netadmin apply template.yaml -d 10.0.1.2 --dry-run
```

### 🏥 巡检与审计

```bash
# 单台健康检查（CPU/内存/温度/日志错误）
netadmin check 10.0.1.1

# 全量巡检
netadmin check --all

# 安全合规审计（密码加密/SNMP/SSH/VTY/ACL/日志）
netadmin audit 10.0.1.1
```

| 审计项 | 检查内容 |
|--------|----------|
| 密码加密 | 是否使用 cipher 或 service password-encryption |
| SNMP 安全 | 是否使用默认 community public |
| SSH 版本 | 是否禁用 SSH v1 |
| VTY 访问控制 | 管理口是否有 ACL 限制 |
| 登录 Banner | 是否有法律告警 |
| VLAN 1 风险 | 端口是否直接使用默认 VLAN 1 |
| 日志审计 | 日志是否开启 |
| NTP 同步 | 是否配置了 NTP |

---

## 🚀 快速开始

```bash
# 安装
pip install netadmin

# 编辑设备清单
cp config.yaml example.yaml
vim config.yaml    # 填入你的设备

# 连接测试
netadmin connect 10.0.1.1

# 全量备份
netadmin backup run

# 一键巡检
netadmin check --all
```

支持通过环境变量传入密码，避免密码出现在命令行历史：

```bash
export NETADMIN_PASS_10_0_1_1=MySecretPass
netadmin connect 10.0.1.1
```

---

## ⚙️ 支持的设备

| 厂商 | 型号系列 | Netmiko device_type |
|------|---------|---------------------|
| **华为 Huawei** | S Series, CE Series, CloudEngine | `huawei` |
| **思科 Cisco** | Catalyst, ISR, ASR, Nexus | `cisco_ios` |

> 理论上所有 Netmiko 支持的设备类型都可用，传 `--device-type` 参数即可。

---

## 📦 项目结构

```
netadmin/
├── netadmin/
│   ├── cli.py          # Click 命令定义
│   ├── connector.py    # 华为/思科连接封装
│   ├── commands.py     # 厂商命令映射
│   ├── backup.py       # 配置备份 + Diff
│   ├── vlan.py         # VLAN 管理
│   ├── interface.py    # 接口状态
│   ├── learn.py        # 照猫 — 配置学习
│   ├── apply.py        # 画虎 — 配置部署
│   ├── scanner.py      # 网段设备发现
│   ├── checker.py      # 健康检查 + 安全审计
│   └── config.py       # 配置加载
├── tests/
├── config.yaml         # 设备清单模板
├── pyproject.toml
└── README.md
```

---

## 🔧 开发

```bash
git clone https://github.com/yhan1203/netadmin.git
cd netadmin
pip install -e ".[dev]"
pytest
```

---

## 📄 License

MIT

---

**Made by [@yhan1203](https://github.com/yhan1203)** — 如果好用，点个 Star ⭐

---

> **关键词：** 网络自动化 · 华为交换机管理 · 思科交换机管理 · 配置备份 · 配置克隆 · 安全审计 · 网络设备发现 · CLI 运维工具