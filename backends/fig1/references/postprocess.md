# 识别路径：SVG、PPT与Adobe显示检查

先读原任务job.json，在原聊天acknowledge后执行 `client.py export --job-dir <原目录>`。保留不可变的result.svg；交付副本默认Times New Roman，用户指定字体优先。校验哈希不能代替看图。

## 输出选择

- 识别路径后的展示方式按用户选择；未指定时按入口询问一次。SVG无需Office或Illustrator。
- 用户要求可逐个编辑形状的PPT：新任务 `submit --application ppt`；已有任务直接 `client.py export-ppt --job-dir <原目录>`。返回PPTX和SVG，不创建新订单或再次收费。
- 用户选择Adobe：`client.py import-illustrator --job-dir <原目录>`，打开独立文档并查看返回的实际Illustrator预览；不修改已有文档。marker按原坐标展开，曲线主体、裁剪和渐变保留。另存真正的PDF兼容AI文件，重新打开该AI导出预览；文字保留可编辑文本，不转曲。不把SVG改后缀冒充AI。

## PPT识别路径

实现随本Skill打包，不临时调用cell_ppt、cell_lct或其他外部Skill。PPT依赖安装本Skill根目录 `requirements-ppt.txt`；几何转换使用Cairo、Skia PathOps和DrawingML，实际预览需要Windows桌面PowerPoint。Cairo运行库必须可加载；失败时报告真实依赖问题并保留SVG。接收器仍由pythonw无窗口持续运行，转换不改变后台监控。

1. 以同一份交付SVG为坐标基准，解析width/height单位、非零viewBox原点、preserveAspectRatio、嵌套SVG、CSS与多层变换。统一像素到EMU的比例；路径局部坐标与形状边框一起计算，不重复缩放、不用每个对象单独拉伸凑版面。
2. 裁剪是曲线几何求交；描边、圆角、虚线与箭头转成真实轮廓；复合路径保留孔洞和绕向。渐变转成足够密集的矢量色带，不能删裁剪、丢箭头、把渐变替换为首个颜色或放入整图位图。
3. **文字必须使用原生文本框，保留Unicode字符，可直接打字修改；不转曲、不嵌图。** 使用渲染器解析后的基线、字体、字号、变换和字符位置，而不是只读text节点的x/y。常规文字按一行/同样式连续段组成文本框；多行分别固定基线，独立坐标或旋转字符按必要段拆分，不能重叠。保留文字在原图中的绘制顺序。关闭自动换行、自动缩放和默认内边距，按原字号摆放。

   在本机PowerPoint的独立校准文件中实测每种字体/粗斜体的首行基线偏移，将测得的修正应用到文本框；随后重新导出最终PPT实际预览，不能用猜测的统一顶部补偿代替。缺字时按实际字形选择系统后备字体，无可用字形则报告缺字体，不能交付方框字。默认字体仍为Times New Roman，用户要求优先。
4. 保存原生DrawingML路径PPTX，检查不存在整图SVG或栅格图片冒充原生路径。坐标、路径和原生文本框数量、字体基线实测记录、源文件及输出哈希写入回执。几何与格式校验只代表文件结构合格。
5. 在PowerPoint打开独立只读副本，导出实际PNG并关闭该副本，不关闭用户已有文档。生成SVG/PPT对照页；需要比较Adobe时加 `--illustrator`，同一SVG另开独立Illustrator文档并导出真实预览。未安装或未检查的软件必须显示未检查，不能声称三方一致。

## 显示验收与恢复

查看 `export-ppt` 返回的preview和comparison_page，按相同比例检查整体布局、元素大小、细胞内部结构、裁剪边界、透明叠加、细线、曲线箭头、复合孔洞和多行文字；放大关键区域。报告同时记录原生路径数量、坐标及差异图，平均像素差只用于定位，不自动判定一致。

SVG渲染器有不同支持范围：复杂滤镜/蒙版、特殊文字排版需要针对文件兼容处理；上下标命名偏移采用em近似、成组透明度近似的数量会在native.json记录，应重点审查叠加区域。常规渐变与嵌套裁剪不能作为直接放弃PPT的理由。文字的斜切、非均匀缩放或局部裁剪需要明确的原生文字兼容处理，不能静默改成轮廓。某项确实失败则保留SVG和转换进度，说明实际差异、继续修复；不得删效果后当作一致完成，也不重新收费。

确认实际预览后执行 `client.py complete --job-dir <原目录> --visual-checked`。选PPT时必须有与当前SVG对应的PPT、实际PowerPoint预览及对照回执；文件改变、检查未完成或转换失败不能标记交付完成。选Adobe时还需当前SVG对应的AI保存并重开回执，AI、实际预览与审查文件哈希均须匹配；旧版仅打开SVG的回执需重新执行import-illustrator。返回AI及SVG。返回所选PPTX及SVG；需要时附预览/对照页。

历史application=ppt且没有原生PPT交付标记的任务保留原SVG交付行为，用户要求转换后在原目录执行export-ppt。旧v1转曲PPT重新export-ppt升级为v2原生文字；旧回执不能冒充新文字版完成。默认SVG和未选择PPT的历史回调不自动启动桌面转换。

离线诊断已有文件可使用同目录 `display_check.py --svg <源SVG> --pptx <已有PPTX> --output <新的检查目录> [--illustrator]`；省略pptx仅生成嵌入SVG的显示基线，不属于原生路径交付。该诊断不提交任何收费任务。

## Illustrator坐标与文字

使用本Skill内置 `illustrator_native.py`，依赖本Skill根目录 `requirements-adobe.txt` 和本机Illustrator。将交付SVG独立导入，不重画路径、不按单个对象边界重新缩放；沿用SVG的viewBox、嵌套变换、图层顺序、裁剪和渐变。marker按原坐标展开；填充与描边被Adobe拆成同位置双份文字时，只将同一组内相邻、几何/字体/内容完全相同且不透明的填充与描边文本对合回一个原生文本，保留描边效果。

保存新AI后关闭并重新打开本次生成的文件，再导出实际PNG。记录画板、文字位置/边框/字号/字体及路径数量；按实际渲染实例比较文字字符，检查画板比例。文字位置仍需在同尺度SVG/Adobe预览中核对，不用字符计数或比例检查代替视觉验收。默认Times New Roman，用户要求优先；不得为消除显示差异静默把文字转曲。

新输出使用独立目录，不覆盖用户已有AI或修改已有文档。完成返回AI、SVG；预览或对照页按需附上。离线已有SVG可直接执行 `illustrator_native.py --svg <SVG> --output <新目录>`，不提交付费任务。
