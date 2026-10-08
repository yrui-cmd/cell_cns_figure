# 返回SVG直接映射

沿用cell_cns_fig1的直接路径映射流程，本客户端默认direct-path-v1，不再让局部裁剪、蒙版、滤镜、渐变或奇偶填充兼容检查阻塞路径输出，也不运行隐藏对象剔除。只使用同级cell_su7的本地几何解析和原生文件写入，不调用图片识别、去字、去水印或付费接口。

## 映射规则

保留服务端result.svg及其SHA-256。direct_svg.py另写任务内的映射副本，原路径d、坐标变换、绘制顺序、复合子路径不重绘；局部use引用展开到对应位置。defs里的裁剪模板等资源不作为可见图形。

本模式只映射几何。裁剪、蒙版、滤镜和标记效果不参与；渐变取第一个色标，虚线用原路径实线表示；曲线文字保留内容并放到曲线锚点及切线方向。PPT使用原生复合填充，AI保留源填充规则。direct-mapping.json记录实际处理数量，不能把这种直接映射称为完整SVG效果复现。

## PPT

run_direct_ppt.py复用cell_su7的prepare_geometry_cache.py和run_cell_ppt_ooxml.py。中间不调用cull_hidden_geometry.py，不删除重叠路径。输出原生自由形状及文本框，不把SVG塞成单张图片。

默认沿用run_ppt_path_playback.ps1，在隔离副本中按顺序显现完整原生对象，再导出真实PowerPoint预览。用户只要文件时使用convert --file-only。只检查实际生成、可打开及原生对象；不反复做科学/效果一致性审核。

## Illustrator

映射副本交给cell_su7/scripts/run_illustrator.py，复用COM/JSX原生批量路径写入，保存AI并导出PNG。沿用已打开目标文档，保留无关内容；Illustrator未打开时保留原SVG和映射副本，打开目标文档后恢复同一任务。

## 恢复

native-output.json绑定原SVG、映射副本、模式及原生文件哈希。旧模式结果不当作直接映射结果复用；新输出另分配目录，保留旧结果。崩溃或中断后继续同一任务，不再付费提交。
