# Tobii Raw TSV Extractor

**中文说明**：本代码脚本用于从 Tobii Pro Lab 中导出的原始全量 TSV 文件中提取全量原始数据，并重建可用于后续统计分析的眼动指标表。换言之，本代码脚本用于从 Tobii Pro Lab 中导出的原始全量 TSV 文件中提取全量原始数据；也即，本代码脚本用于从 Tobii Pro Lab 中导出的原始全量 TSV 文件中提取全量原始数据。

一个可复用的 Tobii Pro Lab 原始 TSV 指标提取工具，用于从 `Data export.tsv` 这类原始导出文件中重建 participant × image、participant × image × AOI 和 AOI 语义类别层面的 CSV 指标表。

本工具的设计目标是尽量不绑定某一个具体实验项目：

- 自动从 `ImageStimulusStart` / `ImageStimulusEnd` 事件切分图片呈现区间。
- 自动识别 `AOI hit [...]` 和 `AOI size [...]` 列，不要求预先写死 AOI 名称或数量。
- 自动识别常见被试分组列，如 `specialist`、`Group`、`Participant group`；如果没有分组列，则统一写为 `participant_group=ALL`。
- 复用 Tobii Pro Lab 原始 TSV 中已有的 `Eye movement type` 和 `Eye movement type index`，不重新实现 fixation detection。
- 支持可选 baseline media code，用于计算瞳孔相对变化指标。

> 说明：不同 Tobii Pro Lab 项目的图片数量、AOI 划分、AOI 命名和分组字段可能不同。本工具会尽量自动适应。若分组列未被识别，可通过 `--group-column` 手动指定。

## 安装依赖

建议使用已有 conda 环境或新建环境：

```powershell
conda create -n tobii_tsv python=3.11 pandas numpy pyinstaller
conda activate tobii_tsv
```

或在现有 Python 环境中安装：

```powershell
pip install -r requirements.txt
```

## 命令行使用

```powershell
python tobii_tsv_extractor.py `
  --raw-tsv "H:\your_project\Data export.tsv" `
  --output-dir ".\outputs" `
  --baseline-media-code "instruction" `
  --exclude-media-codes "instruction"
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--raw-tsv` | Tobii Pro Lab 原始 TSV 文件路径。 |
| `--output-dir` | 输出目录。若不填，默认在 TSV 同级目录下生成 `tobii_tsv_extracted_metrics`。 |
| `--group-column` | 被试分组列名。可留空自动识别。 |
| `--baseline-media-code` | 用作瞳孔 baseline 的媒体代码，例如指导页 `zhidaoyu`。留空则不计算 baseline-based pupil expansion。 |
| `--exclude-media-codes` | 不进入正式 trial 统计的媒体代码，多个值用英文逗号分隔，例如 `zhidaoyu,practice`。 |
| `--chunksize` | 分块读取行数，默认 `100000`，大文件可保持默认。 |
| `--gui` | 打开简易 Tkinter 图形界面。 |

## 图形界面使用

不带参数运行即可打开界面：

```powershell
python tobii_tsv_extractor.py
```

或者：

```powershell
python tobii_tsv_extractor.py --gui
```

界面中的 `Baseline media code` 应填写 Tobii 事件/媒体中的 media code，不是图片序号。例如：

- 指导页媒体为 `zhidaoyu.png` 时，填写 `zhidaoyu`。
- 图片媒体为 `1-02.png` 时，填写 `1-02`，不是填写 `1`。
- 如果不需要 baseline-based pupil expansion，可留空。

## 输出文件

| 文件 | 粒度 | 内容 |
|---|---|---|
| `interval_inventory.csv` | participant × media interval | 由 `ImageStimulusStart` / `ImageStimulusEnd` 重建的图片呈现区间。 |
| `aoi_metadata.csv` | media × AOI | 自动识别出的 AOI hit/size 列、AOI 名称、自动语义类别和 AOI size。 |
| `sample_trial_inventory.csv` | participant × image | 样本数、有效样本数、pupil 样本数、媒体尺寸等基础质控信息。 |
| `trial_metrics.csv` | participant × image | 图片层面的 fixation、saccade、scanpath、pupil、语义 AOI 类别指标。 |
| `aoi_metrics_long.csv` | participant × image × AOI | 原始 AOI 层面的 fixation、visit、glance、pupil 指标。 |
| `aoi_class_metrics_wide.csv` | participant × image | 按自动语义类别聚合后的 AOI 指标。 |
| `extraction_report.md` | report | 本次提取的输入、输出和数据规模摘要。 |

## 可提取指标概览

### trial_metrics.csv

去掉被试、记录、分组、图片和媒体等识别字段后，trial 层指标主要包括：

| 指标组 | 代表字段 | 含义 |
|---|---|---|
| 区间与媒体 | `interval_start_ms`, `interval_end_ms`, `interval_duration_ms`, `presented_media_width`, `presented_media_height` | 图片呈现区间和媒体尺寸。 |
| 数据质量 | `sample_count`, `valid_sample_count`, `valid_sample_ratio`, `eyes_not_found_count`, `eyes_not_found_ratio` | 原始采样数量、有效比例和眼睛未找到比例。 |
| 瞳孔绝对值 | `pupil_mean`, `pupil_median`, `pupil_count` | 图片呈现期间的平均/中位瞳孔直径和样本数。 |
| 瞳孔归一化 | `pupil_within_participant_z`, `pupil_participant_median_corrected_pct` | 被试内 z-score 或被试中位数校正指标。 |
| baseline 瞳孔变化 | `baseline_pupil_mean`, `baseline_pupil_median`, `pupil_expansion_rate_vs_baseline_pct`, `pupil_median_expansion_rate_vs_baseline_pct` | 相对指定 baseline media 的瞳孔变化率。 |
| 注视总量 | `fixation_count`, `total_fixation_duration_ms`, `mean_fixation_duration_ms`, `min_fixation_duration_ms`, `max_fixation_duration_ms` | 图片层面的注视次数和注视时长。 |
| 首次注视 | `time_to_first_fixation_ms`, `first_fixation_duration_ms` | 首次注视潜伏期和首次注视时长。 |
| 扫视 | `saccade_count`, `total_saccade_duration_ms`, `mean_saccade_duration_ms` | 扫视次数和扫视时长。 |
| 视线路径 | `scanpath_length_px`, `normalized_scanpath_length`, `mean_fixation_to_fixation_distance_px` | 注视点路径长度和标准化路径长度。 |
| AOI 转换 | `aoi_transition_count`, `aoi_transition_entropy` | 语义类别之间的转换次数和转换熵。 |
| 语义 AOI 类别 | `class_<semantic>_fixation_duration_ms`, `class_<semantic>_fixation_count`, `class_<semantic>_visit_count`, `class_<semantic>_duration_share_of_trial` | 每类 AOI 的注视、访问和注意占比。语义类别由 AOI 名称自动粗分，不同项目可自行调整。 |
| 注意集中度 | `semantic_attention_entropy`, `semantic_attention_hhi`, `semantic_attention_gini` | 注意分布的熵、HHI 和 Gini。 |
| 语义类别瞳孔 | `class_<semantic>_average_pupil_diameter`, `class_<semantic>_pupil_expansion_rate_vs_baseline_pct` | 每类 AOI 的平均瞳孔和 baseline 相对变化。 |

### aoi_metrics_long.csv

去掉 participant、recording、participant_group、picture_id、media_code、AOI 名称等识别字段后，AOI 层约 25 个指标包括：

| 字段 | 中文释义 |
|---|---|
| `aoi_size` | AOI 面积或 Tobii 导出的 AOI size。 |
| `duration_of_interval_ms` | 图片呈现区间总时长。 |
| `total_duration_of_fixations_ms` | AOI 内注视总时长。 |
| `average_duration_of_fixations_ms` | AOI 内平均注视时长。 |
| `minimum_duration_of_fixations_ms` | AOI 内最短注视时长。 |
| `maximum_duration_of_fixations_ms` | AOI 内最长注视时长。 |
| `number_of_fixations` | AOI 内注视次数。 |
| `time_to_first_fixation_ms` | 从图片开始到首次注视该 AOI 的时间。 |
| `duration_of_first_fixation_ms` | 对该 AOI 的首次注视时长。 |
| `last_aoi_viewed` | 最后一次 fixation 是否落在该 AOI。 |
| `aoi_at_interval_end` | 图片结束时是否仍在该 AOI 上。 |
| `total_duration_of_visit_ms` | AOI visit 总时长。 |
| `average_duration_of_visit_ms` | AOI 平均 visit 时长。 |
| `number_of_visits` | AOI visit 次数。 |
| `revisit_count` | AOI 重访次数。 |
| `total_duration_of_glances_ms` | AOI glance 总时长。当前实现与 visit run 的时长口径一致。 |
| `number_of_glances` | AOI glance 次数。当前实现与 visit run 的次数口径一致。 |
| `aoi_hit_sample_count` | 原始采样中 AOI hit 的样本数。 |
| `aoi_pupil_sum` | AOI hit 样本的瞳孔直径总和。 |
| `aoi_pupil_count` | AOI hit 样本中有效瞳孔样本数。 |
| `aoi_average_pupil_diameter` | AOI 内平均瞳孔直径。 |
| `baseline_period_media_code` | 用作 baseline 的媒体代码。 |
| `baseline_pupil_mean` | 对应被试 baseline 期间平均瞳孔直径。 |
| `baseline_pupil_count` | baseline 期间有效瞳孔样本数。 |
| `aoi_pupil_expansion_rate_vs_baseline_pct` | AOI 平均瞳孔相对 baseline 的增长率。 |

## 示例文件

`examples/` 目录包含一组去标识化示例输出：

- `examples/trial_metrics.csv`
- `examples/aoi_metrics_long.csv`

示例文件用于展示输出格式和指标字段。被试编号、媒体代码和 AOI 原始名称已泛化，不应作为原始研究数据复用。

## 打包为 EXE

Windows 下可运行：

```powershell
.\build_exe.ps1
```

输出位置：

```text
dist\TobiiTSVExtractor.exe
```

如果 PyInstaller 在包含多个 Qt 绑定的 conda 环境中报错，`build_exe.ps1` 已排除不需要的 Qt/Jupyter/绘图模块。

## 方法边界

- 本工具不重新检测 fixation/saccade，而是复用 Tobii Pro Lab 原始 TSV 中已有的 eye-movement 分类结果。
- AOI fixation/visit/glance 指标由 fixation 行和 AOI hit 列重建。Tobii Pro Lab 软件内部对边界 fixation、visit span 的处理可能是闭源实现，因此个别时长字段可能不能逐毫秒复刻软件预计算导出。
- baseline-based pupil expansion 需要有明确的 baseline media code。若没有实验设计上的 baseline，建议使用绝对瞳孔值或被试内 z-score，而不要把所有正式图片均值称为 baseline。

---

# English Version

**English note**: This code script is designed to extract full raw data from the original full TSV file exported by Tobii Pro Lab, and to reconstruct eye-tracking metric tables for downstream analysis.

Tobii Raw TSV Extractor is a reusable tool for reconstructing eye-tracking metrics from Tobii Pro Lab raw `Data export.tsv` files. It generates CSV tables at participant × image, participant × image × AOI, and semantic AOI-class levels.

The tool is designed to avoid hardcoding project-specific settings:

- It detects image presentation intervals from `ImageStimulusStart` / `ImageStimulusEnd` events.
- It detects AOI definitions from `AOI hit [...]` and `AOI size [...]` columns.
- It auto-detects common participant group columns such as `specialist`, `Group`, and `Participant group`. If no group column is available, it writes `participant_group=ALL`.
- It reuses Tobii Pro Lab eye-movement classifications from the raw TSV, especially `Eye movement type` and `Eye movement type index`; it does not rerun fixation detection.
- It supports an optional baseline media code for pupil-response metrics.

Different Tobii Pro Lab projects can have different image counts, AOI names, AOI counts, and participant grouping variables. The extractor adapts automatically where possible. If the group column is not detected, use `--group-column` to specify it manually.

## Installation

Create a conda environment:

```powershell
conda create -n tobii_tsv python=3.11 pandas numpy pyinstaller
conda activate tobii_tsv
```

Or install dependencies in an existing Python environment:

```powershell
pip install -r requirements.txt
```

## Command-Line Usage

```powershell
python tobii_tsv_extractor.py `
  --raw-tsv "H:\your_project\Data export.tsv" `
  --output-dir ".\outputs" `
  --baseline-media-code "instruction" `
  --exclude-media-codes "instruction"
```

Common parameters:

| Parameter | Description |
|---|---|
| `--raw-tsv` | Path to the Tobii Pro Lab raw TSV export. |
| `--output-dir` | Output directory. If omitted, `tobii_tsv_extracted_metrics` is created beside the TSV file. |
| `--group-column` | Participant-group column name. Leave blank for auto-detection. |
| `--baseline-media-code` | Media code used as the pupil baseline, such as `zhidaoyu` or `instruction`. Leave blank to skip baseline-based pupil expansion metrics. |
| `--exclude-media-codes` | Media codes excluded from formal trial statistics, separated by commas, such as `zhidaoyu,practice`. |
| `--chunksize` | Number of rows per chunk when reading large TSV files. Default: `100000`. |
| `--gui` | Launch the simple Tkinter graphical interface. |

## GUI Usage

Run without arguments:

```powershell
python tobii_tsv_extractor.py
```

Or explicitly request the GUI:

```powershell
python tobii_tsv_extractor.py --gui
```

`Baseline media code` should be the Tobii media/event code, not a picture index. For example:

- If the instruction page is `zhidaoyu.png`, enter `zhidaoyu`.
- If a formal image is `1-02.png`, enter `1-02`, not `1`.
- Leave it blank if no baseline-based pupil expansion metric is needed.

## Output Files

| File | Grain | Contents |
|---|---|---|
| `interval_inventory.csv` | participant × media interval | Image intervals reconstructed from `ImageStimulusStart` / `ImageStimulusEnd`. |
| `aoi_metadata.csv` | media × AOI | Detected AOI hit/size columns, AOI names, automatic semantic class labels, and AOI size. |
| `sample_trial_inventory.csv` | participant × image | Sample counts, valid samples, pupil sample counts, and media size information. |
| `trial_metrics.csv` | participant × image | Image-level fixation, saccade, scanpath, pupil, and semantic AOI-class metrics. |
| `aoi_metrics_long.csv` | participant × image × AOI | Raw AOI-level fixation, visit, glance, and pupil metrics. |
| `aoi_class_metrics_wide.csv` | participant × image | AOI metrics aggregated by automatic semantic class. |
| `extraction_report.md` | report | Summary of input, output, and extraction scale. |

## Extractable Metrics

### `trial_metrics.csv`

After excluding identifier fields such as participant, recording, group, picture, and media code, trial-level metrics include:

| Metric Group | Example Fields | Meaning |
|---|---|---|
| Interval and media | `interval_start_ms`, `interval_end_ms`, `interval_duration_ms`, `presented_media_width`, `presented_media_height` | Image display interval and media dimensions. |
| Data quality | `sample_count`, `valid_sample_count`, `valid_sample_ratio`, `eyes_not_found_count`, `eyes_not_found_ratio` | Raw sample counts, valid-sample ratio, and eyes-not-found ratio. |
| Absolute pupil size | `pupil_mean`, `pupil_median`, `pupil_count` | Mean/median pupil diameter and pupil sample count during image presentation. |
| Pupil normalization | `pupil_within_participant_z`, `pupil_participant_median_corrected_pct` | Within-participant z-score and participant-median corrected pupil response. |
| Baseline pupil response | `baseline_pupil_mean`, `baseline_pupil_median`, `pupil_expansion_rate_vs_baseline_pct`, `pupil_median_expansion_rate_vs_baseline_pct` | Pupil response relative to the specified baseline media. |
| Fixation volume | `fixation_count`, `total_fixation_duration_ms`, `mean_fixation_duration_ms`, `min_fixation_duration_ms`, `max_fixation_duration_ms` | Image-level fixation count and duration. |
| First fixation | `time_to_first_fixation_ms`, `first_fixation_duration_ms` | Latency and duration of the first fixation. |
| Saccade | `saccade_count`, `total_saccade_duration_ms`, `mean_saccade_duration_ms` | Saccade count and duration. |
| Scanpath | `scanpath_length_px`, `normalized_scanpath_length`, `mean_fixation_to_fixation_distance_px` | Fixation-path length and normalized scanpath length. |
| AOI transitions | `aoi_transition_count`, `aoi_transition_entropy` | Number and entropy of transitions between semantic AOI classes. |
| Semantic AOI classes | `class_<semantic>_fixation_duration_ms`, `class_<semantic>_fixation_count`, `class_<semantic>_visit_count`, `class_<semantic>_duration_share_of_trial` | Fixation, visit, and attention-share metrics by semantic AOI class. Class labels are automatically inferred from AOI names and can be adjusted for each project. |
| Attention concentration | `semantic_attention_entropy`, `semantic_attention_hhi`, `semantic_attention_gini` | Entropy, HHI, and Gini of semantic attention distribution. |
| Semantic-class pupil metrics | `class_<semantic>_average_pupil_diameter`, `class_<semantic>_pupil_expansion_rate_vs_baseline_pct` | Mean pupil diameter and baseline-relative pupil response by semantic AOI class. |

### `aoi_metrics_long.csv`

After excluding identifier fields such as participant, recording, participant group, picture ID, media code, AOI name, and AOI semantic label, the AOI-level table contains approximately 25 reusable metrics:

| Field | Meaning |
|---|---|
| `aoi_size` | AOI size exported by Tobii Pro Lab. |
| `duration_of_interval_ms` | Total image interval duration. |
| `total_duration_of_fixations_ms` | Total fixation duration inside the AOI. |
| `average_duration_of_fixations_ms` | Mean fixation duration inside the AOI. |
| `minimum_duration_of_fixations_ms` | Minimum fixation duration inside the AOI. |
| `maximum_duration_of_fixations_ms` | Maximum fixation duration inside the AOI. |
| `number_of_fixations` | Number of fixations inside the AOI. |
| `time_to_first_fixation_ms` | Latency from image onset to first fixation on the AOI. |
| `duration_of_first_fixation_ms` | Duration of the first fixation on the AOI. |
| `last_aoi_viewed` | Whether the final fixation fell on the AOI. |
| `aoi_at_interval_end` | Whether the interval ended on this AOI. |
| `total_duration_of_visit_ms` | Total duration of AOI visits. |
| `average_duration_of_visit_ms` | Mean duration of AOI visits. |
| `number_of_visits` | Number of AOI visits. |
| `revisit_count` | Number of revisits after the first visit. |
| `total_duration_of_glances_ms` | Total glance duration. In the current implementation this follows the same run-based definition as visits. |
| `number_of_glances` | Number of glances. In the current implementation this follows the same run-based definition as visits. |
| `aoi_hit_sample_count` | Number of raw samples hitting the AOI. |
| `aoi_pupil_sum` | Sum of valid pupil samples inside the AOI. |
| `aoi_pupil_count` | Count of valid pupil samples inside the AOI. |
| `aoi_average_pupil_diameter` | Mean pupil diameter inside the AOI. |
| `baseline_period_media_code` | Media code used as the pupil baseline period. |
| `baseline_pupil_mean` | Participant-specific mean pupil diameter during baseline. |
| `baseline_pupil_count` | Number of valid baseline pupil samples. |
| `aoi_pupil_expansion_rate_vs_baseline_pct` | AOI pupil change relative to baseline, in percent. |

## Example Files

The `examples/` directory contains anonymized example outputs:

- `examples/trial_metrics.csv`
- `examples/aoi_metrics_long.csv`

The example files are provided to demonstrate the output format and metric fields. Participant IDs, media codes, and raw AOI names have been generalized and should not be treated as raw research data.

## Build an EXE

On Windows, run:

```powershell
.\build_exe.ps1
```

The executable is written to:

```text
dist\TobiiTSVExtractor.exe
```

If PyInstaller fails in a conda environment with multiple Qt bindings, `build_exe.ps1` already excludes unnecessary Qt/Jupyter/plotting modules.

## Method Boundaries

- The tool does not redetect fixations or saccades; it reuses eye-movement classifications already exported in the Tobii Pro Lab raw TSV.
- AOI fixation/visit/glance metrics are reconstructed from fixation rows and AOI hit columns. Tobii Pro Lab's internal handling of boundary fixations and visit spans may be closed-source, so some duration fields may not match precomputed software exports millisecond by millisecond.
- Baseline-based pupil expansion requires a clear baseline media code. If the experiment has no designed baseline period, prefer absolute pupil diameter or within-participant z-scores instead of calling the mean of all formal images a baseline.
