# Third-party notices / 第三方声明

本包由多种不同许可的组件组成，不能将整个包统一标注为 MIT 或“无条件商用”。各组件原始许可优先；完整许可和模型卡位于 `licenses`，依赖的原始 `*.dist-info` 和源码也随 `runtime/packages` 保留。`licenses/manifest.json` 记录所复制许可文件的校验值。

## 模型与推理代码

| 组件 | 随包版本 / 用途 | 许可与上游 |
| --- | --- | --- |
| Ultralytics | 8.4.92，第四版 YOLO 检测及相关工具 | AGPL-3.0；[官方许可说明](https://www.ultralytics.com/license)、[源码](https://github.com/ultralytics/ultralytics) |
| ultralytics-thop | 2.0.20，依赖组件 | AGPL-3.0；完整 LICENSE 已保留 |
| BioCLIP 2 | ViT-L/14 图像编码器 | MIT；[模型卡](https://huggingface.co/imageomics/bioclip-2)、[项目](https://github.com/Imageomics/bioclip-2) |
| BioCLIP 2.5 | ViT-H/14 图像编码器，revision `6e3d04e3d6522012c88181085c5ae666e14c45cd` | MIT；[模型卡](https://huggingface.co/imageomics/bioclip-2.5-vith14) |
| OpenCLIP | open_clip_torch 3.3.0 | MIT；[项目](https://github.com/mlfoundations/open_clip) |
| timm | 1.0.30 | Apache-2.0；[项目](https://github.com/huggingface/pytorch-image-models) |
| PyTorch / torchvision | 2.11.0+cu128 / 0.26.0+cu128 | BSD 系列及随附第三方条款；[PyTorch LICENSE](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| Safetensors | 0.8.0 | Apache-2.0；完整许可已保留 |

Ultralytics 的官方发行采用 AGPL-3.0，并提供另一种企业许可路径。使用、修改或再次分发适用 AGPL 的代码/模型时，需要保留许可、版权和相应源码，并履行适用条款；通过网络提供修改版本也有对应源码义务。AGPL 并非一律禁止商业使用，但闭源商业集成不能仅凭 BioCLIP 的 MIT 许可判断整个应用可闭源。官方依据：[Ultralytics AGPL 说明](https://www.ultralytics.com/legal/agpl-3-0-software-license)。

本包附带应用 `.py` 源码、推理所需配置、权重和 Ultralytics Python 源码；训练数据不随包分发。以上是组件来源与再分发说明，不替代对应许可证的完整要求。原有图片训练集、照片、物种名录等上游内容仍保留其各自权利。

## 运行环境

Python 3.11.9 由 Python Software Foundation 等贡献者提供，完整许可见 `licenses/Python-3.11.9-LICENSE.txt`。Tcl/Tk 用于本地图形界面，其原始许可保留于 `runtime/tcl` 和 `licenses/Tk-8.6-license.terms`。NumPy、SciPy、scikit-learn、Pillow、OpenCV、Matplotlib、PyYAML、Requests、Polars 等依赖的许可和第三方声明均按已安装发行包原文保留；完整实际版本见 `configs/runtime_versions.json`。

PyTorch Windows CUDA 发行包包含 NVIDIA CUDA/cuDNN 等用户态组件，其许可并不因外层 PyTorch 的 BSD 许可而被替换。请保留 `runtime/packages/cuda/torch-*.dist-info` 中的 `LICENSE`、`NOTICE` 以及 `licenses/distributions/torch` 中全部声明。NVIDIA 显卡驱动未随包分发、也不会由本程序自动安装。

Microsoft Visual C++ app-local DLL 来自本机已安装的 Visual Studio Community 2022 正式 `VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT`，文件版本 `14.44.35211.0`；拷贝前核验 Microsoft 有效数字签名，未修改 DLL。Microsoft 的可再分发清单允许符合其 Visual Studio 许可条款的用户随程序分发指定运行库，排除 debug_nonredist。完整 Community 许可保存在 `licenses/Microsoft-VS2022-Community-License-EN.docx`。依据：[官方 REDIST 清单](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)、[运行库部署说明](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)、[许可来源](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)。

## 示例照片

随包两张示例均由源站标为 CC0。照片来源、署名信息、许可链接和未改动说明见 `examples/README.md` 与 `examples/attribution.json`。模型许可与照片许可彼此独立。
