# ADR-002: CLI 框架选 Click 而非 Argparse

## 背景
需要 CLI 框架，支持子命令（`netadmin vlan list`、`netadmin backup run`）、自动生成 help、参数校验。

## 选项
1. **Click** — 装饰器风格，子命令支持好，生态丰富
2. **Argparse** — 标准库内置，但子命令和 help 需要手写
3. **Typer** — Click 的现代封装，类型提示驱动

## 决策
选 **Click**。理由：
- Typer 还较新，生态不如 Click 成熟
- Argparse 对于"13 个子命令"的规模需要太多样板代码
- Click 的 `@click.group` / `@click.argument` 正好匹配需求

## 后果
- 正向：开发速度快，help 自动生成
- 代价：依赖第三方库（但已经是事实标准，风险极低）