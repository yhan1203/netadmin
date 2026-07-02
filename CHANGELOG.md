# 变更记录

## v0.1.0 (2026-07-02)

### 新增
- 项目首版发布
- SSH 连接华为/思科交换机（connector）
- 50+ 厂商命令映射，统一语义接口（commands）
- 13 个 CLI 命令，Rich 终端 UI
- 配置备份 + SQLite 版本管理 + 差异对比（backup）
- 照猫画虎：从设备学习配置生成模板（learn）→ 部署到目标设备（apply）
- 网段设备发现（scan）
- VLAN 管理（vlan list/create/delete/assign）
- 接口状态查询（interface list/detail）
- 设备健康检查（check）
- 安全合规审计（audit）
- GitHub Actions CI（Python 3.10~3.13 矩阵测试）
- 59 个单元测试，全部通过