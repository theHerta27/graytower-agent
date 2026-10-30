# GitHub 与本地版本管理

灰塔仓库：[theHerta27/graytower-agent](https://github.com/theHerta27/graytower-agent)。`main` 展示当前版本，开发分支保留后续改动与历史。

## 下载项目

```powershell
git clone https://github.com/theHerta27/graytower-agent.git
cd graytower-agent
```

安装依赖与启动步骤见 [README](README.md#安装与运行) 和 [开始使用](开始使用.md)。GitHub 代码仓库不包含本机虚拟环境、密钥、用户任务数据库或模型会话。

## 提交与推送

先查看改动，确认需要发布的文件，再提交和推送：

```powershell
git status
git diff
git add README.md
git commit -m "Update project documentation"
git push origin HEAD
```

`git add` 选择文件，`git commit` 保存本地版本，`git push` 才上传。未提交文件不会自动上传。多人或多台电脑协作时，先获取远端更新，再检查分支差异。

## 开发分支合入 main

若主干没有额外提交，可快进合并；若两边都有新提交，先处理合并并重新测试。无论哪种方式，都应检查最终准备发布的代码。

```powershell
git fetch origin
git log --oneline --graph --decorate --all -15
```

灰塔替游戏项目管理的任务 Worktree 与本仓库自身的开发分支是两件事。任务的合入、撤销与归档操作见 [Git 工作树与交付说明](Git工作树与交付说明.md)。
