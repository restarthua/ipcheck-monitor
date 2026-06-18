# IPCheck Monitor

Windows 系统托盘网络环境监控工具，定时调用 ipcheck 检测，异常弹窗提醒。

## 使用方式

### 直接运行

```bash
pip install -r requirements.txt
python app.py
```

### 打包为 exe

双击 `build.bat` 或手动执行：

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name IPCheckMonitor --add-data "checker.py;." --hidden-import ipcheck --hidden-import ipcheck.cli --hidden-import pystray._win32 app.py
```

产出：`dist/IPCheckMonitor.exe`

## 功能

- 启动后最小化到系统托盘，定时自动检测（默认 40 秒，可配置）
- 检测项：IPv6 泄露、DNS 国内服务商、IP 风险评分、时区一致性
- 异常时托盘变红 + Windows 弹窗通知，恢复后托盘变绿
- 双击托盘图标显示详情窗口
- 支持一键修复 DNS（切换为 Cloudflare 安全 DNS）
- 单实例运行，防止重复启动

## 设置

点击主窗口底部「设置」按钮，可配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 检测间隔 | 40 秒 | 最小 10 秒，修改后下次检测立即生效 |
| 网卡名称 | WLAN | DNS 修复时使用的网卡 |
| 主 DNS | 1.1.1.2 | Cloudflare for Families |
| 备 DNS | 1.0.0.2 | Cloudflare for Families |
| 时区 | （空） | IANA 时区名，如 America/Los_Angeles |

- 配置持久化到同目录 `config.json`，重启后自动加载
- 时区右侧「应用」按钮立即生效（设置用户级 TZ 环境变量）
- 启动时自动应用已保存的时区

## 文件结构

```
app.py              主程序：窗口 + 托盘 + 定时检测
checker.py          ipcheck 库函数封装，返回结构化结果
config.json         配置文件（自动生成）
build.bat           一键打包脚本
requirements.txt    Python 依赖
```
