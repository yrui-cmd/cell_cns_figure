# 内置 SVG 原生转换

两条分支统一使用本 Skill 的 `native/scripts`，完整内置自 cell_su7 的 SVG→PPT/AI 代码、缓存解析、JSX、PowerShell 和验收脚本。运行时不读取、不调用同级 cell_su7，不下载临时转换器；不走图片识别或额外收费入口。

## 输入与坐标

保持服务端 `result.svg` 字节和 SHA-256 不变，直接解析原 SVG。嵌套 SVG 的 x/y、width/height、viewBox、preserveAspectRatio 与父级 transform 必须共同计算；支持百分比视口、多层嵌套和非零 viewBox 原点。禁止忽略子视口后把素材堆到原点。PPT 与 AI 使用同一套视口规则。

保留支持范围内的路径、叠放顺序、复合路径、颜色和可编辑文字。局部裁剪、蒙版、滤镜、渐变、marker、虚线、CSS 类、use 等尚未展开的效果若不被转换器支持，应保留原 SVG 并报告需要预处理，不能静默删除后当作正常交付。复杂文本和实际文字边界仍须预览验收；不能声称任意 SVG 均可无损转换。

## PowerPoint

内置 run_from_svg.py 执行 SVG 校验、几何缓存、冗余路径处理和原生 OOXML 写入。输出自由形状及文本框，禁止把整张 SVG 或栅格图塞入 PPT。Windows 中用副本展示路径，再从实际 PowerPoint 导出预览；原生输出文件保留。

## Illustrator

内置 run_illustrator.py 通过同目录 COM/JSX 批量写入原生路径，保存 AI 并导出 PNG。使用已打开的目标文档，保留无关内容；软件或目标文档未打开时保留进度，继续同一任务。Python 解释器沿用启动客户端的解释器。

## 恢复与交付

转换模式为 bundled-native-v2。旧 direct-path-v1 输出不能直接复用，重新 convert 时分配新的 shibielujingN 目录，旧输出保留。只在新模式、原 SVG、输出文件哈希一致时恢复复用。complete 必须通过新模式校验、实际预览和原生对象审计；尤其核对素材位置、比例、箭头完整性、叠放和文字遮挡。

失败只修复已有 SVG 的本地转换，不重新付费提交。原订单、凭据、聊天、费用与后台接收逻辑保持不变。只有本地实际文件验证完成，才可报告交付完成。
