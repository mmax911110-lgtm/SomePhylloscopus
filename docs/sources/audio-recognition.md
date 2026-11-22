# 离线柳莺叫声识别

在首页「找到鸟了！」中可选择照片、录音或两者。录音支持 MP3、WAV、FLAC、OGG、Opus 和 AIFF。点击「开始鉴定！」后，录音会在本机 CPU 上分析。选中一条录音可以查看候选鸟种、模型分数和出现位置。模型证据偏弱时会显示无法确认。录音结果在本次队列内查看，现有档案继续保存照片识别记录。

## 模型与开源参考

| 来源 | 本项目的用法 |
| --- | --- |
| [BirdNET+ V3.0.1 官方发布](https://zenodo.org/records/24362980)及[推理示例](https://github.com/birdnet-team/birdnet-V3.0-dev/blob/main/birdnet_v3.py) | 使用原版 Global 12K FP16 pruned ONNX 权重。音频以 32 kHz 单声道和 3 秒窗口输入，窗口相隔 1.5 秒。保留全部 11,725 类的全局分数供拒识使用，再从图鉴的 50 种柳莺中给出候选。 |
| [BirdNET-Analyzer](https://github.com/birdnet-team/BirdNET-Analyzer)与 [Google Perch](https://github.com/google-research/perch) | 对比模型标签和部署体积。BirdNET 2.4 覆盖图鉴中的 48 种。Perch V2 与 BirdNET+ V3.0.1 都覆盖 50 种。V3.0.1 提供了约 69 MiB 的剪枝 ONNX。 |
| [SoundFile](https://python-soundfile.readthedocs.io/)、[python-soxr](https://github.com/dofuuz/python-soxr) | 按块解码成 `float32`，折叠声道，重采样流横跨块边界。内存占用随窗口和批次大小变化，无需读入整条长录音后才开始推理。 |
| [ONNX Runtime 线程配置](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) | 启动时延迟加载模型。复用 CPU 会话，关闭线程空转，仅请求分数输出。预分配窗口数组，在同批次复用。 |

预训练权重使用 Apache-2.0。项目局部标签表保留官方 CSV 的行序，只保留各类学名。柳莺中英文名来自本地图鉴。随模型保留 `MODEL_LICENSE.txt` 和 `ACCEPTABLE_USE.txt`，音频依赖保留 wheel 内的许可和第三方声明。SoundFile 的 Windows wheel 内含 [libsndfile](https://github.com/libsndfile/libsndfile/tree/1.2.2)。python-soxr 的 wheel 内含 [libsoxr](https://github.com/chirlu/soxr) 和 PFFFT，精确版本及许可见 `vendor/audio` 里的随包说明。

## 本地资源位置

- `app/audio_recognition.py` 是识别入口。照片和录音走各自的模型。
- `models/audio/` 保存官方 ONNX、紧凑学名索引及许可。
- `vendor/audio/` 保存 Windows x64、Python 3.11 音频依赖。可复用便携版已带的 NumPy 和 packaging。

源码目录的模型和运行库与现有照片权重一样独立打包。当前 Windows 本地安装中已准备上述资源。单次录音中可以出现多种声音，候选分数反映最有力的时间窗。本功能给出录音级候选，尚未对每声叫声做单独定位或计数。

## 测试来源

使用带来源和逐条许可的 [iNaturalist 录音](https://www.inaturalist.org/pages/api+reference)及 [ESC-50](https://github.com/karolpiczak/ESC-50) 的环境声。验证和测试录音者分开，测试覆盖极北、冕、褐、淡眉、黄眉、黄腰及暗绿柳莺。模型预训练来源与收集截止日期见官方发布，公开录音的社区标签可能有误。小规模评测的结果应与样本数一起解读。
