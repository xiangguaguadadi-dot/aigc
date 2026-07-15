# 图片投放目录

把一张单主体图片拖到这个目录，然后双击仓库根目录的：

```text
run_image_to_3d.command
```

脚本会选择本目录中最后修改的受支持图片，依次完成去背景、TripoSR 三维生成、Blender 标准化和验证，并自动用 Blender 打开生成的三维模型。

支持的图片格式：

```text
png jpg jpeg webp bmp tif tiff
```

图片应只有一个完整、无遮挡的主体。不要把 API key、私人照片或许可证不明确的素材提交到 Git。
