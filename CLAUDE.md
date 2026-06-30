# IPCheck Monitor — 项目规范

## 项目定位

Windows 系统托盘网络环境监控工具，依赖 `ai-ipcheck` 库做检测，GUI 用 tkinter + pystray。

## 文件职责

| 文件 | 职责 |
|------|------|
| `app.py` | 主程序：窗口、托盘、定时调度、UI 更新、通知 |
| `checker.py` | ipcheck 库封装，唯一出口是 `run_check()` → dict |
| `config.json` | 运行时配置，由 `app.py` 读写，不进 git |
| `build.bat` | 一键 PyInstaller 打包 |
| `IPCheckMonitor.spec` | PyInstaller spec，打包参数变化时更新 |
| `docs/` | 截图等文档资源 |

## 验证命令

```bash
# 直接运行（需要 Windows 环境）
python app.py

# 单独测试检测逻辑
python -c "from checker import run_check; import json; print(json.dumps(run_check(), ensure_ascii=False, indent=2))"

# 打包
build.bat
```

## 约束

- `checker.py` 只做数据封装，不含任何 UI 逻辑
- `run_check()` 返回 dict 结构不变，新增字段用 None/默认值填充，不删除已有字段
- `config.json` 不进 git（已在 .gitignore 或手动排除）
- 打包产物 `dist/` 不进 git
- Windows 弹窗/子进程调用必须加 `CREATE_NO_WINDOW` flag，防止控制台闪烁
- 单实例保护用 Named Mutex（`Global\IPCheckMonitor_SingleInstance`），不要改回 lock file
- 管理员权限检测：`_is_admin()` + `_elevate()`，`main()` 入口处调用；spec 不加 `uac_admin=True`（当前 PyInstaller 版本不支持，加了会报错）
- DNS 弹窗用 `_last_dns_cn` 追踪状态变化，只在首次检测到国内 DNS 时弹（非每轮都弹）；`_dns_prompt_showing` 防止弹窗期间重复弹出，已有弹窗时改用托盘通知
- 基线对比用 `_baseline_mismatch` 追踪状态变化，只在首次检测到差异时托盘通知（恢复一致后再变化才重新通知）；基线数据存 `config.json` 的 `baseline` 字段
- 网卡列表用 `get_network_interfaces()` 从 `netsh interface show interface` 获取，按列偏移解析适配中英文，GBK 解码 + `errors="replace"` 兜底，`except Exception` 回退默认列表；设置面板用 Combobox 可选可编辑
- 子窗口（关于、基线、设置）统一用 `_center_on_parent()` 居中于主窗口
- 代理模式存 `config.json` 的 `proxy_mode`（`"system"` 或 `"custom"`）和 `proxy_url` 字段；`_do_check()` 在调用 `run_check()` 前临时注入 6 个代理环境变量（HTTP/HTTPS/ALL，大小写各一），执行完毕后恢复原值——`"custom"` 注入 `proxy_url`；`"system"` 注入 `get_windows_proxy()` 从 IE 注册表（`HKCU\...\Internet Settings` 的 `ProxyEnable`/`ProxyServer`）读出的系统代理，IE 未开代理时清空环境变量确保直连（覆盖残留）；PAC 自动配置脚本和 socks 代理不支持（requests 固有限制）
- 版本号在 `app.py` 顶部 `VERSION` 常量维护，发版时同步更新 `VERSION`、`ROAD_MAP.md` frontmatter `version`、GitHub Release tag
- GitHub 仓库：`restarthua/ipcheck-monitor`（公开），Release 附带打包好的 exe

## 依赖

- `ai-ipcheck>=0.2.0` — 核心检测库，升级前验证 API 兼容性
- `pystray>=0.19` — 系统托盘，仅支持 Win32 backend
- `Pillow>=9.0` — 托盘图标生成
