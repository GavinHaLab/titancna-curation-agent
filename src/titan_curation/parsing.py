"""Deterministic parsing of TITAN params.txt and segs.txt files."""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd


def parse_params(path: str) -> dict:
    text = open(path).read()

    def grab(pattern, cast=float, default=None):
        m = re.search(pattern, text)
        if not m:
            return default
        return cast(m.group(1).strip())

    normal_contam = grab(r"Normal contamination estimate:\s*([\d.]+)")
    ploidy = grab(r"Average tumour ploidy estimate:\s*([\d.]+)")
    loglik = grab(r"Log likelihood:\s*(-?[\d.]+)")
    sdbw_logr = grab(r"S_Dbw validity index \(LogRatio\):\s*([\d.]+)")
    sdbw_ar = grab(r"S_Dbw validity index \(AllelicRatio\):\s*([\d.]+)")
    sdbw_both = grab(r"S_Dbw validity index \(Both\):\s*([\d.]+)")

    prevalence_line = re.search(
        r"Clonal cluster cellular prevalence Z=(\d+):\s*([\d.\s]+)", text
    )
    if prevalence_line:
        z_requested = int(prevalence_line.group(1))
        prevalences = [float(x) for x in prevalence_line.group(2).split()]
    else:
        z_requested, prevalences = None, []

    return {
        "normal_contamination": normal_contam,
        "titan_purity": round(1 - normal_contam, 4) if normal_contam is not None else None,
        "ploidy": ploidy,
        "log_likelihood": loglik,
        "s_dbw_logratio": sdbw_logr,
        "s_dbw_allelicratio": sdbw_ar,
        "s_dbw_both": sdbw_both,
        "effective_num_clusters": len(prevalences),
        "cluster_cellular_prevalence": prevalences,
    }


def parse_segs(path: str, top_events_n: int = 8) -> dict:
    df = pd.read_csv(path, sep="\t")
    df["length_bp"] = df["End_Position.bp."] - df["Start_Position.bp."]
    total_bp = df["length_bp"].sum()

    neutral_mask = df["Corrected_Call"].isin(["NEUT"]) | (
        (df["Corrected_Call"] == "NLOH") & (df["Corrected_Copy_Number"] == 2)
    )
    altered_bp = df.loc[~neutral_mask, "length_bp"].sum()
    frac_altered = round(altered_bp / total_bp, 4) if total_bp else None

    subclonal_mask = df["Cellular_Prevalence"].apply(
        lambda v: isinstance(v, (int, float)) and pd.notna(v) and v < 0.999
    )
    subclonal_bp = df.loc[subclonal_mask, "length_bp"].sum()
    frac_subclonal = round(subclonal_bp / total_bp, 4) if total_bp else None

    num_segments = len(df)

    top_events = (
        df.loc[~neutral_mask]
        .sort_values("length_bp", ascending=False)
        .head(top_events_n)[[
            "Chromosome", "Start_Position.bp.", "End_Position.bp.", "length_bp",
            "Corrected_Call", "Corrected_Copy_Number", "Corrected_MajorCN",
            "Corrected_MinorCN", "Cellular_Prevalence",
        ]]
    )
    top_events_list = []
    for _, r in top_events.iterrows():
        top_events_list.append({
            "chr": r["Chromosome"],
            "start": int(r["Start_Position.bp."]),
            "end": int(r["End_Position.bp."]),
            "length_bp": int(r["length_bp"]),
            "call": r["Corrected_Call"],
            "copy_number": r["Corrected_Copy_Number"],
            "major_cn": r["Corrected_MajorCN"],
            "minor_cn": r["Corrected_MinorCN"],
            "cellular_prevalence": None if pd.isna(r["Cellular_Prevalence"]) else round(float(r["Cellular_Prevalence"]), 4),
        })

    call_counts = df["Corrected_Call"].value_counts().to_dict()

    return {
        "num_segments": num_segments,
        "fraction_genome_altered": frac_altered,
        "fraction_genome_subclonal": frac_subclonal,
        "call_state_segment_counts": call_counts,
        "top_events_by_length": top_events_list,
    }
