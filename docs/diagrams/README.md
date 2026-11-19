# 识别流程图

| 语言 | SVG | PNG |
| --- | --- | --- |
| 中文 | [SVG](recognition-pipeline.svg) | [PNG](recognition-pipeline.png) |
| English | [SVG](recognition-pipeline.en.svg) | [PNG](recognition-pipeline.en.png) |
| 日本語 | [SVG](recognition-pipeline.ja.svg) | [PNG](recognition-pipeline.ja.png) |

项目 README 内嵌 1680 × 1340 的 PNG，点击可打开对应的 SVG。上半是五步主线，下半把第 4 步的柳莺专项复核展开：门控条件、58 类专项分类头、相似种近邻复核（淡脚柳莺组 k=3、极北柳莺组 k=5）、专项头 / Tip-Adapter / GDA 三路物种概率融合。这些数字和名词按 `app/backend.py`、`app/specialist.py`、`app/species_fusion.py` 及 `models/cryptic_groups_20261115/manifest.json` 核对过，以后改模型记得同步改图。

```markdown
![一张观鸟照片，怎样认出每一只鸟](docs/diagrams/recognition-pipeline.svg)
```

SVG 里的文字都是普通 `<text>`，可以直接改。字体（思源宋体 / Noto Serif CJK SC、Lora Italic，均为 SIL OFL）只嵌入了图中用到的字形；如果新加了图里没有的汉字，这几个字会退回系统字体显示。

示例照片：warbler_09.jpg，Frank Vassen，[CC BY 2.0](https://creativecommons.org/licenses/by/2.0/)，[原图](https://commons.wikimedia.org/wiki/File:Yellow-browed_warbler_(Phylloscopus_inornatus),_Parc_du_Slot,_Woluw%C3%A9-St.-Lambert,_Brussels_(34053989676).jpg)。图中经过裁切并手动加了鸟框。鉴定单里的候选排序和分数条只是示意，不是真实推理输出。
