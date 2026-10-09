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

SVG→PPT/AI 转换代码已随本 Skill 完整内置，不需要安装同级 cell_su7，也不会运行时下载或临时调用它。

最终结构：

```text
skills/
  cell_cns_figure/
    SKILL.md
    backends/fig1/
    backends/fig2/
    native/scripts/
```

让 Codex 重新加载 Skills 后，在聊天中调用：

> 用 cell_cns_figure 处理这张图，输出 PPT。

或者：

> 用 cell_cns_figure 的2号处理以下科研文字，输出 Adobe Illustrator 文件。

图片上限为10 MiB；2号文字上限为500000字符。PDF 需先按指定页转成 PNG/JPG。首次使用需要有效的小描 API Key及足够额度，凭据通过标准输入写入当前 Windows 用户的 DPAPI 密文文件。

## 运行与恢复

提交后，独立 Python 进程等待结果，收到 SVG 后校验任务、费用和文件哈希，再通知原 Codex 聊天继续转换。每个订单使用持久请求ID，响应丢失时恢复同一订单。1号已有的19额度历史订单继续按原回执处理，新订单为20额度。

首次提交会注册当前 Windows 用户的恢复任务：`CellCnsFig1_Client_Recovery` 或 `CellCnsFig2_Client_Recovery`。恢复任务仅在登录时直接启动一次无窗口 `pythonw.exe`，常驻监控器每30秒在同一进程内检查已登记任务；不再每分钟启动 PowerShell。已在运行的接收进程不会重复启动。电脑重启后需重新登录并打开 Codex；它不会创建新的付费订单。`stop` 只停止本地接收，不代表远端取消或退款。

仅检查桌面连接（不提交、不扣费）：

```powershell
python -X utf8 '<Skill目录>/backends/fig1/scripts/client.py' probe
```

具体命令见 [1号客户端](../backends/fig1/references/client.md)、[2号客户端](../backends/fig2/references/client.md)。不要在任务进行中移动 Skill 或删除任务目录；恢复必须保留原目录、原请求ID、原客户和原聊天。

## 输出与适用边界

输出为原生可编辑 PPTX 或 AI，并保留接收到的 SVG。转换完全使用本 Skill 的内置代码，不调用图片识别或其他收费入口。

已修正嵌套 SVG 的视口位置和尺寸计算。尚未支持的 SVG 效果会报告预处理需求，不能静默丢弃；交付前仍需查看实际软件预览。旧版结果重新转换时使用新输出目录，不覆盖已有结果、不重新扣费。

本轮验证包含两条客户端流程、独立内置转换器的真实 PPTX 输出和 Illustrator 几何缓存；未运行真实 Illustrator 桌面导出或付费线上任务。

## 开发测试

在仓库根目录分别运行两个测试套件（使用独立进程，避免同名模块冲突）：

```powershell
python -X utf8 -m unittest discover -s backends/fig1/tests -v
python -X utf8 -m unittest discover -s backends/fig2/tests -v
python -X utf8 -m unittest discover -s native/tests -v
```

## 数据与许可

客户输入会通过 HTTPS 发送给 [小描服务](https://xiaomiao-ai.com/)。服务需要客户账户和额度，开源客户端不包含免费服务额度、服务端代码或第三方软件许可。本仓库不包含客户凭据、真实任务或生成素材。请将任务目录放在仓库外。

客户端代码按 [MIT License](../LICENSE) 发布；依赖项目和第三方应用遵循各自许可证。

已用小描配置工具保存 API Key 时会自动读取共享配置，无需重复提供。新订单先检测本地配置，再验证账户与余额；旧订单始终沿用原凭据。
