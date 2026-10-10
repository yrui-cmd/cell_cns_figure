# SVG交付与Adobe Illustrator导入

`export` 校验原任务、费用回执和SVG哈希，再在原任务的deliverables目录生成SVG副本。原result.svg永不覆盖。默认Times New Roman，用户指定字体优先，仅在副本中调整文字字体；图形路径、位置、大小、变换、层级、渐变、裁剪与箭头保留。

先读取原目录job.json；原聊天执行acknowledge确认nonce后，运行 `client.py export --job-dir <原目录>`。实际查看SVG，确认位置、比例、文字和箭头正常，再用 `complete --visual-checked` 完成。结构校验不能替代实际预览。

默认直接交付返回的svg文件链接，无需安装Office或Illustrator。只有用户选择Adobe导入（application=ai）时才执行 `client.py import-illustrator --job-dir <原目录>`。Windows通过Illustrator的文档打开功能直接打开SVG，不逐路径重绘、不要求预建空白文档、不向已有文档粘贴内容。重复导入同一已打开文件时复用该文档。

Illustrator未安装、启动失败或打开失败时，SVG仍可交付供手动打开；如实说明未完成自动导入，保留原任务和SVG，恢复后重试原目录。不会创建新收费订单，也不把SVG改名为AI冒充原生AI文件。

完成前重新校验原件和交付副本的哈希；已选Adobe导入时还需匹配对应SVG的成功导入回执。旧application=ppt订单改为直接交付SVG；旧convert入口作为export别名保留，没有PPTX转换、预览或播放操作。
