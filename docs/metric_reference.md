# Metric Reference

This document summarizes the output metric schema. The exact semantic AOI class columns depend on the AOI names used in each Tobii Pro Lab project.

## Output Tables

- `trial_metrics.csv`: one row per participant-image trial.
- `aoi_metrics_long.csv`: one row per participant-image-AOI.
- `aoi_class_metrics_wide.csv`: one row per participant-image with AOI metrics aggregated by automatic semantic class.

## AOI-Level Metrics

After excluding identifier columns such as participant, recording, image, media code, and AOI name, the long AOI table contains approximately 25 reusable metric fields:

| Field | Meaning |
|---|---|
| `aoi_size` | AOI size exported by Tobii Pro Lab. |
| `duration_of_interval_ms` | Total image interval duration. |
| `total_duration_of_fixations_ms` | Total fixation duration inside the AOI. |
| `average_duration_of_fixations_ms` | Mean fixation duration inside the AOI. |
| `minimum_duration_of_fixations_ms` | Minimum fixation duration inside the AOI. |
| `maximum_duration_of_fixations_ms` | Maximum fixation duration inside the AOI. |
| `number_of_fixations` | Number of fixations inside the AOI. |
| `time_to_first_fixation_ms` | Latency from image onset to first AOI fixation. |
| `duration_of_first_fixation_ms` | Duration of the first AOI fixation. |
| `last_aoi_viewed` | Whether the final fixation was inside the AOI. |
| `aoi_at_interval_end` | Whether the interval ended on this AOI. |
| `total_duration_of_visit_ms` | Total duration of AOI visit runs. |
| `average_duration_of_visit_ms` | Mean duration of AOI visit runs. |
| `number_of_visits` | Number of AOI visits. |
| `revisit_count` | Number of revisits after the first visit. |
| `total_duration_of_glances_ms` | Total glance duration. |
| `number_of_glances` | Number of glances. |
| `aoi_hit_sample_count` | Sample-level AOI hit count. |
| `aoi_pupil_sum` | Sum of valid pupil samples inside the AOI. |
| `aoi_pupil_count` | Count of valid pupil samples inside the AOI. |
| `aoi_average_pupil_diameter` | Mean pupil diameter inside the AOI. |
| `baseline_period_media_code` | Media code used as the pupil baseline period. |
| `baseline_pupil_mean` | Participant-specific mean pupil diameter during baseline. |
| `baseline_pupil_count` | Number of valid baseline pupil samples. |
| `aoi_pupil_expansion_rate_vs_baseline_pct` | AOI pupil change relative to baseline, in percent. |

## Full Column Inventory

See:

- `metric_columns_inventory.csv`
- `metric_group_summary.csv`
