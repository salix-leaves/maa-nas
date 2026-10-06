# maa-nas · 在 NAS 上跑《明日方舟》日常

用 Docker 把 [MAA](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 跑在 **NAS** 上，
通过 **ADB 远程控制 PC 上 MuMu 模拟器**里的《明日方舟》清日常 —— 游戏和模拟器都在 PC，鼠标键盘完全不受影响。

## 工作原理

```
   NAS (Linux + Docker)                       PC (Windows)
 ┌──────────────────────┐                  ┌─────────────────────────┐
 │  maa 容器            │                  │  MuMu 模拟器            │
 │  ├─ maa-cli + MaaCore│                  │   └─ 明日方舟           │
 │  ├─ Web 手动开关 :5599│                  │                         │
 │  └─ run-daily.sh     │                  │                         │
 └──────────┬───────────┘                  └────────────▲────────────┘
            │ 1) adb 连不上 → ssh 触发计划任务 ─────────┘
            │    (计划任务跑在 PC 登录会话里，才能拉起 MuMu 图形主程序)
            │ 2) adb connect → maa run daily
            └───────────────────────────────────────────────────────
```

**关键点**：SSH 会话是非交互的，启动不了 MuMu 的图形主程序，所以必须借 Windows **计划任务**来完成。

## 功能

- 一键日常：开始唤醒 → 自动公招 → 基建换班 → 信用购物 → 领取奖励 → 刷理智 → 关闭游戏
- **网页手动开关**：开始 / 停止 / 实时日志，支持「记住我」免密
- **模拟器没开也能自动拉起来**（SSH + 计划任务）
- 可选定时执行（默认关闭）

## 前置要求

- NAS：能跑 Docker，能访问 PC 的局域网 IP
- PC：Windows 10/11 + [MuMu 模拟器 12](https://mumu.163.com/)，里面装好《明日方舟》且已登录
- 两者在同一局域网

## 一、PC 侧配置

### 1. 装 OpenSSH 服务端（管理员 PowerShell）

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

装不上（LTSC / 精简版常见）就去 [PowerShell/Win32-OpenSSH](https://github.com/PowerShell/Win32-OpenSSH/releases)
下载 zip，解压到 `C:\Program Files\OpenSSH`，管理员执行 `install-sshd.ps1`，再 `Start-Service sshd`。

### 2. 加入 NAS 的公钥

NAS 上先生成：`ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519`，取 `id_ed25519.pub` 内容。

> ⚠️ 若 Windows 账号属于 **Administrators** 组（多数人都是），Windows **只读**
> `C:\ProgramData\ssh\administrators_authorized_keys`，**不读** `~/.ssh/authorized_keys`。

管理员 PowerShell：

```powershell
$key = "ssh-ed25519 AAAA...把公钥贴这里... maa@nas"
$f = "$env:ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }
Add-Content -Path $f -Value $key -Encoding ascii
icacls $f /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
```

验证（在 NAS 上）：`ssh 你的用户名@PC的IP hostname` 应直接返回电脑名。

### 3. 建计划任务

新建 `D:\mumu\maa-start.cmd`（路径按你的实际安装位置改）：

```bat
@echo off
"D:\mumu\MuMuPlayer-12.0\nx_main\MuMuManager.exe" control -v 0 launch -pkg com.hypergryph.arknights
```

然后（普通权限即可）：

```powershell
schtasks /create /tn "MAA-StartMuMu" /tr "D:\mumu\maa-start.cmd" /sc once /st 00:00 /f
```

确认 `Logon Mode: Interactive only`：

```powershell
schtasks /query /tn MAA-StartMuMu /v /fo LIST
```

> `MuMuManager.exe` 一般在 `...\MuMuPlayer-12.0\nx_main\` 下。
> 找法：任务管理器 → 右键 MuMu 进程 → 打开文件所在位置。

## 二、NAS 侧部署

```bash
git clone https://github.com/salix-leaves/maa-nas.git
cd maa-nas

bash prepare.sh          # 下载 maa-cli / MaaCore / adb 到构建上下文
cp .env.example .env
vi .env                  # 填 PC 的 IP、SSH 用户名、MuMuManager 路径、Web 密码

docker compose up -d --build
```

### 或者直接用现成镜像（免构建）

不想自己 build 的话，仓库已把镜像发布到 GHCR：

```bash
docker pull ghcr.io/salix-leaves/maa-nas:latest
cp .env.example .env
vi .env
docker compose -f docker-compose.ghcr.yml up -d
```

> 镜像由 **GitHub Actions 自动构建**：推送到 `master` 会更新 `latest`，
> 打 `v*` 标签会生成对应版本标签。见 `.github/workflows/build.yml`。

打开 `http://<BIND_IP>:5599`（默认只绑 127.0.0.1），用 `.env` 里的 `MAA_WEB_PASSWORD` 登录。

**免密登录**：第一次用 `http://<IP>:5599/?k=<密码>` 打开一次，会写入一年有效的 Cookie，之后直接进。

## 使用

| 方式 | 命令 |
| --- | --- |
| 网页（推荐） | 打开 `http://<IP>:5599`，在**功能选单**里点要跑的任务 |
| 命令行 | `docker exec maa run-daily.sh`（跑 `config/tasks/daily.toml`） |
| 看日志 | `tail -f log/run.log` |
| 停掉当前任务 | 网页点「停止」，或 `docker exec maa pkill -f run-daily.sh` |

### 网页功能选单

页面上的按钮是**扫 `config/tasks/*.toml` 自动生成**的，文件名就是任务 ID：

| 任务 | 做什么 |
| --- | --- |
| `daily` **一键长草** | 唤醒 → 公招 → 基建 → 购物 → 领奖 → 刷理智 → 关游戏 |
| `fight` | 只刷理智（1-7 × 6） |
| `infrast` | 只基建换班 |
| `recruit` | 只自动公招 |
| `mall` | 只信用购物 |
| `award` | 只领取奖励 |
| `annihilation` | 只打剿灭（自动识别每周合成玉进度，打满即停） |
| `roguelike` | 只自动肉鸽（默认 1 把） |
| `startup` | 只唤醒游戏（排障用，不关游戏） |
| `closedown` | 只关闭游戏 |

**新增或修改按钮**：在 `config/tasks/` 下加个 `.toml`，文件名即 ID，文件头两行注释用作显示：

```toml
# @name 显示名称
# @desc 按钮下面的说明文字
[[tasks]]
...
```

改完**刷新页面即可**，不用重建镜像、不用重启容器。

### ⚙ 参数设置子页面

每个任务卡片右下角有个 **⚙**，点进去就是该任务的参数编辑页 —— **直接在网页上改，不用碰配置文件**：

```
http://<IP>:5599/task/fight        ← 刷理智：关卡、次数、理智药、代理倍率…
http://<IP>:5599/task/annihilation ← 剿灭：关卡值/次数
http://<IP>:5599/task/roguelike    ← 肉鸽：主题、策略、分队、核心干员、探索次数…
http://<IP>:5599/task/infrast      ← 基建：模式、设施、无人机用途、心情阈值…
```

页面底部四个操作：

| 按钮 | 作用 |
| --- | --- |
| **💾 保存** | 写回 `.toml`，下次执行生效 |
| **↺ 恢复默认值** | 把所有参数值还原成内置默认（不提交，可以先看再决定保存） |
| **↩ 放弃修改** | 重新加载页面，丢掉未保存的改动 |
| **← 返回功能选单** | 回主页 |

#### 剿灭

想自动打满剿灭，用 `annihilation` 这个预设（或在刷理智的设置页把 `stage` 改成 `Annihilation`）：

```toml
params = { stage = "Annihilation", medicine = 0, stone = 0, series = -1, times = 2147483647 }
```

`Annihilation` = **当期剿灭**（自动识别是哪张图）。也可以填具体图，值必须完全一致：

| 关卡 | 值 |
| --- | --- |
| 当期剿灭 | `Annihilation` |
| 切尔诺伯格 | `Chernobog@Annihilation` |
| 龙门外环 | `LungmenOutskirts@Annihilation` |
| 龙门市区 | `LungmenDowntown@Annihilation` |

`series = -1` 关闭代理倍率切换（剿灭不支持倍率）；`times` 给一个很大的数，
MAA 每次打完会读每周合成玉进度，**满了就自动停**。如果它没停，网页上点「■ 停止」即可。

页面会把该任务里**每个 MAA 任务块**的参数列出来（勾选框控制是否启用），每项都带说明，
还有下拉选项（比如肉鸽主题、基建无人机用途）。改完点「💾 保存」直接写回 `.toml`，**下次执行即生效**。

内置了常见参数的说明和默认值（`webctl.py` 里的 `KNOWN` 字典），没列出来的参数会作为
「自定义参数」原样显示，不会被丢掉。


## 配置

- **任务清单** `config/tasks/daily.toml`：改完直接生效，不用重建镜像。
  参数含义见 [MAA 集成文档](https://docs.maa.plus/zh-cn/protocol/integration.html)。
- **连接配置** `config/profiles/default.toml`：首次运行自动生成，之后可手改。
- **定时**：`.env` 里 `MAA_CRON_TIME=04:30` 开启；`off` 为关闭。

## 常见问题

**模拟器拉不起来？**

1. PC 必须**已登录** —— 计划任务是 `Interactive only`，锁屏一般没事，但没有已登录用户时不会执行
2. `ssh <user>@<pc> schtasks /query /tn MAA-StartMuMu` 确认任务存在
3. `.env` 里 `MAA_MUMU_MANAGER` 的路径要对

**16384 端口连不上？**

MuMu「设置中心 → ADB 调试」选「本地和远程」（重启 MuMu 后可能重置）。
更稳的做法是在 PC 上做一次持久化端口转发：

```cmd
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=16385 connectaddress=127.0.0.1 connectport=16384
netsh advfirewall firewall add rule name="MuMu ADB 16385" dir=in action=allow protocol=TCP localport=16385
```

然后 `.env` 里把 `MAA_ADB_ADDRESS` 改成 `<PC的IP>:16385`。

**基建换班读不出干员技能？**

MAA 官方要求模拟器为**横屏 1280x720**。分辨率不对会导致技能文字 OCR 失败，任务反复重试出不来。

**PC 关机时能自动跑吗？**

不能。本仓库不含 Wake-on-LAN，需要的话可以自行在 `run-daily.sh` 的 `wake_pc()` 里扩展。

## 安全提醒

- Web 开关默认只绑 `127.0.0.1`，**不要暴露到公网**（它能操作你的游戏账号）
- `administrators_authorized_keys` 里的公钥 = PC 免密登录权限，保管好对应私钥
- `.env` 已在 `.gitignore` 中，别提交

## 说明

本项目只是把现成工具组合起来跑在 NAS 上，未修改 MAA 本体。
MAA 遵循其自身协议（AGPL-3.0），使用请一并遵守。
