---
version: 1.1.2
status: stable
category: tool
emoji: 🛡️
---

# IPCheck Monitor

Windows 系统托盘网络环境监控工具。定时调用 ipcheck 检测 IPv6 泄露、DNS 国内服务商、IP 风险评分、时区一致性，异常时托盘变色并弹窗提醒。

## 已完成

### v1.1.2 (2026-06-18)

- warn 级别结论也触发告警通知：IP 信息获取失败、DNS 获取失败、时区无法比对、IP 风险中等等场景不再静默，托盘弹窗提醒用户排查

### v1.1.1 (2026-06-16)

- 弹窗提示全局置顶：DNS 异常确认框及修复结果弹窗设为 topmost，确保在全屏/后台场景下不被遮挡
- 托盘右下角系统通知保持不动（位置由 Windows 系统控制）

### v1.1.0 (2026-06-14)

- 启动自动提权：`main()` 入口检测权限，非管理员时用 `ShellExecuteW runas` 重新启动并弹 UAC 框（spec `uac_admin=True` 当前 PyInstaller 版本不支持，已移除）
- DNS 异常自动弹窗：首次检测到国内 DNS 时弹确认框，用户点「是」立即修复，状态恢复后下次再检测会重新提示
- 单实例保护改用 Windows Named Mutex，进程退出/崩溃/断电后内核自动释放，不再依赖 lock file

### v1.0.0 (2026-06-14)

- 托盘常驻，启动后最小化到系统托盘
- 定时检测（默认 40 秒，可配置，最小 10 秒）
- 检测项：IPv6 泄露 / DNS 国内服务商 / IP 风险评分 / 时区一致性
- 异常/恢复 Windows 通知，托盘图标变色（绿/黄/红）
- 双击托盘图标显示检测详情窗口
- 一键修复 DNS（切换为 Cloudflare for Families）
- 设置面板：间隔、网卡、DNS、时区，持久化到 config.json
- 时区「应用」按钮立即写入用户级 TZ 环境变量
- 单实例保护（lock file）
- PyInstaller 打包为单文件 exe（build.bat）

## 进行中

（无）

## 待规划

- 检测历史记录（本地存储，支持查看趋势）
- 开机自启动选项
- 更多检测项（WebRTC 泄露等）
- 托盘右键菜单显示最近检测摘要
