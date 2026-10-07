# GitHub 私密仓库使用手册

## 本机和 GitHub 是怎样连接的

本机 Git 保存版本历史；GitHub 保存远程副本；GitHub CLI（`gh`）负责登录和创建仓库。它们不会实时同步整个文件夹。

本次采用两个私密仓库：

- Agent 工作台：https://github.com/theHerta27/mihoyo-agent-project
- 游戏底座：https://github.com/theHerta27/graytower-game

上传前检查了已有历史中的凭据模式、大文件和被跟踪的安装包/数据库；只按明确文件清单提交。SDK、Codex Runtime、虚拟环境、Unity 缓存与构建、本地数据库、个人编辑器设置不上传。历史证据保留；未将上传等同于四个 Agent 全部交付。

本机原游戏 `origin` 指向旧 `combat-foundation`，此次保留为 `local-baseline`，新 `origin` 指向 GitHub。工作台原先没有远端，此次增加 GitHub `origin`。首次将本地已审阅分支推到远程 `main`，不强制推送、不删除历史。

## 登录与查看连接

在 PowerShell 中执行：

```powershell
gh auth login -h github.com -p https -w
gh auth status
```

浏览器确认账号后，凭据由本机凭据存储管理。不要把 Token 写进仓库或发送给别人。检查远端时进入项目目录：

```powershell
git remote -v
git status
```

`origin` 是远端名称，URL 指定目标仓库；它不是模型接口。上传代码不需要调用 DeepSeek，也不会同步 API Key。

## 以后怎样更新

每次先查看改动，再明确选择文件提交。以下路径是示例，换成实际修改的文件：

```powershell
git status
git diff
git add src/agent_workbench/config/workflow.py
git commit -m "Improve config requirement handling"
git push origin HEAD:main
```

`add` 选择文件，`commit` 保存本地版本，`push` 才上传。没有提交的文件不会因普通 push 自动上传。当前本机开发分支仍可保留原名称；远程展示入口为 `main`。不要在多台电脑同时工作时盲目强制推送；先检查远程变化并合并。

## 换一台 Windows 电脑运行

安装 Git、Python 3.11、Node.js，并登录有权限的 GitHub 账号；Unity 演示需安装对应 Unity 版本和 Windows 构建组件。两个仓库放在同一个父目录，保留以下名字：

```powershell
git clone https://github.com/theHerta27/mihoyo-agent-project.git
git clone https://github.com/theHerta27/graytower-game.git
cd mihoyo-agent-project
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-v1.lock.txt
.venv/Scripts/python.exe -m pip install -e . --no-deps
py -3.11 -m venv research/.venv-coding
research/.venv-coding/Scripts/python.exe -m pip install -r requirements-coding.lock.txt
```

Coding 的安装清单会安装 SDK 和配套 `codex.exe`，不需要上传整套虚拟环境。再安装当前游戏：

```powershell
py -3.11 -m venv ../graytower-game/.venv
../graytower-game/.venv/Scripts/python.exe -m pip install -e "../graytower-game[host,dev]"
```

数值验证需要历史固定基线，以保持实验规则一致。从游戏仓库历史还原，不需要额外第三个仓库：

```powershell
.venv/Scripts/python.exe scripts/prepare_verification_baseline.py
py -3.11 -m venv ../graytower-game/local-data/verification-baseline/.venv
../graytower-game/local-data/verification-baseline/.venv/Scripts/python.exe -m pip install -e ../graytower-game/local-data/verification-baseline
```

固定版本是 `fdb9e8387af696482bf2b57d1543484f8b08495c`。本机仍有旧 `D:/Desktop/combat-foundation` 时沿用它，以免破坏已有实验；新机器使用还原目录。Git 还原的文件换行可能与旧 Windows 工作区不同，因此源文件字节指纹可能不同；新候选重新冻结身份，不能复用旧报告。不要把旧报告当成新规则的验证结果。需要在本机显式选用还原基线时，在启动前设置 `$env:AGENT_WORKBENCH_GAME_ROOT=(Resolve-Path ../graytower-game/local-data/verification-baseline).Path`；这项设置由本机操作人员负责，页面不能修改它。

构建网页：

```powershell
cd frontend
npm ci
npm run build
cd ..
```

此后双击 `打开研发工作台.cmd` 查看工作台。Unity Player 不在源码仓库里，按游戏仓库的构建说明生成并封存产品构建，再使用 `开始剧情演示.cmd`。玩家流程见 `使用手册.md`。当前 NPC 台词模式为离线演示。

真实模型任务还需要本机 `DEEPSEEK_API_KEY` 和明确预算。安装完成不等于获得新评测调用授权；封存批次不得重新运行续费。

## 本次上传的验证记录

实际提交、推送、私密状态和克隆检查以根目录 `current_context.md` 最新上传记录为准。忽略目录中的原始数据和构建仍保留本机；GitHub 不是完整桌面备份。
