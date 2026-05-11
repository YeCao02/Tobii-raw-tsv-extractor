# -*- coding: utf-8 -*-
"""Generic Tobii Pro Lab raw-TSV metric extractor.

The extractor is intentionally project-agnostic:
- AOI names/counts are detected from ``AOI hit [...]`` columns.
- participant groups are auto-detected or can be supplied by column name.
- image/media count is inferred from ImageStimulusStart/ImageStimulusEnd events.

It reuses Tobii Pro Lab's exported eye-movement labels and indices; it does not
re-run fixation detection.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


DEFAULT_OUTPUT_FOLDER_NAME = "tobii_tsv_extracted_metrics"
TRIAL_KEY = ["participant", "recording", "participant_group", "picture_id", "media_code"]
FIX_KEY = TRIAL_KEY + ["eye_movement_type_index"]
KNOWN_GROUP_COLUMNS = ["specialist", "Participant group", "participant group", "Group", "group", "Subject group"]
CLASS_PRIORITY = [
    "human_activities",
    "traditional_building",
    "commercial_building",
    "landmark",
    "bridge",
    "sign",
    "birds",
    "dragon_boat",
    "river",
    "riparian_vegetation",
    "upland_vegetation",
    "other",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Tobii Pro Lab raw-TSV metrics.")
    parser.add_argument("--raw-tsv", type=Path, default=None, help="Path to Tobii Pro Lab raw TSV export.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory. Defaults to a sibling folder beside the TSV.")
    parser.add_argument("--chunksize", type=int, default=100_000)
    parser.add_argument("--group-column", type=str, default=None, help="Optional participant-group column. Auto-detected when omitted.")
    parser.add_argument("--baseline-media-code", type=str, default="", help="Optional baseline media code for pupil expansion, e.g. zhidaoyu.")
    parser.add_argument("--exclude-media-codes", type=str, default="", help="Comma-separated media codes to exclude from formal trials.")
    parser.add_argument("--gui", action="store_true", help="Open a simple Tkinter interface.")
    return parser.parse_args()


def media_code_from_name(value: object) -> Optional[str]:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"\s+\(\d+\)$", "", text)
    return re.sub(r"\.(jpg|jpeg|png|bmp|gif|tif|tiff)$", "", text, flags=re.IGNORECASE)


def picture_id_from_code(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    match = re.match(r"^(\d+)(?:-|_|\.|\s|$)", str(value).strip())
    return int(match.group(1)) if match else None


def parse_aoi_column(col: str, prefix: str = "AOI hit") -> Tuple[str, str]:
    pattern = re.escape(prefix) + r" \[(.+?) - (.+)\]$"
    match = re.match(pattern, col)
    if not match:
        raise ValueError(f"Cannot parse AOI column: {col}")
    return media_code_from_name(match.group(1)) or match.group(1), match.group(2)


def normalize_aoi_name(name: str) -> str:
    text = str(name).strip().lower().replace("_", " ")
    return re.sub(r"\s+", " ", text)


def semantic_class(name: str) -> str:
    text = normalize_aoi_name(name)
    if "human" in text or "people" in text or "person" in text:
        return "human_activities"
    if "traditional" in text or "historic" in text or "heritage" in text:
        return "traditional_building"
    if "commercial" in text or text == "buildings":
        return "commercial_building"
    if "riparian" in text or "waterfront vegetation" in text:
        return "riparian_vegetation"
    if "upland" in text or "vegetation" in text or "tree" in text or "plant" in text:
        return "upland_vegetation"
    if "river" in text or "water" in text:
        return "river"
    if "bird" in text:
        return "birds"
    if "dragon" in text:
        return "dragon_boat"
    if "landmark" in text:
        return "landmark"
    if "sign" in text:
        return "sign"
    if "bridge" in text:
        return "bridge"
    if "building" in text:
        return "commercial_building"
    return "other"


def first_non_null(series: pd.Series) -> object:
    non_null = series.dropna()
    return non_null.iloc[0] if len(non_null) else np.nan


def safe_mean(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(arr.mean()) if arr.size else np.nan


def safe_median(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.median(arr)) if arr.size else np.nan


def shannon_entropy(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    total = arr.sum()
    if total <= 0:
        return 0.0
    p = arr / total
    return float(-(p * np.log2(p)).sum())


def gini(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr >= 0)]
    if arr.size == 0 or np.all(arr == 0):
        return 0.0
    arr = np.sort(arr)
    n = arr.size
    return float((2 * np.arange(1, n + 1) - n - 1).dot(arr) / (n * arr.sum()))


def hhi(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    total = arr.sum()
    if total <= 0:
        return 0.0
    p = arr / total
    return float(np.square(p).sum())


def numeric_frame(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    return df.loc[:, list(cols)].apply(pd.to_numeric, errors="coerce")


def read_header(path: Path) -> List[str]:
    return pd.read_csv(path, sep="\t", nrows=0).columns.tolist()


def detect_group_column(columns: List[str], requested: Optional[str]) -> Optional[str]:
    if requested:
        if requested not in columns:
            raise ValueError(f"Group column not found in TSV: {requested}")
        return requested
    for candidate in KNOWN_GROUP_COLUMNS:
        if candidate in columns:
            return candidate
    return None


def resolve_picture_ids(media_codes: Sequence[str]) -> Dict[str, int]:
    explicit = {m: picture_id_from_code(m) for m in media_codes}
    next_id = 1
    mapping: Dict[str, int] = {}
    for media in media_codes:
        pid = explicit.get(media)
        if pid is None:
            while next_id in explicit.values():
                next_id += 1
            pid = next_id
            next_id += 1
        mapping[media] = int(pid)
    return mapping


def build_aoi_metadata(raw_tsv: Path, columns: List[str], out_dir: Path) -> pd.DataFrame:
    aoi_hit_cols = [c for c in columns if c.startswith("AOI hit [")]
    aoi_size_cols = [c for c in columns if c.startswith("AOI size [")]
    size_map: Dict[Tuple[str, str], float] = {}
    if aoi_size_cols:
        size_row = pd.read_csv(raw_tsv, sep="\t", usecols=aoi_size_cols, nrows=1)
        for col in aoi_size_cols:
            media_code, aoi_name = parse_aoi_column(col, prefix="AOI size")
            size_map[(media_code, aoi_name)] = pd.to_numeric(size_row[col], errors="coerce").iloc[0]

    rows = []
    for col in aoi_hit_cols:
        media_code, aoi_name = parse_aoi_column(col, prefix="AOI hit")
        rows.append(
            {
                "aoi_hit_column": col,
                "media_code": media_code,
                "picture_id": picture_id_from_code(media_code),
                "aoi_name": aoi_name,
                "aoi_name_normalized": normalize_aoi_name(aoi_name),
                "semantic_class_auto": semantic_class(aoi_name),
                "aoi_size": size_map.get((media_code, aoi_name), np.nan),
            }
        )
    meta = pd.DataFrame(rows).sort_values(["media_code", "aoi_name"]).reset_index(drop=True)
    meta.to_csv(out_dir / "aoi_metadata.csv", index=False, encoding="utf-8-sig")
    return meta


def build_intervals(
    raw_tsv: Path,
    out_dir: Path,
    chunksize: int,
    group_column: Optional[str],
    excluded_media: set[str],
) -> pd.DataFrame:
    cols = ["Participant name", "Recording name", "Recording timestamp", "Event", "Event value"]
    if group_column:
        cols.append(group_column)
    frames = []
    row_offset = 0
    for chunk in pd.read_csv(raw_tsv, sep="\t", usecols=cols, chunksize=chunksize, low_memory=False):
        chunk["_row_number"] = np.arange(row_offset, row_offset + len(chunk))
        row_offset += len(chunk)
        events = chunk[chunk["Event"].isin(["ImageStimulusStart", "ImageStimulusEnd"])].copy()
        if not events.empty:
            frames.append(events)
    if not frames:
        raise RuntimeError("No ImageStimulusStart/ImageStimulusEnd events found.")

    ev = pd.concat(frames, ignore_index=True)
    ev["recording_timestamp_ms"] = pd.to_numeric(ev["Recording timestamp"], errors="coerce")
    ev = ev.rename(columns={"Participant name": "participant", "Recording name": "recording", "Event value": "event_value"})
    if group_column:
        ev["participant_group"] = ev[group_column].fillna("Unknown").astype(str)
    else:
        ev["participant_group"] = "ALL"

    rows = []
    for (participant, recording), group in ev.sort_values(["recording_timestamp_ms", "_row_number"], kind="mergesort").groupby(["participant", "recording"], dropna=False):
        open_start = None
        for rec in group.to_dict("records"):
            if rec["Event"] == "ImageStimulusStart":
                open_start = rec
            elif rec["Event"] == "ImageStimulusEnd" and open_start is not None:
                media_code = media_code_from_name(open_start.get("event_value"))
                rows.append(
                    {
                        "participant": participant,
                        "recording": recording,
                        "participant_group": open_start.get("participant_group", "ALL"),
                        "event_value_start": str(open_start.get("event_value", "")).strip(),
                        "event_value_end": str(rec.get("event_value", "")).strip(),
                        "media_code": media_code,
                        "interval_start_ms": open_start["recording_timestamp_ms"],
                        "interval_end_ms": rec["recording_timestamp_ms"],
                        "interval_duration_ms": rec["recording_timestamp_ms"] - open_start["recording_timestamp_ms"],
                        "excluded_from_formal": bool(media_code in excluded_media),
                    }
                )
                open_start = None
    intervals = pd.DataFrame(rows)
    media_order = intervals["media_code"].dropna().drop_duplicates().tolist()
    pid_map = resolve_picture_ids(media_order)
    intervals["picture_id"] = intervals["media_code"].map(pid_map)
    intervals = intervals.sort_values(["participant", "recording", "interval_start_ms"]).reset_index(drop=True)
    intervals.to_csv(out_dir / "interval_inventory.csv", index=False, encoding="utf-8-sig")
    return intervals


def append_pupil_values(
    store: Dict[Tuple, List[float]],
    participant_store: Dict[str, List[float]],
    formal: pd.DataFrame,
) -> None:
    pupil = pd.to_numeric(formal["Pupil diameter filtered"], errors="coerce")
    valid = pupil[np.isfinite(pupil)]
    if valid.empty:
        return
    tmp = formal.loc[valid.index, TRIAL_KEY].copy()
    tmp["_pupil"] = valid.values
    for key, group in tmp.groupby(TRIAL_KEY, dropna=False):
        vals = group["_pupil"].to_numpy(dtype=float)
        store[key].extend(vals.tolist())
        participant_store[str(key[0])].extend(vals.tolist())


def append_baseline_pupil_values(store: Dict[str, List[float]], chunk: pd.DataFrame, baseline_media_code: str) -> None:
    if not baseline_media_code:
        return
    baseline = chunk[chunk["media_code"].eq(baseline_media_code)].copy()
    if baseline.empty:
        return
    pupil = pd.to_numeric(baseline["Pupil diameter filtered"], errors="coerce")
    valid = pupil[np.isfinite(pupil) & baseline["valid_sample"]]
    if valid.empty:
        return
    tmp = baseline.loc[valid.index, ["participant"]].copy()
    tmp["_pupil"] = valid.values
    for participant, group in tmp.groupby("participant", dropna=False):
        store[str(participant)].extend(group["_pupil"].to_numpy(dtype=float).tolist())


def aggregate_chunks(
    raw_tsv: Path,
    chunksize: int,
    aoi_meta: pd.DataFrame,
    out_dir: Path,
    group_column: Optional[str],
    baseline_media_code: str,
    included_media_codes: set[str],
    media_picture_ids: Dict[str, int],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[Tuple, List[float]], Dict[str, List[float]], Dict[str, List[float]]]:
    aoi_cols = aoi_meta["aoi_hit_column"].tolist()
    aoi_cols_by_media = {media: group["aoi_hit_column"].tolist() for media, group in aoi_meta.groupby("media_code", sort=False)}
    base_cols = [
        "Participant name",
        "Recording name",
        "Recording timestamp",
        "Presented Media name",
        "Presented Media width",
        "Presented Media height",
        "Original Media width",
        "Original Media height",
        "Eye movement type",
        "Eye movement event duration",
        "Eye movement type index",
        "Fixation point X",
        "Fixation point Y",
        "Pupil diameter filtered",
        "Validity left",
        "Validity right",
    ]
    if group_column:
        base_cols.insert(1, group_column)
    usecols = [c for c in base_cols + aoi_cols if c]

    sample_frames: List[pd.DataFrame] = []
    fixation_frames: List[pd.DataFrame] = []
    saccade_frames: List[pd.DataFrame] = []
    aoi_sample_frames: List[pd.DataFrame] = []
    pupil_by_trial: Dict[Tuple, List[float]] = defaultdict(list)
    pupil_by_participant: Dict[str, List[float]] = defaultdict(list)
    pupil_by_baseline: Dict[str, List[float]] = defaultdict(list)

    for chunk_i, chunk in enumerate(pd.read_csv(raw_tsv, sep="\t", usecols=usecols, chunksize=chunksize, low_memory=False), start=1):
        chunk = chunk.rename(
            columns={
                "Participant name": "participant",
                "Recording name": "recording",
                "Presented Media name": "presented_media_name",
                "Recording timestamp": "recording_timestamp_ms",
                "Eye movement type index": "eye_movement_type_index",
            }
        )
        chunk["participant_group"] = chunk[group_column].fillna("Unknown").astype(str) if group_column else "ALL"
        chunk["media_code"] = chunk["presented_media_name"].map(media_code_from_name)
        chunk["picture_id"] = chunk["media_code"].map(media_picture_ids)
        chunk["Pupil diameter filtered"] = pd.to_numeric(chunk["Pupil diameter filtered"], errors="coerce")
        chunk["valid_sample"] = chunk["Validity left"].eq("Valid") | chunk["Validity right"].eq("Valid")
        append_baseline_pupil_values(pupil_by_baseline, chunk, baseline_media_code)

        formal = chunk[chunk["media_code"].isin(included_media_codes)].copy()
        if formal.empty:
            continue
        formal["picture_id"] = formal["picture_id"].astype(int)
        for col in ["recording_timestamp_ms", "Eye movement event duration", "eye_movement_type_index", "Fixation point X", "Fixation point Y"]:
            formal[col] = pd.to_numeric(formal[col], errors="coerce")
        formal["eyes_not_found"] = formal["Eye movement type"].eq("EyesNotFound")

        sample = formal.copy()
        sample["_pupil_sum"] = sample["Pupil diameter filtered"].where(np.isfinite(sample["Pupil diameter filtered"]), 0.0)
        sample["_pupil_count"] = np.isfinite(sample["Pupil diameter filtered"]).astype(int)
        sample["_valid_count"] = sample["valid_sample"].astype(int)
        sample["_eyes_not_found_count"] = sample["eyes_not_found"].astype(int)
        sample["_sample_count"] = 1
        sample_frames.append(
            sample.groupby(TRIAL_KEY, dropna=False)
            .agg(
                sample_count=("_sample_count", "sum"),
                valid_sample_count=("_valid_count", "sum"),
                eyes_not_found_count=("_eyes_not_found_count", "sum"),
                pupil_sum=("_pupil_sum", "sum"),
                pupil_count=("_pupil_count", "sum"),
                sample_start_ms=("recording_timestamp_ms", "min"),
                sample_end_ms=("recording_timestamp_ms", "max"),
                presented_media_width=("Presented Media width", first_non_null),
                presented_media_height=("Presented Media height", first_non_null),
                original_media_width=("Original Media width", first_non_null),
                original_media_height=("Original Media height", first_non_null),
            )
            .reset_index()
        )
        append_pupil_values(pupil_by_trial, pupil_by_participant, formal)

        fixation = formal[formal["Eye movement type"].eq("Fixation") & formal["eye_movement_type_index"].notna()].copy()
        if not fixation.empty:
            fixation["_x_sum"] = fixation["Fixation point X"].where(np.isfinite(fixation["Fixation point X"]), 0.0)
            fixation["_y_sum"] = fixation["Fixation point Y"].where(np.isfinite(fixation["Fixation point Y"]), 0.0)
            fixation["_xy_count"] = (np.isfinite(fixation["Fixation point X"]) & np.isfinite(fixation["Fixation point Y"])).astype(int)
            base_fix = (
                fixation.groupby(FIX_KEY, dropna=False)
                .agg(
                    fixation_duration_ms=("Eye movement event duration", "max"),
                    fixation_start_ms=("recording_timestamp_ms", "min"),
                    fixation_end_ms=("recording_timestamp_ms", "max"),
                    fixation_x_sum=("_x_sum", "sum"),
                    fixation_y_sum=("_y_sum", "sum"),
                    fixation_xy_count=("_xy_count", "sum"),
                    fixation_sample_rows=("Eye movement type", "size"),
                )
            )
            for media_code in sorted(fixation["media_code"].dropna().unique()):
                cols = aoi_cols_by_media.get(media_code, [])
                if not cols:
                    continue
                sub = fixation[fixation["media_code"].eq(media_code)]
                hits = numeric_frame(sub, cols).fillna(0)
                hits[FIX_KEY] = sub[FIX_KEY].values
                base_fix = base_fix.join(hits.groupby(FIX_KEY, dropna=False)[cols].max(), how="left")
            fixation_frames.append(base_fix.reset_index())

        saccade = formal[formal["Eye movement type"].eq("Saccade") & formal["eye_movement_type_index"].notna()].copy()
        if not saccade.empty:
            saccade_frames.append(
                saccade.groupby(FIX_KEY, dropna=False)
                .agg(
                    saccade_duration_ms=("Eye movement event duration", "max"),
                    saccade_start_ms=("recording_timestamp_ms", "min"),
                    saccade_end_ms=("recording_timestamp_ms", "max"),
                    saccade_sample_rows=("Eye movement type", "size"),
                )
                .reset_index()
            )

        for media_code in sorted(formal["media_code"].dropna().unique()):
            cols = aoi_cols_by_media.get(media_code, [])
            if not cols:
                continue
            sub = formal[formal["media_code"].eq(media_code)].copy()
            hits = numeric_frame(sub, cols).fillna(0).gt(0)
            pupil = pd.to_numeric(sub["Pupil diameter filtered"], errors="coerce")
            for col in cols:
                mask = hits[col].to_numpy()
                if not mask.any():
                    continue
                tmp = sub.loc[mask, TRIAL_KEY].copy()
                tmp["aoi_hit_column"] = col
                tmp["_aoi_sample_count"] = 1
                tmp["_aoi_pupil_sum"] = pupil.loc[tmp.index].where(np.isfinite(pupil.loc[tmp.index]), 0.0).values
                tmp["_aoi_pupil_count"] = np.isfinite(pupil.loc[tmp.index]).astype(int).values
                aoi_sample_frames.append(
                    tmp.groupby(TRIAL_KEY + ["aoi_hit_column"], dropna=False)
                    .agg(
                        aoi_hit_sample_count=("_aoi_sample_count", "sum"),
                        aoi_pupil_sum=("_aoi_pupil_sum", "sum"),
                        aoi_pupil_count=("_aoi_pupil_count", "sum"),
                    )
                    .reset_index()
                )
        if chunk_i % 5 == 0:
            print(f"Processed chunk {chunk_i}", flush=True)

    sample_stats = pd.concat(sample_frames, ignore_index=True)
    sample_stats = sample_stats.groupby(TRIAL_KEY, dropna=False).agg(
        sample_count=("sample_count", "sum"),
        valid_sample_count=("valid_sample_count", "sum"),
        eyes_not_found_count=("eyes_not_found_count", "sum"),
        pupil_sum=("pupil_sum", "sum"),
        pupil_count=("pupil_count", "sum"),
        sample_start_ms=("sample_start_ms", "min"),
        sample_end_ms=("sample_end_ms", "max"),
        presented_media_width=("presented_media_width", first_non_null),
        presented_media_height=("presented_media_height", first_non_null),
        original_media_width=("original_media_width", first_non_null),
        original_media_height=("original_media_height", first_non_null),
    ).reset_index()

    fixation_stats = pd.concat(fixation_frames, ignore_index=True) if fixation_frames else pd.DataFrame(columns=FIX_KEY)
    if not fixation_stats.empty:
        aoi_existing = [c for c in aoi_cols if c in fixation_stats.columns]
        agg_map = {
            "fixation_duration_ms": "max",
            "fixation_start_ms": "min",
            "fixation_end_ms": "max",
            "fixation_x_sum": "sum",
            "fixation_y_sum": "sum",
            "fixation_xy_count": "sum",
            "fixation_sample_rows": "sum",
        }
        agg_map.update({c: "max" for c in aoi_existing})
        fixation_stats = fixation_stats.groupby(FIX_KEY, dropna=False).agg(agg_map).reset_index()
        for col in aoi_cols:
            if col not in fixation_stats.columns:
                fixation_stats[col] = 0
        fixation_stats[aoi_cols] = fixation_stats[aoi_cols].fillna(0)
        fixation_stats["fixation_x"] = fixation_stats["fixation_x_sum"] / fixation_stats["fixation_xy_count"].replace(0, np.nan)
        fixation_stats["fixation_y"] = fixation_stats["fixation_y_sum"] / fixation_stats["fixation_xy_count"].replace(0, np.nan)

    saccade_stats = pd.concat(saccade_frames, ignore_index=True) if saccade_frames else pd.DataFrame(columns=FIX_KEY)
    if not saccade_stats.empty:
        saccade_stats = saccade_stats.groupby(FIX_KEY, dropna=False).agg(
            saccade_duration_ms=("saccade_duration_ms", "max"),
            saccade_start_ms=("saccade_start_ms", "min"),
            saccade_end_ms=("saccade_end_ms", "max"),
            saccade_sample_rows=("saccade_sample_rows", "sum"),
        ).reset_index()

    aoi_sample_stats = pd.concat(aoi_sample_frames, ignore_index=True) if aoi_sample_frames else pd.DataFrame(columns=TRIAL_KEY + ["aoi_hit_column"])
    if not aoi_sample_stats.empty:
        aoi_sample_stats = aoi_sample_stats.groupby(TRIAL_KEY + ["aoi_hit_column"], dropna=False).agg(
            aoi_hit_sample_count=("aoi_hit_sample_count", "sum"),
            aoi_pupil_sum=("aoi_pupil_sum", "sum"),
            aoi_pupil_count=("aoi_pupil_count", "sum"),
        ).reset_index()
        aoi_sample_stats["aoi_average_pupil_diameter"] = aoi_sample_stats["aoi_pupil_sum"] / aoi_sample_stats["aoi_pupil_count"].replace(0, np.nan)

    sample_stats.to_csv(out_dir / "sample_trial_inventory.csv", index=False, encoding="utf-8-sig")
    return sample_stats, fixation_stats, saccade_stats, aoi_sample_stats, pupil_by_trial, pupil_by_participant, pupil_by_baseline


def choose_fixation_class(row: pd.Series, aoi_cols_by_media: Dict[str, List[str]], class_by_col: Dict[str, str]) -> str:
    cols = aoi_cols_by_media.get(row["media_code"], [])
    hit_classes = {class_by_col[c] for c in cols if c in row.index and pd.to_numeric(row[c], errors="coerce") > 0}
    if not hit_classes:
        return "ungrouped"
    for cls in CLASS_PRIORITY:
        if cls in hit_classes:
            return cls
    return sorted(hit_classes)[0]


def build_trial_metrics(
    sample_stats: pd.DataFrame,
    fixation_stats: pd.DataFrame,
    saccade_stats: pd.DataFrame,
    intervals: pd.DataFrame,
    pupil_by_trial: Dict[Tuple, List[float]],
    pupil_by_participant: Dict[str, List[float]],
    pupil_by_baseline: Dict[str, List[float]],
    aoi_meta: pd.DataFrame,
    baseline_media_code: str,
) -> pd.DataFrame:
    formal_intervals = intervals[~intervals["excluded_from_formal"]].copy()
    interval_cols = TRIAL_KEY + ["interval_start_ms", "interval_end_ms", "interval_duration_ms"]
    base = formal_intervals[interval_cols].merge(sample_stats, on=TRIAL_KEY, how="left")

    participant_baseline = {}
    for participant, vals in pupil_by_participant.items():
        arr = np.asarray(vals, dtype=float)
        arr = arr[np.isfinite(arr)]
        participant_baseline[participant] = {
            "participant_pupil_mean": float(arr.mean()) if arr.size else np.nan,
            "participant_pupil_std": float(arr.std(ddof=1)) if arr.size > 1 else np.nan,
            "participant_pupil_median": float(np.median(arr)) if arr.size else np.nan,
        }
    period_baseline = {}
    for participant, vals in pupil_by_baseline.items():
        arr = np.asarray(vals, dtype=float)
        arr = arr[np.isfinite(arr)]
        period_baseline[participant] = {
            "baseline_period_media_code": baseline_media_code,
            "baseline_pupil_mean": float(arr.mean()) if arr.size else np.nan,
            "baseline_pupil_median": float(np.median(arr)) if arr.size else np.nan,
            "baseline_pupil_count": int(arr.size),
        }

    rows = []
    for key, vals in pupil_by_trial.items():
        participant = str(key[0])
        part = participant_baseline.get(participant, {})
        period = period_baseline.get(participant, {})
        mean_val = safe_mean(vals)
        median_val = safe_median(vals)
        mean_base = part.get("participant_pupil_mean", np.nan)
        std_base = part.get("participant_pupil_std", np.nan)
        median_base = part.get("participant_pupil_median", np.nan)
        baseline_mean = period.get("baseline_pupil_mean", np.nan)
        baseline_median = period.get("baseline_pupil_median", np.nan)
        rows.append(
            dict(
                zip(TRIAL_KEY, key),
                pupil_mean=mean_val,
                pupil_median=median_val,
                pupil_within_participant_z=(mean_val - mean_base) / std_base if np.isfinite(std_base) and std_base > 0 else np.nan,
                pupil_participant_median_corrected_pct=(median_val - median_base) / median_base * 100 if np.isfinite(median_base) and median_base != 0 else np.nan,
                participant_pupil_mean=mean_base,
                participant_pupil_std=std_base,
                participant_pupil_median=median_base,
                baseline_period_media_code=period.get("baseline_period_media_code", baseline_media_code),
                baseline_pupil_mean=baseline_mean,
                baseline_pupil_median=baseline_median,
                baseline_pupil_count=period.get("baseline_pupil_count", 0),
                pupil_expansion_rate_vs_baseline_pct=(mean_val - baseline_mean) / baseline_mean * 100 if np.isfinite(baseline_mean) and baseline_mean != 0 else np.nan,
                pupil_median_expansion_rate_vs_baseline_pct=(median_val - baseline_median) / baseline_median * 100 if np.isfinite(baseline_median) and baseline_median != 0 else np.nan,
            )
        )
    base = base.merge(pd.DataFrame(rows), on=TRIAL_KEY, how="left")
    base["valid_sample_ratio"] = base["valid_sample_count"] / base["sample_count"].replace(0, np.nan)
    base["eyes_not_found_ratio"] = base["eyes_not_found_count"] / base["sample_count"].replace(0, np.nan)

    trial_rows = []
    if not fixation_stats.empty:
        aoi_cols_by_media = {media: group["aoi_hit_column"].tolist() for media, group in aoi_meta.groupby("media_code", sort=False)}
        class_by_col = dict(zip(aoi_meta["aoi_hit_column"], aoi_meta["semantic_class_auto"]))
        for key, group in fixation_stats.groupby(TRIAL_KEY, dropna=False):
            group = group.sort_values("fixation_start_ms")
            durations = pd.to_numeric(group["fixation_duration_ms"], errors="coerce").to_numpy(dtype=float)
            valid_durations = durations[np.isfinite(durations)]
            first_idx = group["fixation_start_ms"].idxmin()
            xs = pd.to_numeric(group["fixation_x"], errors="coerce").to_numpy(dtype=float)
            ys = pd.to_numeric(group["fixation_y"], errors="coerce").to_numpy(dtype=float)
            finite_xy = np.isfinite(xs) & np.isfinite(ys)
            if finite_xy.sum() >= 2:
                deltas = np.diff(np.column_stack([xs[finite_xy], ys[finite_xy]]), axis=0)
                distances = np.sqrt(np.square(deltas).sum(axis=1))
                scanpath_length = float(distances.sum())
                mean_distance = float(distances.mean())
            else:
                scanpath_length = 0.0
                mean_distance = np.nan
            class_sequence = [choose_fixation_class(row, aoi_cols_by_media, class_by_col) for _, row in group.iterrows()]
            transitions = [(class_sequence[i - 1], class_sequence[i]) for i in range(1, len(class_sequence)) if class_sequence[i] != class_sequence[i - 1]]
            transition_counts = pd.Series(transitions).value_counts() if transitions else pd.Series(dtype=int)
            trial_rows.append(
                {
                    **dict(zip(TRIAL_KEY, key)),
                    "fixation_count": int(len(group)),
                    "total_fixation_duration_ms": float(np.nansum(valid_durations)),
                    "mean_fixation_duration_ms": float(np.nanmean(valid_durations)) if valid_durations.size else np.nan,
                    "min_fixation_duration_ms": float(np.nanmin(valid_durations)) if valid_durations.size else np.nan,
                    "max_fixation_duration_ms": float(np.nanmax(valid_durations)) if valid_durations.size else np.nan,
                    "first_fixation_start_ms": float(group.loc[first_idx, "fixation_start_ms"]),
                    "first_fixation_duration_ms": float(group.loc[first_idx, "fixation_duration_ms"]),
                    "scanpath_length_px": scanpath_length,
                    "mean_fixation_to_fixation_distance_px": mean_distance,
                    "aoi_transition_count": int(len(transitions)),
                    "aoi_transition_entropy": shannon_entropy(transition_counts.to_numpy(dtype=float)) if len(transition_counts) else 0.0,
                }
            )
    base = base.merge(pd.DataFrame(trial_rows), on=TRIAL_KEY, how="left")
    base["time_to_first_fixation_ms"] = base["first_fixation_start_ms"] - base["interval_start_ms"]

    if not saccade_stats.empty:
        saccade_trial = saccade_stats.groupby(TRIAL_KEY, dropna=False).agg(
            saccade_count=("eye_movement_type_index", "count"),
            total_saccade_duration_ms=("saccade_duration_ms", "sum"),
            mean_saccade_duration_ms=("saccade_duration_ms", "mean"),
        ).reset_index()
        base = base.merge(saccade_trial, on=TRIAL_KEY, how="left")
    else:
        base["saccade_count"] = np.nan
        base["total_saccade_duration_ms"] = np.nan
        base["mean_saccade_duration_ms"] = np.nan

    for col in ["fixation_count", "saccade_count"]:
        base[col] = base[col].fillna(0).astype(int)
    for col in ["total_fixation_duration_ms", "total_saccade_duration_ms", "scanpath_length_px", "aoi_transition_count", "aoi_transition_entropy"]:
        if col in base.columns:
            base[col] = base[col].fillna(0)

    diagonal = np.sqrt(pd.to_numeric(base["presented_media_width"], errors="coerce") ** 2 + pd.to_numeric(base["presented_media_height"], errors="coerce") ** 2)
    base["normalized_scanpath_length"] = base["scanpath_length_px"] / diagonal.replace(0, np.nan)
    return base.sort_values(["participant", "picture_id"]).reset_index(drop=True)


def compute_runs(mask: Sequence[bool], durations: Sequence[float]) -> Tuple[int, List[float]]:
    run_count = 0
    run_durations: List[float] = []
    in_run = False
    current = 0.0
    for hit, duration in zip(mask, durations):
        if hit:
            if not in_run:
                run_count += 1
                current = 0.0
                in_run = True
            if np.isfinite(duration):
                current += float(duration)
        elif in_run:
            run_durations.append(current)
            in_run = False
    if in_run:
        run_durations.append(current)
    return run_count, run_durations


def build_aoi_long(trial_metrics: pd.DataFrame, fixation_stats: pd.DataFrame, aoi_sample_stats: pd.DataFrame, aoi_meta: pd.DataFrame) -> pd.DataFrame:
    aoi_cols_by_media = {media: group.sort_values("aoi_name")["aoi_hit_column"].tolist() for media, group in aoi_meta.groupby("media_code", sort=False)}
    meta_by_col = aoi_meta.set_index("aoi_hit_column").to_dict("index")
    sample_stats_by_key = {}
    if not aoi_sample_stats.empty:
        for rec in aoi_sample_stats.to_dict("records"):
            sample_stats_by_key[tuple(rec[k] for k in TRIAL_KEY) + (rec["aoi_hit_column"],)] = rec
    fix_groups = {key: group.sort_values("fixation_start_ms").copy() for key, group in fixation_stats.groupby(TRIAL_KEY, dropna=False)} if not fixation_stats.empty else {}

    rows = []
    for trial in trial_metrics.to_dict("records"):
        trial_key = tuple(trial[k] for k in TRIAL_KEY)
        group = fix_groups.get(trial_key, pd.DataFrame())
        durations = pd.to_numeric(group.get("fixation_duration_ms", pd.Series(dtype=float)), errors="coerce").to_numpy(dtype=float)
        for col in aoi_cols_by_media.get(trial["media_code"], []):
            meta = meta_by_col[col]
            hits = pd.to_numeric(group[col], errors="coerce").fillna(0).gt(0).to_numpy() if not group.empty and col in group.columns else np.zeros(len(group), dtype=bool)
            hit_durations = durations[hits] if len(durations) else np.asarray([], dtype=float)
            visit_count, visit_durations = compute_runs(hits, durations)
            hit_starts = pd.to_numeric(group.loc[hits, "fixation_start_ms"], errors="coerce") if len(group) else pd.Series(dtype=float)
            first_start = float(hit_starts.min()) if len(hit_starts) else np.nan
            first_idx = hit_starts.idxmin() if len(hit_starts) else None
            sample_rec = sample_stats_by_key.get(trial_key + (col,), {})
            avg_aoi_pupil = sample_rec.get("aoi_average_pupil_diameter", np.nan)
            baseline_mean = trial.get("baseline_pupil_mean", np.nan)
            rows.append(
                {
                    **{k: trial[k] for k in TRIAL_KEY},
                    "aoi_hit_column": col,
                    "aoi_name": meta["aoi_name"],
                    "semantic_class_auto": meta["semantic_class_auto"],
                    "aoi_size": meta["aoi_size"],
                    "duration_of_interval_ms": trial.get("interval_duration_ms", np.nan),
                    "total_duration_of_fixations_ms": float(np.nansum(hit_durations)) if hit_durations.size else 0.0,
                    "average_duration_of_fixations_ms": float(np.nanmean(hit_durations)) if hit_durations.size else np.nan,
                    "minimum_duration_of_fixations_ms": float(np.nanmin(hit_durations)) if hit_durations.size else np.nan,
                    "maximum_duration_of_fixations_ms": float(np.nanmax(hit_durations)) if hit_durations.size else np.nan,
                    "number_of_fixations": int(hits.sum()) if len(hits) else 0,
                    "time_to_first_fixation_ms": first_start - trial.get("interval_start_ms", np.nan) if np.isfinite(first_start) else np.nan,
                    "duration_of_first_fixation_ms": float(group.loc[first_idx, "fixation_duration_ms"]) if first_idx is not None else np.nan,
                    "last_aoi_viewed": bool(hits[-1]) if len(hits) else False,
                    "aoi_at_interval_end": bool(hits[-1]) if len(hits) else False,
                    "total_duration_of_visit_ms": float(np.nansum(visit_durations)) if visit_durations else 0.0,
                    "average_duration_of_visit_ms": float(np.nanmean(visit_durations)) if visit_durations else np.nan,
                    "number_of_visits": int(visit_count),
                    "revisit_count": max(int(visit_count) - 1, 0),
                    "total_duration_of_glances_ms": float(np.nansum(visit_durations)) if visit_durations else 0.0,
                    "number_of_glances": int(visit_count),
                    "aoi_hit_sample_count": sample_rec.get("aoi_hit_sample_count", 0),
                    "aoi_pupil_sum": sample_rec.get("aoi_pupil_sum", 0),
                    "aoi_pupil_count": sample_rec.get("aoi_pupil_count", 0),
                    "aoi_average_pupil_diameter": avg_aoi_pupil,
                    "baseline_period_media_code": trial.get("baseline_period_media_code", np.nan),
                    "baseline_pupil_mean": baseline_mean,
                    "baseline_pupil_count": trial.get("baseline_pupil_count", 0),
                    "aoi_pupil_expansion_rate_vs_baseline_pct": (avg_aoi_pupil - baseline_mean) / baseline_mean * 100 if np.isfinite(avg_aoi_pupil) and np.isfinite(baseline_mean) and baseline_mean != 0 else np.nan,
                }
            )
    return pd.DataFrame(rows)


def build_aoi_class_wide(trial_metrics: pd.DataFrame, fixation_stats: pd.DataFrame, aoi_meta: pd.DataFrame, aoi_long: pd.DataFrame) -> pd.DataFrame:
    class_to_cols_by_media: Dict[str, Dict[str, List[str]]] = defaultdict(dict)
    for media, group in aoi_meta.groupby("media_code", sort=False):
        for cls, cls_group in group.groupby("semantic_class_auto"):
            class_to_cols_by_media[media][cls] = cls_group["aoi_hit_column"].tolist()
    fix_groups = {key: group.sort_values("fixation_start_ms").copy() for key, group in fixation_stats.groupby(TRIAL_KEY, dropna=False)} if not fixation_stats.empty else {}
    classes = sorted(aoi_meta["semantic_class_auto"].dropna().unique().tolist())
    rows = []
    for trial in trial_metrics.to_dict("records"):
        trial_key = tuple(trial[k] for k in TRIAL_KEY)
        group = fix_groups.get(trial_key, pd.DataFrame())
        durations = pd.to_numeric(group.get("fixation_duration_ms", pd.Series(dtype=float)), errors="coerce").to_numpy(dtype=float)
        row = {k: trial[k] for k in TRIAL_KEY}
        class_durations = []
        for cls in classes:
            cols = class_to_cols_by_media.get(trial["media_code"], {}).get(cls, [])
            if not group.empty and cols:
                hit_df = numeric_frame(group, [c for c in cols if c in group.columns]).fillna(0).gt(0)
                hits = hit_df.any(axis=1).to_numpy() if hit_df.shape[1] else np.zeros(len(group), dtype=bool)
            else:
                hits = np.zeros(len(group), dtype=bool)
            hit_durations = durations[hits] if len(durations) else np.asarray([], dtype=float)
            visit_count, visit_durations = compute_runs(hits, durations)
            total_duration = float(np.nansum(hit_durations)) if hit_durations.size else 0.0
            class_durations.append(total_duration)
            prefix = f"class_{cls}"
            row[f"{prefix}_fixation_duration_ms"] = total_duration
            row[f"{prefix}_fixation_count"] = int(hits.sum()) if len(hits) else 0
            row[f"{prefix}_visit_count"] = int(visit_count)
            row[f"{prefix}_visit_duration_ms"] = float(np.nansum(visit_durations)) if visit_durations else 0.0
        trial_total = trial.get("total_fixation_duration_ms", np.nan)
        for cls, duration in zip(classes, class_durations):
            row[f"class_{cls}_duration_share_of_trial"] = duration / trial_total if np.isfinite(trial_total) and trial_total > 0 else np.nan
        row["semantic_attention_entropy"] = shannon_entropy(class_durations)
        row["semantic_attention_hhi"] = hhi(class_durations)
        row["semantic_attention_gini"] = gini(class_durations)
        rows.append(row)
    class_wide = pd.DataFrame(rows)
    if not aoi_long.empty:
        tmp = aoi_long.copy()
        pupil_grouped = tmp.groupby(TRIAL_KEY + ["semantic_class_auto"], dropna=False).agg(
            class_aoi_pupil_count=("aoi_pupil_count", "sum"),
            class_average_pupil_diameter=("aoi_average_pupil_diameter", "mean"),
            baseline_pupil_mean=("baseline_pupil_mean", first_non_null),
        ).reset_index()
        pupil_grouped["class_pupil_expansion_rate_vs_baseline_pct"] = (
            (pupil_grouped["class_average_pupil_diameter"] - pupil_grouped["baseline_pupil_mean"])
            / pupil_grouped["baseline_pupil_mean"].replace(0, np.nan)
            * 100
        )
        for value_col in ["class_aoi_pupil_count", "class_average_pupil_diameter", "class_pupil_expansion_rate_vs_baseline_pct"]:
            wide = pupil_grouped.pivot_table(index=TRIAL_KEY, columns="semantic_class_auto", values=value_col, aggfunc="first")
            wide.columns = [f"class_{c}_{value_col.replace('class_', '')}" for c in wide.columns]
            class_wide = class_wide.merge(wide.reset_index(), on=TRIAL_KEY, how="left")
    return class_wide


def write_report(out_dir: Path, raw_tsv: Path, columns: List[str], group_column: Optional[str], intervals: pd.DataFrame, aoi_meta: pd.DataFrame, trial: pd.DataFrame, aoi_long: pd.DataFrame, baseline_media_code: str) -> None:
    lines = [
        "# Tobii raw-TSV extraction report",
        "",
        f"- Raw TSV: `{raw_tsv}`",
        f"- Raw columns: {len(columns)}",
        f"- Group column: `{group_column}`" if group_column else "- Group column: not found; `participant_group=ALL` was used.",
        f"- Baseline media code: `{baseline_media_code}`" if baseline_media_code else "- Baseline media code: not set.",
        f"- Image intervals: {len(intervals)}",
        f"- Formal trial rows: {len(trial)}",
        f"- Participants: {trial['participant'].nunique()}",
        f"- Participant groups: {', '.join(map(str, sorted(trial['participant_group'].dropna().unique().tolist())))}",
        f"- Media/images included: {trial['media_code'].nunique()}",
        f"- AOI definitions detected: {len(aoi_meta)}",
        f"- AOI metric rows: {len(aoi_long)}",
        "",
        "## Output files",
        "- `interval_inventory.csv`: ImageStimulusStart/ImageStimulusEnd-derived intervals.",
        "- `aoi_metadata.csv`: detected AOI hit/size columns and automatic semantic class labels.",
        "- `sample_trial_inventory.csv`: sample-level QC and pupil counts per participant-image.",
        "- `trial_metrics.csv`: participant-image metrics.",
        "- `aoi_metrics_long.csv`: participant-image-AOI metrics.",
        "- `aoi_class_metrics_wide.csv`: automatically grouped semantic AOI-class metrics.",
        "",
        "## Notes",
        "- Fixation and saccade metrics reuse Tobii Pro Lab's raw-export `Eye movement type` and `Eye movement type index`.",
        "- AOI duration and visit metrics are reconstructed from fixation rows and AOI hit columns.",
        "- Pupil expansion rate is `(mean pupil during target period - baseline mean pupil) / baseline mean pupil * 100`.",
    ]
    (out_dir / "extraction_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_extraction(raw_tsv: Path, output_dir: Optional[Path], chunksize: int, group_column_arg: Optional[str], baseline_media_code: str, exclude_media_codes: str) -> Path:
    raw_tsv = raw_tsv.expanduser().resolve()
    if not raw_tsv.exists():
        raise FileNotFoundError(raw_tsv)
    out_dir = output_dir.expanduser().resolve() if output_dir else raw_tsv.parent / DEFAULT_OUTPUT_FOLDER_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    columns = read_header(raw_tsv)
    group_column = detect_group_column(columns, group_column_arg)
    excluded_media = {media_code_from_name(x) or x.strip() for x in exclude_media_codes.split(",") if x.strip()}
    print("Detecting AOIs...", flush=True)
    aoi_meta = build_aoi_metadata(raw_tsv, columns, out_dir)
    print(f"Detected {len(aoi_meta)} AOI hit columns.", flush=True)

    print("Building image interval inventory...", flush=True)
    intervals = build_intervals(raw_tsv, out_dir, chunksize, group_column, excluded_media)
    included = intervals.loc[~intervals["excluded_from_formal"], ["media_code", "picture_id"]].dropna().drop_duplicates()
    included_media_codes = set(included["media_code"].astype(str))
    media_picture_ids = dict(zip(included["media_code"], included["picture_id"].astype(int)))
    aoi_meta["picture_id"] = aoi_meta["media_code"].map(media_picture_ids).fillna(aoi_meta["picture_id"])
    aoi_meta.to_csv(out_dir / "aoi_metadata.csv", index=False, encoding="utf-8-sig")

    print("Aggregating samples, fixations, saccades and AOI hits...", flush=True)
    sample_stats, fixation_stats, saccade_stats, aoi_sample_stats, pupil_by_trial, pupil_by_participant, pupil_by_baseline = aggregate_chunks(
        raw_tsv, chunksize, aoi_meta, out_dir, group_column, baseline_media_code, included_media_codes, media_picture_ids
    )
    print("Building trial metrics...", flush=True)
    trial = build_trial_metrics(sample_stats, fixation_stats, saccade_stats, intervals, pupil_by_trial, pupil_by_participant, pupil_by_baseline, aoi_meta, baseline_media_code)
    print("Building AOI metrics...", flush=True)
    aoi_long = build_aoi_long(trial, fixation_stats, aoi_sample_stats, aoi_meta)
    print("Building semantic class metrics...", flush=True)
    class_wide = build_aoi_class_wide(trial, fixation_stats, aoi_meta, aoi_long)
    trial_enriched = trial.merge(class_wide, on=TRIAL_KEY, how="left", suffixes=("", "_class"))

    trial_enriched.to_csv(out_dir / "trial_metrics.csv", index=False, encoding="utf-8-sig")
    aoi_long.to_csv(out_dir / "aoi_metrics_long.csv", index=False, encoding="utf-8-sig")
    class_wide.to_csv(out_dir / "aoi_class_metrics_wide.csv", index=False, encoding="utf-8-sig")
    write_report(out_dir, raw_tsv, columns, group_column, intervals, aoi_meta, trial_enriched, aoi_long, baseline_media_code)
    print(f"Done. Outputs written to: {out_dir}", flush=True)
    return out_dir


def launch_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("Tobii TSV Extractor")
    root.geometry("760x310")

    raw_var = tk.StringVar()
    out_var = tk.StringVar()
    group_var = tk.StringVar()
    baseline_var = tk.StringVar()
    exclude_var = tk.StringVar()
    status_var = tk.StringVar(value="Paste/select a Tobii raw TSV path, then run extraction.")

    def browse_raw() -> None:
        path = filedialog.askopenfilename(title="Select Tobii raw TSV", filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")])
        if path:
            raw_var.set(path)
            if not out_var.get():
                out_var.set(str(Path(path).parent / DEFAULT_OUTPUT_FOLDER_NAME))

    def browse_out() -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            out_var.set(path)

    def run() -> None:
        try:
            if not raw_var.get().strip():
                raise ValueError("Please select a raw TSV file.")
            status_var.set("Running... This may take several minutes for large TSV files.")
            root.update_idletasks()
            out_dir = run_extraction(
                Path(raw_var.get().strip()),
                Path(out_var.get().strip()) if out_var.get().strip() else None,
                100_000,
                group_var.get().strip() or None,
                baseline_var.get().strip(),
                exclude_var.get().strip(),
            )
            status_var.set(f"Done: {out_dir}")
            messagebox.showinfo("Extraction finished", f"Outputs written to:\n{out_dir}")
        except Exception as exc:  # pragma: no cover - GUI path
            status_var.set("Failed. Check the error message.")
            messagebox.showerror("Extraction failed", str(exc))

    pad = {"padx": 10, "pady": 6}
    tk.Label(root, text="Raw TSV path").grid(row=0, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=raw_var, width=78).grid(row=0, column=1, sticky="ew", **pad)
    tk.Button(root, text="Browse", command=browse_raw).grid(row=0, column=2, **pad)

    tk.Label(root, text="Output folder").grid(row=1, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=out_var, width=78).grid(row=1, column=1, sticky="ew", **pad)
    tk.Button(root, text="Browse", command=browse_out).grid(row=1, column=2, **pad)

    tk.Label(root, text="Group column").grid(row=2, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=group_var, width=78).grid(row=2, column=1, sticky="ew", **pad)

    tk.Label(root, text="Baseline media code").grid(row=3, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=baseline_var, width=78).grid(row=3, column=1, sticky="ew", **pad)

    tk.Label(root, text="Exclude media codes").grid(row=4, column=0, sticky="w", **pad)
    tk.Entry(root, textvariable=exclude_var, width=78).grid(row=4, column=1, sticky="ew", **pad)

    tk.Button(root, text="Run Extraction", command=run, width=20).grid(row=5, column=1, sticky="w", **pad)
    tk.Label(root, textvariable=status_var, wraplength=690, anchor="w", justify="left").grid(row=6, column=0, columnspan=3, sticky="ew", **pad)
    root.columnconfigure(1, weight=1)
    root.mainloop()
    return 0


def main() -> int:
    args = parse_args()
    if args.gui or args.raw_tsv is None:
        return launch_gui()
    run_extraction(args.raw_tsv, args.output_dir, args.chunksize, args.group_column, args.baseline_media_code, args.exclude_media_codes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
