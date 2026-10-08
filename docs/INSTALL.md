# 安装与运行说明

## 安装

支持 **Windows + Codex 桌面 + Python 3.11–3.14**，需要 Git。PowerPoint 预览需要桌面版 PowerPoint；AI 输出需要 Illustrator 已运行且打开目标文档。后台等待和原聊天唤醒依赖 Codex 桌面的本地 app-tools 接口与 Node.js；脚本会查找 Codex 自带运行时，找不到时需安装 Node.js 并加入 PATH。版本变化时可先运行 `probe` 检查。

在 PowerShell 中执行。以下是全新安装；若目标文件夹已存在，先检查已有安装和运行中任务，不要覆盖正在使用的脚本。

```powershell
$skillsRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex/skills' }
New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null
git clone https://github.com/yrui-cmd/cell_cns_figure.git (Join-Path $skillsRoot 'cell_cns_figure')
if ($LASTEXITCODE -ne 0) { throw 'Skill 下载失败，请检查目标目录和网络' }
python -m pip install -r (Join-Path $skillsRoot 'cell_cns_figure/requirements.txt')
```

SVG 转换复用 [cell_su7](https://github.com/yrui-cmd/cell_su7) 的脚本，需要与本 Skill 同级安装。如果已经安装 `cell_su7`，可跳过下面的复制。本版本在该依赖的 `95dce2b972d8b93f36a95e7f045f4d3910a44313` 提交上验证。

```powershell
$su7Source = Join-Path $env:TEMP ('cell-su7-source-' + [guid]::NewGuid().ToString('N'))
git clone https://github.com/yrui-cmd/cell_su7.git $su7Source
if ($LASTEXITCODE -ne 0) { throw 'cell_su7 下载失败' }
git -C $su7Source checkout 95dce2b972d8b93f36a95e7f045f4d3910a44313
if ($LASTEXITCODE -ne 0) { throw 'cell_su7 版本切换失败' }
$su7Target = Join-Path $skillsRoot 'cell_su7'
if (Test-Path -LiteralPath $su7Target) { throw 'cell_su7 已存在，请检查现有安装' }
Copy-Item -LiteralPath (Join-Path $su7Source 'plugins/cell_su7/skills/cell_su7') -Destination $su7Target -Recurse
```

最终结构：

```text
skills/
  cell_cns_figure/
    SKILL.md
    backends/fig1/
    backends/fig2/
  cell_su7/
    scripts/
```

让 Codex 重新加载 Skills 后，在聊天中调用：

> 用 cell_cns_figure 处理这张图，输出 PPT。

或者：

> 用 cell_cns_figure 的2号处理以下科研文字，输出 Adobe Illustrator 文件。

图片上限为10 MiB；2号文字上限为500000字符。PDF 需先按指定页转成 PNG/JPG。首次使用需要有效的小描客户登录号及足够额度，凭据通过标准输入写入当前 Windows 用户的 DPAPI 密文文件。

## 运行与恢复

提交后，独立 Python 进程等待结果，收到 SVG 后校验任务、费用和文件哈希，再通知原 Codex 聊天继续转换。每个订单使用持久请求ID，响应丢失时恢复同一订单。1号已有的19额度历史订单继续按原回执处理，新订单为20额度。

首次提交会注册当前 Windows 用户的恢复任务：`CellCnsFig1_Client_Recovery` 或 `CellCnsFig2_Client_Recovery`。恢复器每分钟及登录后检查已登记任务。电脑重启后需重新登录并打开 Codex；它不会创建新的付费订单。`stop` 只停止本地接收，不代表远端取消或退款。

仅检查桌面连接（不提交、不扣费）：

```powershell
python -X utf8 '<Skill目录>/backends/fig1/scripts/client.py' probe
```

具体命令见 [1号客户端](../backends/fig1/references/client.md)、[2号客户端](../backends/fig2/references/client.md)。不要在任务进行中移动 Skill 或删除任务目录；恢复必须保留原目录、原请求ID、原客户和原聊天。

## 输出与适用边界

输出为原生可编辑 PPTX 或 AI，并保留接收到的 SVG。这里只调用 `cell_su7` 的 SVG 转换脚本，不调用其图片识别或其他收费入口。

直接路径映射保留坐标、变换、叠放顺序及复合路径；裁剪、蒙版和滤镜不参与转换，渐变取首色，虚线转实线，曲线文字转为锚点处普通文字。因此可编辑文件可能与 SVG 渲染有差异。交付前仍需查看实际预览。

本版本本地验证了60项测试，包括模拟服务接发、重复提交保护、历史价格恢复、SVG校验和真实原生PPTX文件生成；未提交收费测试订单，也未在发布测试中运行真实 Illustrator 或完整线上生成流程。

## 开发测试

保持上述同级依赖结构，在仓库根目录分别运行两个测试套件（使用独立进程，避免同名模块冲突）：

```powershell
python -X utf8 -m unittest discover -s backends/fig1/tests -v
python -X utf8 -m unittest discover -s backends/fig2/tests -v
```

## 数据与许可

客户输入会通过 HTTPS 发送给 [小描服务](https://xiaomiao-ai.com/)。服务需要客户账户和额度，开源客户端不包含免费服务额度、服务端代码或第三方软件许可。本仓库不包含客户凭据、真实任务或生成素材。请将任务目录放在仓库外。

客户端代码按 [MIT License](../LICENSE) 发布；依赖项目和第三方应用遵循各自许可证。
