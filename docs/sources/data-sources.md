# 数据、模型与素材来源

本页按用途列出从训练、验证、图鉴和交付记录中核实的来源。上游预训练数据的收录范围见模型卡。照片或录音能否再分发，以该条目的授权为准。

## 鸟类检测和背景复核

| 来源 | 实际用途 | 原始出处 |
| --- | --- | --- |
| Caltech-UCSD Birds-200-2011（CUB-200-2011） | 既有鸟框训练数据，另沿用留出的图片做检测回归和裁图对照。 | [Caltech 数据集](https://www.vision.caltech.edu/datasets/cub_200_2011/) |
| COCO 2017 | 取鸟框及无鸟背景，训练或诊断误报。历史网络负样本记录包括重划分的 COCO val2017。 | [COCO 下载页](https://cocodataset.org/#download) |
| FBD-SV-2024 | 监控视频帧中的小型飞鸟与复杂背景，用于检测；同一视频的帧需要分组处理。 | [作者仓库](https://github.com/Ziwei89/FBD-SV-2024_github) |
| IBERBIRDS | 使用中远距离飞鸟和天空画面，辅助检测训练与评估。 | [Zenodo DOI](https://doi.org/10.5281/zenodo.15090760) |
| Open Images | 上游检测研发的独立来源对照，包含小目标、遮挡和人工筛查的无鸟样本。 | [Open Images 下载页](https://storage.googleapis.com/openimages/web/download_v7.html) |

较早的联网负样本清单有 1,700 条记录，来自过滤鸟类别后重新划分的 COCO 2017 val2017。清单中同时保留 COCO 下载地址、Flickr 原图地址与逐图许可索引。

## 鸟种分类、柳莺专项与复核评估

| 来源 | 实际用途 | 原始出处 |
| --- | --- | --- |
| iNaturalist 研究级观察及其图片记录 | 用于中国鸟种分类研究、柳莺专项训练以及相似种实验的训练、验证和测试。公开许可逐图记录。划分和重合核查尽量按观察记录、作者与图片像素进行。 | [iNaturalist API](https://api.inaturalist.org/v1/docs/) · [摄影作品许可说明](https://help.inaturalist.org/en/support/solutions/articles/151000169918) |
| GBIF 发生记录与原始观察平台 | 用于稀缺柳莺来源核查和相似种独立对照。留出清单可追到 Observation.org 和 Artsobservasjoner 等发布者。查询时检查野外照片、作者与媒体授权。 | [GBIF 发生记录接口](https://api.gbif.org/v1/occurrence/search) · [Observation.org](https://observation.org/) · [Artsobservasjoner](https://www.artsobservasjoner.no/) |
| 可见部位与易混淆种参考 | 可见部位研究的标注说明引用了上海观鸟资料，图像来源仍按每条观察记录列出。此实验与正式版的全局特征专项路径分别记录。 | [Shanghai Birding](https://www.shanghaibirding.com/) |

社区研究级标签来自观察平台。历史评估保留失败样本与许可筛选记录，仍可能存在误标、跨平台转载或上游预训练重合。数据集的用途和版本不能由一项识别准确率概括。

## 上游模型与研究实现

- BioCLIP 2 和 BioCLIP 2.5 的预训练数据及权重来自 Imageomics，TreeOfLife 数据范围按各型号说明。项目使用相应的预训练视觉编码器。[BioCLIP 2 项目与训练说明](https://github.com/Imageomics/bioclip-2) · [BioCLIP 2 模型卡](https://huggingface.co/imageomics/bioclip-2) · [BioCLIP 2.5 模型卡](https://huggingface.co/imageomics/bioclip-2.5-vith14)
- Tip 缓存检索参考 Tip-Adapter 的官方实现。其论文所用的通用分类基准属于上游研究。[Tip-Adapter](https://github.com/gaopengcuhk/Tip-Adapter)
- Ultralytics、OpenCLIP、timm 和相关运行库的随包版本及许可记录见第三方声明。媒体和图鉴另按各自来源署名。[第三方组件说明](third-party-notices.md)

## 应用内的图鉴、录音和图像

| 材料 | 记录 |
| --- | --- |
| 首页与鸟种卡的内置鸟照 | Wikimedia Commons。逐图记录摄影者、原图、许可。[轮播照片署名](photos-credits.md) |
| 补充自然照片和历史图版 | iNaturalist 逐照片记录及公共领域历史图版，分别记录作者、原观察或原书及许可。[补充参考图署名](reference-credits.md) |
| 离线录音及鸟种文字 | 本地资料按条目标注录音平台、作者、许可和原始页面。鸟种文字参考香港观鸟会、物种文献和中英文百科。[逐项资料与录音署名](catalog-and-audio.md) |
| 辨识折页 | 《两岸三地50种柳莺类辨识》简体折页用于比对体征。出版与著作权信息应参照原件。公开源码的预览图使用有明确许可的摄影照片。 |
| 字体与图形 | 首页标题采用霞鹜文楷，装饰柳莺和枝叶由本项目代码绘制。字体适用原许可证。[霞鹜文楷](https://github.com/lxgw/LxgwWenKai) |
| 本仓库的软件截图 | 用当前正式界面和临时空档案截取。具体示例和横幅均有摄影署名。[截图署名](screenshots.md) |

## 权利反馈

请在本仓库开启 Issue 联系维护者。可使用标题「资料署名更正」或「权利反馈」，提供相关文件位置、原始来源、您与该材料的关系，以及希望补充、更正或移除的内容。维护者核实后处理。涉及私人信息时，请在公开 Issue 中先简述问题。
