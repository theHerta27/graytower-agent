$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$taskRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
Write-Host '[1/4] 创建本机Python环境（不包含任何模型调用）'
if (!(Test-Path '.venv/Scripts/python.exe')) { & py -3.11 -m venv .venv; if ($LASTEXITCODE -ne 0) { throw '请先安装Python 3.11。' } }
& ./.venv/Scripts/python.exe -m pip install -r requirements-v1.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Python依赖安装失败，请检查网络后重试。' }
Write-Host '[2/4] 安装官方SDK及配对Runtime'
if (!(Test-Path '.venv-coding/Scripts/python.exe')) { & py -3.11 -m venv .venv-coding }
& ./.venv-coding/Scripts/python.exe -m pip install -r requirements-coding.lock.txt
if ($LASTEXITCODE -ne 0) { throw '官方SDK依赖安装失败。' }
Write-Host '[3/4] 构建浏览器页面'
Push-Location frontend
try { & npm.cmd ci --ignore-scripts; if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }; & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw '页面构建失败。' } } finally { Pop-Location }
Write-Host '[4/4] 构建匹配游戏回归的Python3.11.9镜像（先启动Docker Desktop）'
$taskDocker=Get-Command docker -ErrorAction SilentlyContinue
if ($taskDocker) { $taskDockerPath=$taskDocker.Source } else { $taskDockerPath=Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe' }
if (!(Test-Path -LiteralPath $taskDockerPath)) { throw '未找到Docker Desktop，请安装并启动后重试。' }
& $taskDockerPath build --build-arg 'PYTHON_BASE=public.ecr.aws/docker/library/python@sha256:f9ce6fe33d9a5499e35c976df16d24ae80f6ef0a28be5433140236c2ca482686' -t graytower-development-runner:py3119 infrastructure/development-runner
if ($LASTEXITCODE -ne 0) { throw 'Docker检查镜像构建失败，请检查网络与引擎。' }
$taskImage=(& $taskDockerPath image inspect graytower-development-runner:py3119 --format '{{.Id}}').Trim()
if ($taskImage -notmatch '^sha256:[a-f0-9]{64}$') { throw '无法确认镜像身份。' }
New-Item -ItemType Directory -Path local-data -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $taskRoot 'local-data/development-image.json'),(@{image=$taskImage;python='3.11.9'} | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
Write-Host '安装完成。请双击“打开灰塔研发助手.cmd”。不会把SDK、Runtime或密钥上传GitHub。'
