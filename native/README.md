# 内置原生 SVG 转换

从 cell_su7 的已批准 SVG 分支完整复制的运行代码，源文件哈希记录在 PROVENANCE.json。源 Skill 不属于运行时依赖。这里只包含 SVG 原生绘制，不包含图片识别、去水印、凭据或付费接口。

本地修订：共享 svg_viewport.py 处理嵌套视口，PPT 与 AI 缓存增加 nested-v1 版本；Windows AI 复用当前 Python 并隐藏辅助控制台。后续维护直接修改本目录并执行 native/tests；不得改回同级 Skill 跳转。

限制：未展开的局部裁剪、资源引用、CSS、渐变、滤镜等由校验器报告；复杂文字实际边界仍需软件预览。真实 Illustrator 导出尚未在本轮运行。
