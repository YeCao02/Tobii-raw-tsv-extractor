# -*- coding: utf-8 -*-
"""Reusable Tobii Pro Lab raw TSV extractor.

The script reconstructs trial-level, AOI-level, and semantic AOI-class metrics
from a Tobii Pro Lab raw TSV export. It uses Tobii's own exported eye-movement
labels; it does not re-run fixation detection.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

TRIAL_KEY = ["participant", "recording", "participant_group", "picture_id", "media_code"]
FIX_KEY = TRIAL_KEY + ["eye_movement_type_index"]
DEFAULT_OUTPUT_FOLDER_NAME = "tobii_tsv_extracted_metrics"
KNOWN_GROUP_COLUMNS = ["specialist", "Participant group", "participant group", "Group", "group", "Subject group"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract metrics from Tobii Pro Lab raw TSV exports.")
    parser.add_argument("--raw-tsv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--chunksize", type=int, default=100_000)
    parser.add_argument("--group-column", type=str, default=None)
    parser.add_argument("--baseline-media-code", type=str, default="")
    parser.add_argument("--exclude-media-codes", type=str, default="")
    parser.add_argument("--gui", action="store_true")
    return parser.parse_args()


def media_code_from_name(value: object) -> Optional[str]:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"\s+\(\d+\)$", "", text)
    return re.sub(r"\.(jpg|jpeg|png|bmp|gif|tif|tiff)$", "", text, flags=re.I)


def picture_id_from_code(value: object) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    match = re.match(r"^(\d+)(?:-|_|\.|\s|$)", str(value).strip())
    return int(match.group(1)) if match else None


def parse_aoi_column(col: str, prefix: str = "AOI hit") -> Tuple[str, str]:
    match = re.match(re.escape(prefix) + r" \[(.+?) - (.+)\]$", col)
    if not match:
        raise ValueError(f"Cannot parse AOI column: {col}")
    return media_code_from_name(match.group(1)) or match.group(1), match.group(2)


def semantic_class(name: str) -> str:
    text = re.sub(r"\s+", " ", str(name).strip().lower().replace("_", " "))
    if any(x in text for x in ["human", "people", "person"]):
        return "human_activities"
    if any(x in text for x in ["traditional", "historic", "heritage"]):
        return "traditional_building"
    if "commercial" in text or text == "buildings" or "building" in text:
        return "commercial_building"
    if "riparian" in text or "waterfront vegetation" in text:
        return "riparian_vegetation"
    if any(x in text for x in ["upland", "vegetation", "tree", "plant"]):
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
    return "other"


def first_non_null(series: pd.Series) -> object:
    s = series.dropna()
    return s.iloc[0] if len(s) else np.nan


def numeric_frame(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    return df.loc[:, list(cols)].apply(pd.to_numeric, errors="coerce")


def entropy(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if arr.size == 0 or arr.sum() <= 0:
        return 0.0
    p = arr / arr.sum()
    return float(-(p * np.log2(p)).sum())


def hhi(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if arr.size == 0 or arr.sum() <= 0:
        return 0.0
    p = arr / arr.sum()
    return float(np.square(p).sum())


def gini(values: Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr) & (arr >= 0)]
    if arr.size == 0 or np.all(arr == 0):
        return 0.0
    arr = np.sort(arr)
    n = arr.size
    return float((2 * np.arange(1, n + 1) - n - 1).dot(arr) / (n * arr.sum()))


def detect_group_column(columns: List[str], requested: Optional[str]) -> Optional[str]:
    if requested:
        if requested not in columns:
            raise ValueError(f"Group column not found: {requested}")
        return requested
    return next((c for c in KNOWN_GROUP_COLUMNS if c in columns), None)


def resolve_picture_ids(media_codes: Sequence[str]) -> Dict[str, int]:
    explicit = {m: picture_id_from_code(m) for m in media_codes}
    used = {v for v in explicit.values() if v is not None}
    next_id = 1
    out = {}
    for media in media_codes:
        pid = explicit.get(media)
        if pid is None:
            while next_id in used:
                next_id += 1
            pid = next_id
            used.add(pid)
        out[media] = int(pid)
    return out


def build_aoi_metadata(raw_tsv: Path, columns: List[str], out_dir: Path) -> pd.DataFrame:
    hit_cols = [c for c in columns if c.startswith("AOI hit [")]
    size_cols = [c for c in columns if c.startswith("AOI size [")]
    size_map = {}
    if size_cols:
        size_row = pd.read_csv(raw_tsv, sep="\t", usecols=size_cols, nrows=1)
        for col in size_cols:
            media, name = parse_aoi_column(col, "AOI size")
            size_map[(media, name)] = pd.to_numeric(size_row[col], errors="coerce").iloc[0]
    rows = []
    for col in hit_cols:
        media, name = parse_aoi_column(col, "AOI hit")
        rows.append({
            "aoi_hit_column": col,
            "media_code": media,
            "picture_id": picture_id_from_code(media),
            "aoi_name": name,
            "semantic_class_auto": semantic_class(name),
            "aoi_size": size_map.get((media, name), np.nan),
        })
    meta = pd.DataFrame(rows).sort_values(["media_code", "aoi_name"]).reset_index(drop=True)
    meta.to_csv(out_dir / "aoi_metadata.csv", index=False, encoding="utf-8-sig")
    return meta


def build_intervals(raw_tsv: Path, out_dir: Path, chunksize: int, group_column: Optional[str], excluded_media: set[str]) -> pd.DataFrame:
    cols = ["Participant name", "Recording name", "Recording timestamp", "Event", "Event value"]
    if group_column:
        cols.append(group_column)
    frames = []
    row_offset = 0
    for chunk in pd.read_csv(raw_tsv, sep="\t", usecols=cols, chunksize=chunksize, low_memory=False):
        chunk["_row_number"] = np.arange(row_offset, row_offset + len(chunk))
        row_offset += len(chunk)
        ev = chunk[chunk["Event"].isin(["ImageStimulusStart", "ImageStimulusEnd"])].copy()
        if not ev.empty:
            frames.append(ev)
    if not frames:
        raise RuntimeError("No ImageStimulusStart/ImageStimulusEnd events found.")
    ev = pd.concat(frames, ignore_index=True)
    ev["recording_timestamp_ms"] = pd.to_numeric(ev["Recording timestamp"], errors="coerce")
    ev = ev.rename(columns={"Participant name": "participant", "Recording name": "recording", "Event value": "event_value"})
    ev["participant_group"] = ev[group_column].fillna("Unknown").astype(str) if group_column else "ALL"
    rows = []
    for (participant, recording), group in ev.sort_values(["recording_timestamp_ms", "_row_number"]).groupby(["participant", "recording"], dropna=False):
        start = None
        for rec in group.to_dict("records"):
            if rec["Event"] == "ImageStimulusStart":
                start = rec
            elif rec["Event"] == "ImageStimulusEnd" and start is not None:
                media = media_code_from_name(start.get("event_value"))
                rows.append({
                    "participant": participant,
                    "recording": recording,
                    "participant_group": start.get("participant_group", "ALL"),
                    "event_value_start": str(start.get("event_value", "")).strip(),
                    "event_value_end": str(rec.get("event_value", "")).strip(),
                    "media_code": media,
                    "interval_start_ms": start["recording_timestamp_ms"],
                    "interval_end_ms": rec["recording_timestamp_ms"],
                    "interval_duration_ms": rec["recording_timestamp_ms"] - start["recording_timestamp_ms"],
                    "excluded_from_formal": bool(media in excluded_media),
                })
                start = None
    intervals = pd.DataFrame(rows)
    pid_map = resolve_picture_ids(intervals["media_code"].dropna().drop_duplicates().tolist())
    intervals["picture_id"] = intervals["media_code"].map(pid_map)
    intervals.to_csv(out_dir / "interval_inventory.csv", index=False, encoding="utf-8-sig")
    return intervals


def aggregate_chunks(raw_tsv: Path, chunksize: int, aoi_meta: pd.DataFrame, out_dir: Path, group_column: Optional[str], baseline_media: str, included_media: set[str], media_picture_ids: Dict[str, int]):
    aoi_cols = aoi_meta["aoi_hit_column"].tolist()
    aoi_cols_by_media = {m: g["aoi_hit_column"].tolist() for m, g in aoi_meta.groupby("media_code", sort=False)}
    base_cols = ["Participant name", "Recording name", "Recording timestamp", "Presented Media name", "Presented Media width", "Presented Media height", "Original Media width", "Original Media height", "Eye movement type", "Eye movement event duration", "Eye movement type index", "Fixation point X", "Fixation point Y", "Pupil diameter filtered", "Validity left", "Validity right"]
    if group_column:
        base_cols.insert(1, group_column)
    usecols = base_cols + aoi_cols
    sample_frames, fix_frames, sac_frames, aoi_sample_frames = [], [], [], []
    pupil_by_trial, pupil_by_participant, pupil_by_baseline = defaultdict(list), defaultdict(list), defaultdict(list)
    for i, chunk in enumerate(pd.read_csv(raw_tsv, sep="\t", usecols=usecols, chunksize=chunksize, low_memory=False), start=1):
        chunk = chunk.rename(columns={"Participant name": "participant", "Recording name": "recording", "Presented Media name": "presented_media_name", "Recording timestamp": "recording_timestamp_ms", "Eye movement type index": "eye_movement_type_index"})
        chunk["participant_group"] = chunk[group_column].fillna("Unknown").astype(str) if group_column else "ALL"
        chunk["media_code"] = chunk["presented_media_name"].map(media_code_from_name)
        chunk["picture_id"] = chunk["media_code"].map(media_picture_ids)
        chunk["Pupil diameter filtered"] = pd.to_numeric(chunk["Pupil diameter filtered"], errors="coerce")
        chunk["valid_sample"] = chunk["Validity left"].eq("Valid") | chunk["Validity right"].eq("Valid")
        if baseline_media:
            b = chunk[chunk["media_code"].eq(baseline_media)]
            if not b.empty:
                p = pd.to_numeric(b["Pupil diameter filtered"], errors="coerce")
                tmp = b.loc[np.isfinite(p) & b["valid_sample"], ["participant"]].copy()
                tmp["_pupil"] = p.loc[tmp.index].values
                for part, g in tmp.groupby("participant", dropna=False):
                    pupil_by_baseline[str(part)].extend(g["_pupil"].to_numpy(float).tolist())
        formal = chunk[chunk["media_code"].isin(included_media)].copy()
        if formal.empty:
            continue
        formal["picture_id"] = formal["picture_id"].astype(int)
        for col in ["recording_timestamp_ms", "Eye movement event duration", "eye_movement_type_index", "Fixation point X", "Fixation point Y"]:
            formal[col] = pd.to_numeric(formal[col], errors="coerce")
        formal["eyes_not_found"] = formal["Eye movement type"].eq("EyesNotFound")
        p = formal["Pupil diameter filtered"]
        sample = formal.copy()
        sample["_pupil_sum"] = p.where(np.isfinite(p), 0.0)
        sample["_pupil_count"] = np.isfinite(p).astype(int)
        sample["_valid_count"] = sample["valid_sample"].astype(int)
        sample["_eyes_not_found_count"] = sample["eyes_not_found"].astype(int)
        sample["_sample_count"] = 1
        sample_frames.append(sample.groupby(TRIAL_KEY, dropna=False).agg(sample_count=("_sample_count", "sum"), valid_sample_count=("_valid_count", "sum"), eyes_not_found_count=("_eyes_not_found_count", "sum"), pupil_sum=("_pupil_sum", "sum"), pupil_count=("_pupil_count", "sum"), sample_start_ms=("recording_timestamp_ms", "min"), sample_end_ms=("recording_timestamp_ms", "max"), presented_media_width=("Presented Media width", first_non_null), presented_media_height=("Presented Media height", first_non_null), original_media_width=("Original Media width", first_non_null), original_media_height=("Original Media height", first_non_null)).reset_index())
        valid = p[np.isfinite(p)]
        if not valid.empty:
            tmp = formal.loc[valid.index, TRIAL_KEY].copy(); tmp["_pupil"] = valid.values
            for key, g in tmp.groupby(TRIAL_KEY, dropna=False):
                vals = g["_pupil"].to_numpy(float).tolist(); pupil_by_trial[key].extend(vals); pupil_by_participant[str(key[0])].extend(vals)
        fix = formal[formal["Eye movement type"].eq("Fixation") & formal["eye_movement_type_index"].notna()].copy()
        if not fix.empty:
            fix["_x_sum"] = fix["Fixation point X"].where(np.isfinite(fix["Fixation point X"]), 0.0)
            fix["_y_sum"] = fix["Fixation point Y"].where(np.isfinite(fix["Fixation point Y"]), 0.0)
            fix["_xy_count"] = (np.isfinite(fix["Fixation point X"]) & np.isfinite(fix["Fixation point Y"])).astype(int)
            base = fix.groupby(FIX_KEY, dropna=False).agg(fixation_duration_ms=("Eye movement event duration", "max"), fixation_start_ms=("recording_timestamp_ms", "min"), fixation_end_ms=("recording_timestamp_ms", "max"), fixation_x_sum=("_x_sum", "sum"), fixation_y_sum=("_y_sum", "sum"), fixation_xy_count=("_xy_count", "sum"), fixation_sample_rows=("Eye movement type", "size"))
            for media in sorted(fix["media_code"].dropna().unique()):
                cols = aoi_cols_by_media.get(media, [])
                if cols:
                    sub = fix[fix["media_code"].eq(media)]
                    hits = numeric_frame(sub, cols).fillna(0); hits[FIX_KEY] = sub[FIX_KEY].values
                    base = base.join(hits.groupby(FIX_KEY, dropna=False)[cols].max(), how="left")
            fix_frames.append(base.reset_index())
        sac = formal[formal["Eye movement type"].eq("Saccade") & formal["eye_movement_type_index"].notna()].copy()
        if not sac.empty:
            sac_frames.append(sac.groupby(FIX_KEY, dropna=False).agg(saccade_duration_ms=("Eye movement event duration", "max"), saccade_start_ms=("recording_timestamp_ms", "min"), saccade_end_ms=("recording_timestamp_ms", "max"), saccade_sample_rows=("Eye movement type", "size")).reset_index())
        for media in sorted(formal["media_code"].dropna().unique()):
            cols = aoi_cols_by_media.get(media, [])
            if not cols: continue
            sub = formal[formal["media_code"].eq(media)].copy(); hits = numeric_frame(sub, cols).fillna(0).gt(0); pp = pd.to_numeric(sub["Pupil diameter filtered"], errors="coerce")
            for col in cols:
                mask = hits[col].to_numpy()
                if mask.any():
                    tmp = sub.loc[mask, TRIAL_KEY].copy(); tmp["aoi_hit_column"] = col; tmp["_aoi_sample_count"] = 1; tmp["_aoi_pupil_sum"] = pp.loc[tmp.index].where(np.isfinite(pp.loc[tmp.index]), 0.0).values; tmp["_aoi_pupil_count"] = np.isfinite(pp.loc[tmp.index]).astype(int).values
                    aoi_sample_frames.append(tmp.groupby(TRIAL_KEY + ["aoi_hit_column"], dropna=False).agg(aoi_hit_sample_count=("_aoi_sample_count", "sum"), aoi_pupil_sum=("_aoi_pupil_sum", "sum"), aoi_pupil_count=("_aoi_pupil_count", "sum")).reset_index())
        if i % 5 == 0:
            print(f"Processed chunk {i}", flush=True)
    sample_stats = pd.concat(sample_frames, ignore_index=True).groupby(TRIAL_KEY, dropna=False).agg(sample_count=("sample_count", "sum"), valid_sample_count=("valid_sample_count", "sum"), eyes_not_found_count=("eyes_not_found_count", "sum"), pupil_sum=("pupil_sum", "sum"), pupil_count=("pupil_count", "sum"), sample_start_ms=("sample_start_ms", "min"), sample_end_ms=("sample_end_ms", "max"), presented_media_width=("presented_media_width", first_non_null), presented_media_height=("presented_media_height", first_non_null), original_media_width=("original_media_width", first_non_null), original_media_height=("original_media_height", first_non_null)).reset_index()
    fix_stats = pd.concat(fix_frames, ignore_index=True) if fix_frames else pd.DataFrame(columns=FIX_KEY)
    if not fix_stats.empty:
        aoi_existing = [c for c in aoi_cols if c in fix_stats.columns]
        agg = {"fixation_duration_ms": "max", "fixation_start_ms": "min", "fixation_end_ms": "max", "fixation_x_sum": "sum", "fixation_y_sum": "sum", "fixation_xy_count": "sum", "fixation_sample_rows": "sum"}; agg.update({c: "max" for c in aoi_existing})
        fix_stats = fix_stats.groupby(FIX_KEY, dropna=False).agg(agg).reset_index()
        for c in aoi_cols:
            if c not in fix_stats.columns: fix_stats[c] = 0
        fix_stats[aoi_cols] = fix_stats[aoi_cols].fillna(0)
        fix_stats["fixation_x"] = fix_stats["fixation_x_sum"] / fix_stats["fixation_xy_count"].replace(0, np.nan)
        fix_stats["fixation_y"] = fix_stats["fixation_y_sum"] / fix_stats["fixation_xy_count"].replace(0, np.nan)
    sac_stats = pd.concat(sac_frames, ignore_index=True) if sac_frames else pd.DataFrame(columns=FIX_KEY)
    if not sac_stats.empty:
        sac_stats = sac_stats.groupby(FIX_KEY, dropna=False).agg(saccade_duration_ms=("saccade_duration_ms", "max"), saccade_start_ms=("saccade_start_ms", "min"), saccade_end_ms=("saccade_end_ms", "max"), saccade_sample_rows=("saccade_sample_rows", "sum")).reset_index()
    aoi_sample = pd.concat(aoi_sample_frames, ignore_index=True) if aoi_sample_frames else pd.DataFrame(columns=TRIAL_KEY + ["aoi_hit_column"])
    if not aoi_sample.empty:
        aoi_sample = aoi_sample.groupby(TRIAL_KEY + ["aoi_hit_column"], dropna=False).agg(aoi_hit_sample_count=("aoi_hit_sample_count", "sum"), aoi_pupil_sum=("aoi_pupil_sum", "sum"), aoi_pupil_count=("aoi_pupil_count", "sum")).reset_index()
        aoi_sample["aoi_average_pupil_diameter"] = aoi_sample["aoi_pupil_sum"] / aoi_sample["aoi_pupil_count"].replace(0, np.nan)
    sample_stats.to_csv(out_dir / "sample_trial_inventory.csv", index=False, encoding="utf-8-sig")
    return sample_stats, fix_stats, sac_stats, aoi_sample, pupil_by_trial, pupil_by_participant, pupil_by_baseline


def compute_runs(mask: Sequence[bool], durations: Sequence[float]) -> Tuple[int, List[float]]:
    n, vals, active, current = 0, [], False, 0.0
    for hit, dur in zip(mask, durations):
        if hit:
            if not active: n, active, current = n + 1, True, 0.0
            if np.isfinite(dur): current += float(dur)
        elif active:
            vals.append(current); active = False
    if active: vals.append(current)
    return n, vals


def build_trial_metrics(sample_stats, fix_stats, sac_stats, intervals, pupil_by_trial, pupil_by_participant, pupil_by_baseline, baseline_media):
    base = intervals[~intervals["excluded_from_formal"]][TRIAL_KEY + ["interval_start_ms", "interval_end_ms", "interval_duration_ms"]].merge(sample_stats, on=TRIAL_KEY, how="left")
    part_base = {p: {"mean": float(np.mean(v)), "std": float(np.std(v, ddof=1)) if len(v) > 1 else np.nan, "median": float(np.median(v))} for p, v in pupil_by_participant.items() if len(v)}
    period_base = {p: {"mean": float(np.mean(v)), "median": float(np.median(v)), "count": int(len(v))} for p, v in pupil_by_baseline.items() if len(v)}
    rows = []
    for key, vals in pupil_by_trial.items():
        vals = np.asarray(vals, float); vals = vals[np.isfinite(vals)]
        mean, med = (float(vals.mean()) if vals.size else np.nan), (float(np.median(vals)) if vals.size else np.nan)
        pb, bb = part_base.get(str(key[0]), {}), period_base.get(str(key[0]), {})
        rows.append(dict(zip(TRIAL_KEY, key), pupil_mean=mean, pupil_median=med, participant_pupil_mean=pb.get("mean", np.nan), participant_pupil_std=pb.get("std", np.nan), participant_pupil_median=pb.get("median", np.nan), baseline_period_media_code=baseline_media, baseline_pupil_mean=bb.get("mean", np.nan), baseline_pupil_median=bb.get("median", np.nan), baseline_pupil_count=bb.get("count", 0)))
    pupil = pd.DataFrame(rows)
    if not pupil.empty:
        pupil["pupil_within_participant_z"] = (pupil["pupil_mean"] - pupil["participant_pupil_mean"]) / pupil["participant_pupil_std"].replace(0, np.nan)
        pupil["pupil_participant_median_corrected_pct"] = (pupil["pupil_median"] - pupil["participant_pupil_median"]) / pupil["participant_pupil_median"].replace(0, np.nan) * 100
        pupil["pupil_expansion_rate_vs_baseline_pct"] = (pupil["pupil_mean"] - pupil["baseline_pupil_mean"]) / pupil["baseline_pupil_mean"].replace(0, np.nan) * 100
        pupil["pupil_median_expansion_rate_vs_baseline_pct"] = (pupil["pupil_median"] - pupil["baseline_pupil_median"]) / pupil["baseline_pupil_median"].replace(0, np.nan) * 100
        base = base.merge(pupil, on=TRIAL_KEY, how="left")
    base["valid_sample_ratio"] = base["valid_sample_count"] / base["sample_count"].replace(0, np.nan)
    base["eyes_not_found_ratio"] = base["eyes_not_found_count"] / base["sample_count"].replace(0, np.nan)
    fix_rows = []
    if not fix_stats.empty:
        for key, g in fix_stats.groupby(TRIAL_KEY, dropna=False):
            g = g.sort_values("fixation_start_ms"); d = pd.to_numeric(g["fixation_duration_ms"], errors="coerce").to_numpy(float); vd = d[np.isfinite(d)]
            first = g["fixation_start_ms"].idxmin(); xs = pd.to_numeric(g["fixation_x"], errors="coerce").to_numpy(float); ys = pd.to_numeric(g["fixation_y"], errors="coerce").to_numpy(float); ok = np.isfinite(xs) & np.isfinite(ys)
            if ok.sum() >= 2:
                dist = np.sqrt(np.square(np.diff(np.column_stack([xs[ok], ys[ok]]), axis=0)).sum(axis=1)); path, mean_dist = float(dist.sum()), float(dist.mean())
            else:
                path, mean_dist = 0.0, np.nan
            fix_rows.append(dict(zip(TRIAL_KEY, key), fixation_count=int(len(g)), total_fixation_duration_ms=float(np.nansum(vd)), mean_fixation_duration_ms=float(np.nanmean(vd)) if vd.size else np.nan, min_fixation_duration_ms=float(np.nanmin(vd)) if vd.size else np.nan, max_fixation_duration_ms=float(np.nanmax(vd)) if vd.size else np.nan, first_fixation_start_ms=float(g.loc[first, "fixation_start_ms"]), first_fixation_duration_ms=float(g.loc[first, "fixation_duration_ms"]), scanpath_length_px=path, mean_fixation_to_fixation_distance_px=mean_dist))
    if fix_rows:
        base = base.merge(pd.DataFrame(fix_rows), on=TRIAL_KEY, how="left")
    base["time_to_first_fixation_ms"] = base["first_fixation_start_ms"] - base["interval_start_ms"]
    if not sac_stats.empty:
        sac = sac_stats.groupby(TRIAL_KEY, dropna=False).agg(saccade_count=("eye_movement_type_index", "count"), total_saccade_duration_ms=("saccade_duration_ms", "sum"), mean_saccade_duration_ms=("saccade_duration_ms", "mean")).reset_index(); base = base.merge(sac, on=TRIAL_KEY, how="left")
    for c in ["fixation_count", "saccade_count"]:
        if c in base: base[c] = base[c].fillna(0).astype(int)
    diag = np.sqrt(pd.to_numeric(base["presented_media_width"], errors="coerce") ** 2 + pd.to_numeric(base["presented_media_height"], errors="coerce") ** 2)
    base["normalized_scanpath_length"] = base["scanpath_length_px"] / diag.replace(0, np.nan)
    return base.sort_values(["participant", "picture_id"]).reset_index(drop=True)


def build_aoi_long(trial, fix_stats, aoi_sample, aoi_meta):
    cols_by_media = {m: g.sort_values("aoi_name")["aoi_hit_column"].tolist() for m, g in aoi_meta.groupby("media_code", sort=False)}
    meta = aoi_meta.set_index("aoi_hit_column").to_dict("index")
    sample = {tuple(r[k] for k in TRIAL_KEY) + (r["aoi_hit_column"],): r for r in aoi_sample.to_dict("records")} if not aoi_sample.empty else {}
    fix_groups = {k: g.sort_values("fixation_start_ms") for k, g in fix_stats.groupby(TRIAL_KEY, dropna=False)} if not fix_stats.empty else {}
    rows = []
    for tr in trial.to_dict("records"):
        key = tuple(tr[k] for k in TRIAL_KEY); g = fix_groups.get(key, pd.DataFrame()); d = pd.to_numeric(g.get("fixation_duration_ms", pd.Series(dtype=float)), errors="coerce").to_numpy(float)
        for col in cols_by_media.get(tr["media_code"], []):
            hits = pd.to_numeric(g[col], errors="coerce").fillna(0).gt(0).to_numpy() if not g.empty and col in g.columns else np.zeros(len(g), bool)
            hd = d[hits] if len(d) else np.asarray([], float); nvisit, vdur = compute_runs(hits, d); starts = pd.to_numeric(g.loc[hits, "fixation_start_ms"], errors="coerce") if len(g) else pd.Series(dtype=float); first_start = float(starts.min()) if len(starts) else np.nan; first_idx = starts.idxmin() if len(starts) else None; sr = sample.get(key + (col,), {})
            avg_pupil, base_pupil = sr.get("aoi_average_pupil_diameter", np.nan), tr.get("baseline_pupil_mean", np.nan)
            rows.append({**{k: tr[k] for k in TRIAL_KEY}, "aoi_hit_column": col, "aoi_name": meta[col]["aoi_name"], "semantic_class_auto": meta[col]["semantic_class_auto"], "aoi_size": meta[col]["aoi_size"], "duration_of_interval_ms": tr.get("interval_duration_ms", np.nan), "total_duration_of_fixations_ms": float(np.nansum(hd)) if hd.size else 0.0, "average_duration_of_fixations_ms": float(np.nanmean(hd)) if hd.size else np.nan, "minimum_duration_of_fixations_ms": float(np.nanmin(hd)) if hd.size else np.nan, "maximum_duration_of_fixations_ms": float(np.nanmax(hd)) if hd.size else np.nan, "number_of_fixations": int(hits.sum()) if len(hits) else 0, "time_to_first_fixation_ms": first_start - tr.get("interval_start_ms", np.nan) if np.isfinite(first_start) else np.nan, "duration_of_first_fixation_ms": float(g.loc[first_idx, "fixation_duration_ms"]) if first_idx is not None else np.nan, "last_aoi_viewed": bool(hits[-1]) if len(hits) else False, "aoi_at_interval_end": bool(hits[-1]) if len(hits) else False, "total_duration_of_visit_ms": float(np.nansum(vdur)) if vdur else 0.0, "average_duration_of_visit_ms": float(np.nanmean(vdur)) if vdur else np.nan, "number_of_visits": int(nvisit), "revisit_count": max(int(nvisit) - 1, 0), "total_duration_of_glances_ms": float(np.nansum(vdur)) if vdur else 0.0, "number_of_glances": int(nvisit), "aoi_hit_sample_count": sr.get("aoi_hit_sample_count", 0), "aoi_pupil_sum": sr.get("aoi_pupil_sum", 0), "aoi_pupil_count": sr.get("aoi_pupil_count", 0), "aoi_average_pupil_diameter": avg_pupil, "baseline_period_media_code": tr.get("baseline_period_media_code", np.nan), "baseline_pupil_mean": base_pupil, "baseline_pupil_count": tr.get("baseline_pupil_count", 0), "aoi_pupil_expansion_rate_vs_baseline_pct": (avg_pupil - base_pupil) / base_pupil * 100 if np.isfinite(avg_pupil) and np.isfinite(base_pupil) and base_pupil != 0 else np.nan})
    return pd.DataFrame(rows)


def build_class_wide(trial, aoi_long):
    if aoi_long.empty:
        return trial[TRIAL_KEY].copy()
    agg = aoi_long.groupby(TRIAL_KEY + ["semantic_class_auto"], dropna=False).agg(class_fixation_duration_ms=("total_duration_of_fixations_ms", "sum"), class_fixation_count=("number_of_fixations", "sum"), class_visit_count=("number_of_visits", "sum"), class_visit_duration_ms=("total_duration_of_visit_ms", "sum"), class_aoi_pupil_count=("aoi_pupil_count", "sum"), class_average_pupil_diameter=("aoi_average_pupil_diameter", "mean"), baseline_pupil_mean=("baseline_pupil_mean", first_non_null)).reset_index()
    agg["class_pupil_expansion_rate_vs_baseline_pct"] = (agg["class_average_pupil_diameter"] - agg["baseline_pupil_mean"]) / agg["baseline_pupil_mean"].replace(0, np.nan) * 100
    out = trial[TRIAL_KEY + ["total_fixation_duration_ms"]].copy()
    for val in ["class_fixation_duration_ms", "class_fixation_count", "class_visit_count", "class_visit_duration_ms", "class_aoi_pupil_count", "class_average_pupil_diameter", "class_pupil_expansion_rate_vs_baseline_pct"]:
        wide = agg.pivot_table(index=TRIAL_KEY, columns="semantic_class_auto", values=val, aggfunc="first")
        wide.columns = [f"class_{c}_{val.replace('class_', '')}" for c in wide.columns]
        out = out.merge(wide.reset_index(), on=TRIAL_KEY, how="left")
    dur_cols = [c for c in out.columns if c.endswith("_fixation_duration_ms") and c.startswith("class_")]
    for c in dur_cols:
        out[c.replace("_fixation_duration_ms", "_duration_share_of_trial")] = out[c] / out["total_fixation_duration_ms"].replace(0, np.nan)
    out["semantic_attention_entropy"] = out[dur_cols].apply(lambda r: entropy(r.to_numpy(float)), axis=1)
    out["semantic_attention_hhi"] = out[dur_cols].apply(lambda r: hhi(r.to_numpy(float)), axis=1)
    out["semantic_attention_gini"] = out[dur_cols].apply(lambda r: gini(r.to_numpy(float)), axis=1)
    return out.drop(columns=["total_fixation_duration_ms"])


def run_extraction(raw_tsv: Path, output_dir: Optional[Path], chunksize: int, group_arg: Optional[str], baseline_media: str, exclude_media: str) -> Path:
    raw_tsv = raw_tsv.expanduser().resolve()
    out_dir = output_dir.expanduser().resolve() if output_dir else raw_tsv.parent / DEFAULT_OUTPUT_FOLDER_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = pd.read_csv(raw_tsv, sep="\t", nrows=0).columns.tolist()
    group_column = detect_group_column(columns, group_arg)
    excluded = {media_code_from_name(x) or x.strip() for x in exclude_media.split(",") if x.strip()}
    aoi_meta = build_aoi_metadata(raw_tsv, columns, out_dir)
    intervals = build_intervals(raw_tsv, out_dir, chunksize, group_column, excluded)
    inc = intervals.loc[~intervals["excluded_from_formal"], ["media_code", "picture_id"]].dropna().drop_duplicates()
    included = set(inc["media_code"].astype(str)); media_picture_ids = dict(zip(inc["media_code"], inc["picture_id"].astype(int)))
    aoi_meta["picture_id"] = aoi_meta["media_code"].map(media_picture_ids).fillna(aoi_meta["picture_id"]); aoi_meta.to_csv(out_dir / "aoi_metadata.csv", index=False, encoding="utf-8-sig")
    sample, fix, sac, aoi_sample, p_trial, p_part, p_base = aggregate_chunks(raw_tsv, chunksize, aoi_meta, out_dir, group_column, baseline_media, included, media_picture_ids)
    trial = build_trial_metrics(sample, fix, sac, intervals, p_trial, p_part, p_base, baseline_media)
    aoi_long = build_aoi_long(trial, fix, aoi_sample, aoi_meta)
    class_wide = build_class_wide(trial, aoi_long)
    trial = trial.merge(class_wide, on=TRIAL_KEY, how="left", suffixes=("", "_class"))
    trial.to_csv(out_dir / "trial_metrics.csv", index=False, encoding="utf-8-sig")
    aoi_long.to_csv(out_dir / "aoi_metrics_long.csv", index=False, encoding="utf-8-sig")
    class_wide.to_csv(out_dir / "aoi_class_metrics_wide.csv", index=False, encoding="utf-8-sig")
    report = ["# Tobii raw-TSV extraction report", "", f"- Raw TSV: `{raw_tsv}`", f"- Raw columns: {len(columns)}", f"- Group column: `{group_column}`" if group_column else "- Group column: not found; participant_group=ALL was used.", f"- Baseline media code: `{baseline_media}`" if baseline_media else "- Baseline media code: not set.", f"- Image intervals: {len(intervals)}", f"- Formal trial rows: {len(trial)}", f"- Participants: {trial['participant'].nunique()}", f"- Media/images included: {trial['media_code'].nunique()}", f"- AOI definitions detected: {len(aoi_meta)}", f"- AOI metric rows: {len(aoi_long)}"]
    (out_dir / "extraction_report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Done. Outputs written to: {out_dir}")
    return out_dir


def launch_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk(); root.title("Tobii TSV Extractor"); root.geometry("760x310")
    raw, out, group, base, excl, status = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar(value="Select or paste a Tobii raw TSV path.")
    def browse_raw():
        p = filedialog.askopenfilename(title="Select Tobii raw TSV", filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")])
        if p: raw.set(p); out.set(out.get() or str(Path(p).parent / DEFAULT_OUTPUT_FOLDER_NAME))
    def browse_out():
        p = filedialog.askdirectory(title="Select output folder")
        if p: out.set(p)
    def run():
        try:
            status.set("Running..."); root.update_idletasks(); result = run_extraction(Path(raw.get()), Path(out.get()) if out.get() else None, 100_000, group.get() or None, base.get(), excl.get()); status.set(str(result)); messagebox.showinfo("Done", str(result))
        except Exception as exc:
            messagebox.showerror("Extraction failed", str(exc)); status.set("Failed")
    labels = [("Raw TSV path", raw, browse_raw), ("Output folder", out, browse_out), ("Group column", group, None), ("Baseline media code", base, None), ("Exclude media codes", excl, None)]
    for i, (lab, var, cmd) in enumerate(labels):
        tk.Label(root, text=lab).grid(row=i, column=0, sticky="w", padx=10, pady=6); tk.Entry(root, textvariable=var, width=78).grid(row=i, column=1, sticky="ew", padx=10, pady=6)
        if cmd: tk.Button(root, text="Browse", command=cmd).grid(row=i, column=2, padx=10, pady=6)
    tk.Button(root, text="Run Extraction", command=run, width=20).grid(row=5, column=1, sticky="w", padx=10, pady=6); tk.Label(root, textvariable=status, wraplength=690).grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=6)
    root.columnconfigure(1, weight=1); root.mainloop(); return 0


def main() -> int:
    args = parse_args()
    if args.gui or args.raw_tsv is None:
        return launch_gui()
    run_extraction(args.raw_tsv, args.output_dir, args.chunksize, args.group_column, args.baseline_media_code, args.exclude_media_codes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
