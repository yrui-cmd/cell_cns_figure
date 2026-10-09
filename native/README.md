# 内置原生 SVG 转换

从 cell_su7 的已批准 SVG 分支完整复制的运行代码，源文件哈希记录在 PROVENANCE.json。源 Skill 不属于运行时依赖。这里只包含 SVG 原生绘制，不包含图片识别、去水印、凭据或付费接口。

本地修订：共享 svg_viewport.py 处理嵌套视口，PPT 与 AI 缓存增加 nested-v2 版本；Windows AI 复用当前 Python 并隐藏辅助控制台。后续维护直接修改本目录并执行 native/tests；不得改回同级 Skill 跳转。

两个分支的 direct_svg.py 生成映射副本，渐变、裁剪等效果不拦截绘制；run_direct_ppt.py 跳过路径剔除，保留原位置和尺寸，不改原 SVG。复杂文字实际边界仍需软件预览。真实 Illustrator 导出尚未在本轮运行。

2026-10-09：按真实 FUNDC1 PPT/SVG 修复子视口可见范围、百分比几何、零宽描边、空路径及开放轮廓填色；视口交集使用 skia-pathops，PPT 与 AI 共用。
