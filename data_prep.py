"""Data preparation and input-analysis utilities for the IE 304 hospital simulation.

This module provides pure, reusable pandas functions that clean the raw SQL
export (Baltalimani_Data_2025.xlsx) and extract the variables needed to
parametrize the SimPy model. Nothing here touches the filesystem except
``load_raw`` (and ``fit_distributions`` which is a pure computation).

The top-level entry point is :func:`load_and_clean`, which chains every
cleaning step and returns a tidy ``pandas.DataFrame`` together with a
``CleaningLog`` that captures how many rows / values each step affected.
The notebook consumes that log to render a transparent data-quality report
for Section 1.3 of the IE 304 report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
from scipy import stats


RAW_TIME_COLUMNS = [
    "RANDEVU_BASLAMA_SAATI",
    "MUAYENE_KABUL_ZAMANI",
    "CAGRILMA_ZAMANI",
    "TETKIK_ISTEK_SAATI",
    "CEKIM_ZAMANI",
    "MUAYENE_SONLANDIRMA_ZAMANI",
]

DEPARTMENT_SHORT_NAMES: dict[str, str] = {
    "Erişkin Kalça‑Diz Hastalıkları ve Eklem Protez Cerrahisi": "AdultHipKnee",
    "Artroskopi ve Spor Cer. Omuz Hastalık": "ShoulderSports",
    "Çocuk Ortopedisi ve Deformite Cerrahisi": "ChildOrtho",
    "Diz, Menisküs bağ ve kıkırdak Yaralanmaları Eklem Protezi Cerrahisi": "KneeMeniscus",
    "Kemik Eğriliği, Boy Uzatma ve Deformite": "BoneDeformity",
    "Kemik Kisti Hastalıkları": "BoneCyst",
    "Omurga Cerrahisi": "Spine",
    "Tümör Kemik ve Yumuşak Doku Tümörleri": "Tumor",
    "Kontrol Polikliniği": "Control",
}

SCOLIOSIS_ROOM_SUFFIX = 160
STANDING_ROOM_SUFFIX = 31
LAYING_ROOM_SUFFIX = 32

LATE_ARRIVAL_CUTOFF_HOUR = 16
APPOINTMENT_DEVIATION_HOURS = 1.0

# Clinic policy overrides after time-based :func:`classify_walkin_vs_appointment`.
# Tumor accepts walk-ins alongside appointments — we do **not** force a single type there.
APPOINTMENT_ONLY_DEPARTMENTS: frozenset[str] = frozenset({"ChildOrtho"})
WALKIN_ONLY_DEPARTMENTS: frozenset[str] = frozenset({"Control"})

# Doctors whose primary department is fixed by clinic operations (not only the specialty CSV).
DOCTOR_PRIMARY_DEPARTMENT_OVERRIDES: dict[str, str] = {
    "BERKAY DOĞAN": "Control",
}

SECONDARY_MIN_MINUTES = 2.0
SECONDARY_MAX_MINUTES = 10.0

# Tukey IQR rule for outlier removal before distribution fitting
DEFAULT_IQR_FACTOR = 1.5

# Max consecutive ``CEKIM_ZAMANI`` gap (minutes) treated as back-to-back service;
# larger gaps are idle / lunch and do not define per-row imaging service.
XRAY_INTERDEPARTURE_MAX_MINUTES = 25.0


@dataclass
class CleaningLog:
    """Audit trail for every cleaning step.

    Every cleaner appends a ``{step, before, after, dropped, note}`` entry so
    the notebook can reproduce a before/after table without re-running the
    pipeline.
    """

    entries: list[dict] = field(default_factory=list)

    def record(self, step: str, before: int, after: int, note: str = "") -> None:
        self.entries.append(
            {
                "step": step,
                "rows_before": before,
                "rows_after": after,
                "delta": before - after,
                "note": note,
            }
        )

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.entries)


def _combine_date_time(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    """Combine a date column with a HH:MM:SS string into a full datetime.

    The source Excel stores the appointment date in ``GIRIS_TARIHI`` and all
    event clocks as standalone time strings, so we have to splice them back
    together before we can do arithmetic.
    """

    date_str = pd.to_datetime(date_series, errors="coerce").dt.strftime("%Y-%m-%d")
    time_str = time_series.astype("string").str.strip()
    combined = date_str.str.cat(time_str, sep=" ", na_rep="NaT")
    return pd.to_datetime(combined, format="%Y-%m-%d %H:%M:%S", errors="coerce")


def load_doctor_department_mapping(
    csv_path: str,
    short_names: Mapping[str, str] | None = DEPARTMENT_SHORT_NAMES,
) -> dict[str, list[str]]:
    """Build a ``{DOKTOR_ADI -> [department, ...]}`` dict from the specialty CSV.

    A doctor can appear in more than one specialty (e.g. AHMET KOCABIYIK
    practises both Adult Hip-Knee surgery and Bone Deformity surgery). We
    keep **every** occurrence so downstream code can decide whether to use a
    primary specialty, explode visits per specialty, or aggregate differently.
    Order is preserved from the CSV, duplicates are dropped, and doctors
    without any specialty (e.g. BERKAY DOĞAN in the raw file) map to
    ``["Unknown"]`` so they still appear in the dataset for arrival-rate
    analysis.
    """

    mapping_df = pd.read_csv(csv_path, encoding="utf-8")
    mapping_df.columns = [c.strip() for c in mapping_df.columns]
    doctor_col, dept_col = mapping_df.columns[0], mapping_df.columns[1]
    mapping_df[doctor_col] = mapping_df[doctor_col].astype("string").str.strip()
    mapping_df[dept_col] = mapping_df[dept_col].astype("string").str.strip()

    result: dict[str, list[str]] = {}
    for _, row in mapping_df.iterrows():
        doctor = row[doctor_col]
        dept = row[dept_col]
        if not doctor or pd.isna(doctor):
            continue
        if not dept or pd.isna(dept) or dept == "":
            dept_value = "Unknown"
        else:
            dept_value = short_names.get(dept, dept) if short_names else dept
        bucket = result.setdefault(doctor, [])
        if dept_value not in bucket:
            bucket.append(dept_value)
    return result


def primary_department_mapping(
    all_mapping: Mapping[str, list[str]],
) -> dict[str, str]:
    """Collapse a multi-specialty mapping to a single "primary" department.

    The primary is the first specialty that appears in the CSV for each
    doctor, which mirrors how the clinic keeps a "home room" per physician.
    This is what :func:`map_department` uses to produce the single-valued
    ``department`` column needed for routing probabilities and per-doctor
    resource sizing.
    """

    return {doctor: depts[0] for doctor, depts in all_mapping.items() if depts}


def load_raw(path: str) -> pd.DataFrame:
    """Load the raw workbook and convert the 6 time columns to datetime.

    ``GIRIS_TARIHI`` already arrives as a pandas datetime, but the six event
    times (``RANDEVU_BASLAMA_SAATI`` ... ``MUAYENE_SONLANDIRMA_ZAMANI``) are
    plain ``HH:MM:SS`` strings. We combine them with ``GIRIS_TARIHI`` so every
    timestamp becomes comparable on a single axis.
    """

    df = pd.read_excel(path)
    df["GIRIS_TARIHI"] = pd.to_datetime(df["GIRIS_TARIHI"], errors="coerce")
    for col in RAW_TIME_COLUMNS:
        df[col] = _combine_date_time(df["GIRIS_TARIHI"], df[col])
    return df


def _rontgen_room_missing(series: pd.Series) -> pd.Series:
    """True where ``RONTGEN_ODA_NO`` is null, blank, or non-numeric garbage."""

    num = pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip()
    text_blank = text.isna() | (text == "")
    return text_blank & num.isna()


def drop_cekim_without_rontgen_room(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Drop rows that have an imaging timestamp but no X-ray room number."""

    before = len(df)
    bad = df["CEKIM_ZAMANI"].notna() & _rontgen_room_missing(df["RONTGEN_ODA_NO"])
    cleaned = df.loc[~bad].copy()

    if log is not None:
        log.record(
            "drop_cekim_without_rontgen_room",
            before,
            len(cleaned),
            note="Removed rows with CEKIM_ZAMANI set but RONTGEN_ODA_NO missing.",
        )
    return cleaned


def drop_tetkik_without_muayene_kabul(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Drop rows with an X-ray request time but no exam-accept timestamp."""

    before = len(df)
    bad = df["TETKIK_ISTEK_SAATI"].notna() & df["MUAYENE_KABUL_ZAMANI"].isna()
    cleaned = df.loc[~bad].copy()

    if log is not None:
        log.record(
            "drop_tetkik_without_muayene_kabul",
            before,
            len(cleaned),
            note="Removed rows with TETKIK_ISTEK_SAATI set but MUAYENE_KABUL_ZAMANI missing.",
        )
    return cleaned


def consolidate_xray_duplicates(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Collapse multi-angle X-ray rows into a single patient visit.

    Each X-ray shot (e.g. AP + lateral) writes a new SQL row even though it is
    the same patient appointment. We group by ``(TC_KIMLIK_NO, GIRIS_TARIHI,
    DOKTOR_ADI)`` and aggregate:

    - start-of-process times (request, call, exam accept, first shot) -> min
    - end-of-process time (examination close) -> max
    - descriptive columns -> first
    """

    before = len(df)
    group_keys = ["TC_KIMLIK_NO", "GIRIS_TARIHI", "DOKTOR_ADI"]

    agg_spec: dict[str, str] = {
        "HASTA_ADI_SOYADI": "first",
        "CINSIYET": "first",
        "DOGUM_YILI": "first",
        "RANDEVU_BASLAMA_SAATI": "min",
        "MUAYENE_KABUL_ZAMANI": "min",
        "CAGRILMA_ZAMANI": "min",
        "TETKIK_ISTEK_SAATI": "min",
        "CEKIM_ZAMANI": "min",
        "RONTGEN_ODA_NO": "first",
        "MUAYENE_SONLANDIRMA_ZAMANI": "max",
    }
    consolidated = df.groupby(group_keys, as_index=False, dropna=False).agg(agg_spec)

    if log is not None:
        log.record(
            "consolidate_xray_duplicates",
            before,
            len(consolidated),
            note="Multi-angle X-ray shots collapsed to one visit per (patient, day, doctor).",
        )
    return consolidated


def drop_room_160(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Remove scoliosis-only X-ray records (room 160 is in a different building)."""

    before = len(df)
    room = pd.to_numeric(df["RONTGEN_ODA_NO"], errors="coerce")
    scoliosis_mask = room.notna() & (room.mod(1000).fillna(-1).astype("int64") == SCOLIOSIS_ROOM_SUFFIX)
    cleaned = df.loc[~scoliosis_mask].copy()

    if log is not None:
        log.record(
            "drop_room_160",
            before,
            len(cleaned),
            note=f"Removed {scoliosis_mask.sum()} scoliosis rows (room suffix {SCOLIOSIS_ROOM_SUFFIX}).",
        )
    return cleaned


def flag_call_time_anomaly(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Mask ``CAGRILMA_ZAMANI`` values that happened *after* the exam started.

    The hospital UI overwrites the call time when a patient is re-called after
    an X-ray, so some rows show ``CAGRILMA_ZAMANI > MUAYENE_KABUL_ZAMANI``.
    Those values are not a real "first call" and would yield negative waiting
    times if used naively. We keep the row but blank the suspicious value.
    """

    df = df.copy()
    valid = df["CAGRILMA_ZAMANI"].notna() & df["MUAYENE_KABUL_ZAMANI"].notna()
    anomaly = valid & (df["CAGRILMA_ZAMANI"] > df["MUAYENE_KABUL_ZAMANI"])

    df["call_time_valid"] = ~anomaly
    df.loc[anomaly, "CAGRILMA_ZAMANI"] = pd.NaT

    if log is not None:
        log.record(
            "flag_call_time_anomaly",
            len(df),
            len(df),
            note=f"Masked {int(anomaly.sum())} call-time values that were overwritten after X-ray.",
        )
    return df


def flag_open_case(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Mark rows whose examination was never formally closed.

    Open cases still contribute valid information for arrival rates and X-ray
    routing, so we only tag them rather than drop them.
    """

    df = df.copy()
    df["case_closed"] = df["MUAYENE_SONLANDIRMA_ZAMANI"].notna()

    if log is not None:
        open_cnt = int((~df["case_closed"]).sum())
        log.record(
            "flag_open_case",
            len(df),
            len(df),
            note=f"Flagged {open_cnt} open cases (no examination end time). Kept for arrival/routing stats.",
        )
    return df


def _to_minutes(delta: pd.Series) -> pd.Series:
    """Convert a timedelta series to float minutes, with negatives becoming NaN."""

    minutes = delta.dt.total_seconds() / 60.0
    return minutes.where(minutes >= 0)


def add_derived_columns(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Derive the duration variables we care about, in minutes.

    The first-exam duration is split by routing path so the SimPy model can
    sample the right service distribution per branch:

    - ``initial_screening_time``: **X-ray path only** — from accept-into-exam
      (``MUAYENE_KABUL_ZAMANI``) until the doctor asks for an X-ray
      (``TETKIK_ISTEK_SAATI``). NaN for patients without an X-ray request.
    - ``single_screening_time``: **no-X-ray path only** — from accept-into-exam
      until either the case closes (``MUAYENE_SONLANDIRMA_ZAMANI``) or the next
      patient is admitted on the same ``(GIRIS_TARIHI, DOKTOR_ADI)``, whichever
      comes first. The next-patient fallback treats each doctor as a
      single-server queue (per the IE 304 modelling rule). NaN for patients
      with an X-ray request.
    - ``xray_wait_time``: total minutes from X-ray request to first shot
      (**queue wait + imaging service**). See :func:`add_xray_wait_decomposed`
      for ``xray_queue_wait_time`` and ``xray_service_time_implied``.
    - ``secondary_screening_time``: from the *second* call (``CAGRILMA_ZAMANI``)
      until close. Per the updated plan we isolate the ``[2, 10]`` minute
      window so we are measuring the real post-X-ray doctor contact and not
      picking up overwritten-call artefacts.
    - ``total_system_time``: end-to-end time in the system.

    After :func:`drop_impossible_durations`,
    :func:`mask_initial_screening_iqr_outliers` masks Tukey-IQR outliers on
    ``initial_screening_time`` and ``single_screening_time`` separately so each
    branch's outlier fence is computed from its own distribution.
    """

    df = df.copy()
    df = df.sort_values(["GIRIS_TARIHI", "MUAYENE_KABUL_ZAMANI"]).reset_index(drop=True)
    negative_counts = {}

    df["NEXT_PATIENT_KABUL"] = (
        df.groupby(["GIRIS_TARIHI", "DOKTOR_ADI"])["MUAYENE_KABUL_ZAMANI"].shift(-1)
    )

    has_xray = df["TETKIK_ISTEK_SAATI"].notna()

    # X-ray path: end timestamp is the X-ray request itself.
    initial_xray = df["TETKIK_ISTEK_SAATI"] - df["MUAYENE_KABUL_ZAMANI"]
    initial_xray_min = _to_minutes(initial_xray)
    df["initial_screening_time"] = initial_xray_min.where(has_xray)
    negative_counts["initial_screening_time"] = int(
        (initial_xray.dt.total_seconds() < 0).sum()
    )

    # No-X-ray path: end timestamp is the case-close, falling back to the next
    # admit on the same doctor/day when MUAYENE_SONLANDIRMA_ZAMANI is missing.
    single_end = df["MUAYENE_SONLANDIRMA_ZAMANI"].fillna(df["NEXT_PATIENT_KABUL"])
    single = single_end - df["MUAYENE_KABUL_ZAMANI"]
    single_min = _to_minutes(single)
    df["single_screening_time"] = single_min.where(~has_xray)
    negative_counts["single_screening_time"] = int(
        ((~has_xray) & (single.dt.total_seconds() < 0)).sum()
    )

    xray_wait = df["CEKIM_ZAMANI"] - df["TETKIK_ISTEK_SAATI"]
    df["xray_wait_time"] = _to_minutes(xray_wait)
    negative_counts["xray_wait_time"] = int((xray_wait.dt.total_seconds() < 0).sum())

    secondary = df["MUAYENE_SONLANDIRMA_ZAMANI"] - df["CAGRILMA_ZAMANI"]
    secondary_min = _to_minutes(secondary)
    in_window = secondary_min.between(SECONDARY_MIN_MINUTES, SECONDARY_MAX_MINUTES)
    df["secondary_screening_time"] = secondary_min.where(in_window)
    negative_counts["secondary_screening_time"] = int((secondary.dt.total_seconds() < 0).sum())

    total = df["MUAYENE_SONLANDIRMA_ZAMANI"] - df["MUAYENE_KABUL_ZAMANI"]
    df["total_system_time"] = _to_minutes(total)
    negative_counts["total_system_time"] = int((total.dt.total_seconds() < 0).sum())

    if log is not None:
        note = ", ".join(f"{k}: {v} negatives -> NaN" for k, v in negative_counts.items())
        log.record("add_derived_columns", len(df), len(df), note=note)
    return add_xray_wait_decomposed(df, log=log)


def add_xray_wait_decomposed(
    df: pd.DataFrame,
    log: CleaningLog | None = None,
    max_gap_minutes: float = XRAY_INTERDEPARTURE_MAX_MINUTES,
) -> pd.DataFrame:
    """Split request-to-shot time into queue wait vs implied imaging service.

    ``CEKIM_ZAMANI - TETKIK_ISTEK_SAATI`` equals waiting (queue + walk) plus
    time the modality spends on this patient's imaging. Following the same
    consecutive-shot logic as :func:`xray_interdeparture_times`, the gap from
    the previous ``CEKIM_ZAMANI`` to this row's shot—within
    ``(xray_room_type, day)`` and with ``0 < gap <= max_gap_minutes``—is taken
    as **this row's** implied service minutes. Then
    ``xray_queue_wait_time ≈ xray_wait_time - xray_service_time_implied``.

    The first shot in a daily chain (or any gap above the threshold) leaves
    ``xray_service_time_implied`` as NaN and therefore ``xray_queue_wait_time``
    as NaN. Requires ``xray_room_type`` from :func:`tag_xray_room`.
    """

    df = df.copy()
    df["xray_service_time_implied"] = np.nan
    df["xray_queue_wait_time"] = np.nan

    if "xray_room_type" not in df.columns:
        if log is not None:
            log.record(
                "add_xray_wait_decomposed",
                len(df),
                len(df),
                note="skipped: no xray_room_type column",
            )
        return df

    sel = (
        df["TETKIK_ISTEK_SAATI"].notna()
        & df["CEKIM_ZAMANI"].notna()
        & df["xray_room_type"].isin(["standing", "laying"])
    )
    if not sel.any():
        if log is not None:
            log.record(
                "add_xray_wait_decomposed",
                len(df),
                len(df),
                note="no rows with tetkik+cekim+standing/laying",
            )
        return df

    sub = df.loc[sel].copy()
    sub["_d"] = sub["CEKIM_ZAMANI"].dt.date
    sub = sub.sort_values(["xray_room_type", "_d", "CEKIM_ZAMANI"])
    prev_cekim = sub.groupby(["xray_room_type", "_d"], sort=False)["CEKIM_ZAMANI"].shift(1)
    gap_min = (sub["CEKIM_ZAMANI"] - prev_cekim).dt.total_seconds() / 60.0
    valid = (gap_min > 0) & (gap_min <= max_gap_minutes) & prev_cekim.notna()
    implied = np.where(valid.to_numpy(), gap_min.to_numpy(), np.nan)

    tot = (sub["CEKIM_ZAMANI"] - sub["TETKIK_ISTEK_SAATI"]).dt.total_seconds() / 60.0
    tot = np.where(tot >= 0, tot, np.nan)
    queue = tot - implied
    queue = np.where(
        np.isfinite(implied) & np.isfinite(tot) & (queue >= 0),
        queue,
        np.nan,
    )

    df.loc[sub.index, "xray_service_time_implied"] = implied
    df.loc[sub.index, "xray_queue_wait_time"] = queue

    if log is not None:
        n_implied = int(np.isfinite(implied).sum())
        n_queue = int(np.isfinite(queue).sum())
        log.record(
            "add_xray_wait_decomposed",
            len(df),
            len(df),
            note=(
                f"implied service: {n_implied} rows; queue wait: {n_queue} rows "
                f"(max_gap={max_gap_minutes} min)"
            ),
        )
    return df


def drop_impossible_durations(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Cap extreme outliers at 3x the 99th percentile for each duration.

    Values beyond that threshold are almost always data-entry errors (e.g. a
    case left open overnight). We mask them as NaN rather than deleting the
    row, so the patient still counts for arrivals and routing.
    """

    df = df.copy()
    duration_cols = [
        "initial_screening_time",
        "single_screening_time",
        "xray_wait_time",
        "xray_service_time_implied",
        "xray_queue_wait_time",
        "secondary_screening_time",
        "total_system_time",
    ]
    masked = {}
    for col in duration_cols:
        if col not in df.columns:
            continue
        series = df[col]
        if series.notna().sum() == 0:
            continue
        cutoff = float(series.quantile(0.99) * 3)
        mask = series > cutoff
        masked[col] = {"cutoff_minutes": round(cutoff, 2), "masked": int(mask.sum())}
        df.loc[mask, col] = np.nan

    if log is not None:
        note = "; ".join(f"{c}: >{v['cutoff_minutes']}m -> NaN ({v['masked']} rows)" for c, v in masked.items())
        log.record("drop_impossible_durations", len(df), len(df), note=note)
    return df


def mask_initial_screening_iqr_outliers(
    df: pd.DataFrame,
    log: CleaningLog | None = None,
    *,
    factor: float = DEFAULT_IQR_FACTOR,
) -> pd.DataFrame:
    """Set first-exam durations to NaN outside Tukey IQR fences.

    Applies independent fences to ``initial_screening_time`` (X-ray path) and
    ``single_screening_time`` (no-X-ray path) so each branch's outlier cutoff
    reflects its own distribution rather than a pooled one. Fences use every
    finite, non-negative duration (zeros included). Runs after
    :func:`drop_impossible_durations` so gross data-entry spikes are already
    removed before quartiles are computed.
    """

    df = df.copy()
    notes: list[str] = []
    for col in ("initial_screening_time", "single_screening_time"):
        if col not in df.columns:
            continue
        arr = df[col].to_numpy(dtype=float)
        valid = arr[np.isfinite(arr) & (arr >= 0)]
        n_in = int(valid.size)
        if n_in < 4:
            notes.append(f"{col}: skipped (n={n_in}<4)")
            continue

        q1, q3 = np.quantile(valid, [0.25, 0.75])
        iqr = float(q3 - q1)
        lower = max(float(q1 - factor * iqr), 0.0)
        upper = float(q3 + factor * iqr)
        outside = np.isfinite(arr) & ((arr < lower) | (arr > upper))
        n_mask = int(outside.sum())
        df.loc[outside, col] = np.nan
        notes.append(
            f"{col}: fence [{lower:.4g}, {upper:.4g}] min "
            f"(factor={factor}); masked {n_mask} of {n_in}"
        )

    if log is not None:
        log.record(
            "mask_initial_screening_iqr_outliers",
            len(df),
            len(df),
            note="; ".join(notes) if notes else "no eligible columns",
        )
    return df


def classify_walkin_vs_appointment(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Label each visit as ``walkin`` or ``appointment``.

    Rules (in order, first match wins):

    1. Missing ``RANDEVU_BASLAMA_SAATI`` -> walk-in.
    2. ``MUAYENE_KABUL_ZAMANI`` at or after 16:00 -> walk-in (late-arrival rule
       from ``.cursor/master.mdc``).
    3. Temporal deviation between scheduled and actual start beyond one hour
       in *either* direction -> walk-in (slotted into an open doctor).
    4. Otherwise -> appointment.

    If ``MUAYENE_KABUL_ZAMANI`` is missing we default to appointment because
    the patient was registered on a schedule but never seen.
    """

    df = df.copy()
    has_accept = df["MUAYENE_KABUL_ZAMANI"].notna()

    delta_hours = (
        (df["MUAYENE_KABUL_ZAMANI"] - df["RANDEVU_BASLAMA_SAATI"]).dt.total_seconds() / 3600.0
    )
    late_hour = has_accept & (df["MUAYENE_KABUL_ZAMANI"].dt.hour >= LATE_ARRIVAL_CUTOFF_HOUR)
    no_appt = df["RANDEVU_BASLAMA_SAATI"].isna()
    deviation = has_accept & (delta_hours.abs() >= APPOINTMENT_DEVIATION_HOURS)

    walkin_mask = no_appt | late_hour | deviation
    df["patient_type"] = np.where(walkin_mask, "walkin", "appointment")
    df["appointment_delta_hours"] = delta_hours

    if log is not None:
        counts = df["patient_type"].value_counts().to_dict()
        log.record(
            "classify_walkin_vs_appointment",
            len(df),
            len(df),
            note=f"patient_type counts: {counts}",
        )
    return df


def apply_department_patient_type_rules(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Apply department-level walk-in vs appointment policy on top of time-based labels.

    - **ChildOrtho:** appointment-only polyclinic — every visit is ``appointment``.
    - **Control:** kontrol / follow-up — every visit is ``walkin``.

    **Tumor** is intentionally excluded: the service accepts walk-ins but also
    scheduled patients, so :func:`classify_walkin_vs_appointment` keeps the
    time-based split.

    Requires ``department`` (from :func:`map_department`) and ``patient_type``.
    """

    df = df.copy()
    if "department" not in df.columns or "patient_type" not in df.columns:
        raise KeyError("apply_department_patient_type_rules expects 'department' and 'patient_type' columns")

    appt_mask = df["department"].isin(APPOINTMENT_ONLY_DEPARTMENTS)
    walk_mask = df["department"].isin(WALKIN_ONLY_DEPARTMENTS)
    if (appt_mask & walk_mask).any():
        bad = df.loc[appt_mask & walk_mask, "department"].unique().tolist()
        raise ValueError(f"Department(s) cannot be both appointment-only and walk-in-only: {bad}")

    before = df["patient_type"].copy()
    df.loc[appt_mask, "patient_type"] = "appointment"
    df.loc[walk_mask, "patient_type"] = "walkin"

    n_child = int(appt_mask.sum())
    n_control = int(walk_mask.sum())
    relabel_to_appt = int((appt_mask & (before != "appointment")).sum())
    relabel_to_walk = int((walk_mask & (before != "walkin")).sum())

    if log is not None:
        log.record(
            "apply_department_patient_type_rules",
            len(df),
            len(df),
            note=(
                f"ChildOrtho appointment policy: {n_child} rows ({relabel_to_appt} relabelled); "
                f"Control walk-in policy: {n_control} rows ({relabel_to_walk} relabelled)."
            ),
        )
    return df


def map_department(
    df: pd.DataFrame,
    doctor_to_department: Mapping[str, str] | Mapping[str, list[str]] | None = None,
    log: CleaningLog | None = None,
) -> pd.DataFrame:
    """Attach ``department`` + ``departments_all`` columns to every row.

    Accepts either:

    - ``{doctor: department}`` - legacy single-specialty mapping
    - ``{doctor: [department, ...]}`` - multi-specialty mapping returned by
      :func:`load_doctor_department_mapping`

    For multi-specialty mappings we expose two columns: ``department`` is the
    **primary** specialty (first entry in the CSV, used for routing and
    resource sizing), and ``departments_all`` is the pipe-joined list of every
    specialty the doctor practises (useful for per-specialty reporting).
    """

    df = df.copy()
    if doctor_to_department:
        sample = next(iter(doctor_to_department.values()))
        if isinstance(sample, (list, tuple)):
            full_mapping: dict[str, list[str]] = {
                k: list(v) for k, v in doctor_to_department.items()
            }
            primary_mapping = {k: v[0] for k, v in full_mapping.items() if v}
            df["department"] = df["DOKTOR_ADI"].map(primary_mapping).fillna("Unknown")
            df["departments_all"] = (
                df["DOKTOR_ADI"]
                .map(lambda d: "|".join(full_mapping.get(d, ["Unknown"])))
                .fillna("Unknown")
            )
        else:
            df["department"] = df["DOKTOR_ADI"].map(doctor_to_department).fillna("Unknown")
            df["departments_all"] = df["department"]
    else:
        df["department"] = df["DOKTOR_ADI"]
        df["departments_all"] = df["DOKTOR_ADI"]

    for doc_name, dept_override in DOCTOR_PRIMARY_DEPARTMENT_OVERRIDES.items():
        match = df["DOKTOR_ADI"].astype("string").str.strip() == doc_name
        if match.any():
            df.loc[match, "department"] = dept_override
            df.loc[match, "departments_all"] = dept_override

    if log is not None:
        dept_counts = df["department"].value_counts().head(10).to_dict()
        multi_count = int((df["departments_all"].str.count(r"\|") > 0).sum())
        log.record(
            "map_department",
            len(df),
            len(df),
            note=f"Top primary departments: {dept_counts}; rows whose doctor spans >1 specialty: {multi_count}",
        )
    return df


def anonymize_doctor(df: pd.DataFrame, log: CleaningLog | None = None) -> pd.DataFrame:
    """Collapse the head-doctor + assistants into one resource per department.

    The master rules explicitly forbid modelling the doctor/assistant
    hierarchy, so the simulation sees a single resource (named after the
    department) regardless of which assistant actually examined the patient.
    """

    df = df.copy()
    df["doctor_resource"] = df["department"]

    if log is not None:
        log.record(
            "anonymize_doctor",
            len(df),
            len(df),
            note="Collapsed doctor + assistants into one resource per department.",
        )
    return df


def tag_xray_room(df: pd.DataFrame) -> pd.DataFrame:
    """Tag each X-ray record as ``standing``, ``laying``, or ``other``.

    Room suffix ``31`` is the standing bucky, ``32`` is the laying bucky. We
    use the suffix (last three digits) instead of the full room id so the
    mapping survives any schema rename.
    """

    df = df.copy()
    room = pd.to_numeric(df["RONTGEN_ODA_NO"], errors="coerce")
    suffix = room.mod(1000)
    df["xray_room_type"] = np.select(
        [suffix == STANDING_ROOM_SUFFIX, suffix == LAYING_ROOM_SUFFIX],
        ["standing", "laying"],
        default=np.where(room.isna(), "none", "other"),
    )
    return df


def load_and_clean(
    path: str,
    doctor_to_department: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, CleaningLog]:
    """Run the full cleaning pipeline and return (clean_df, log)."""

    log = CleaningLog()
    df = load_raw(path)
    log.record("load_raw", len(df), len(df), note=f"Loaded {len(df)} raw rows from {path}")

    df = drop_cekim_without_rontgen_room(df, log)
    df = drop_tetkik_without_muayene_kabul(df, log)
    df = consolidate_xray_duplicates(df, log)
    df = drop_room_160(df, log)
    df = flag_call_time_anomaly(df, log)
    df = flag_open_case(df, log)
    df = tag_xray_room(df)
    df = add_derived_columns(df, log)
    df = drop_impossible_durations(df, log)
    df = mask_initial_screening_iqr_outliers(df, log=log)
    df = classify_walkin_vs_appointment(df, log)
    df = map_department(df, doctor_to_department, log)
    df = apply_department_patient_type_rules(df, log)
    df = anonymize_doctor(df, log)
    return df, log


def xray_interdeparture_times(
    df: pd.DataFrame,
    max_gap_minutes: float = XRAY_INTERDEPARTURE_MAX_MINUTES,
) -> pd.DataFrame:
    """Consecutive-departure gaps at the X-ray modality, tagged as service vs idle.

    Queueing argument: while the X-ray device is busy back-to-back, the time
    between two consecutive departures equals the service time of the second
    patient. Gaps longer than ``max_gap_minutes`` indicate that the device
    went idle in between (no-one in queue), so those gaps are **idle time**
    and do not belong to the service-time sample.

    Returns a DataFrame with columns:
    ``_date``, ``xray_room_type``, ``CEKIM_ZAMANI``, ``interdeparture_minutes``,
    ``is_service_sample`` (``True`` iff ``0 < gap <= max_gap_minutes``).
    The raw gaps are preserved so the notebook can plot the full histogram
    and visually defend the 25-minute threshold.
    """

    keep_rooms = ("standing", "laying")
    source = df.dropna(subset=["CEKIM_ZAMANI"]).copy()
    source = source[source["xray_room_type"].isin(keep_rooms)]
    source["_date"] = source["CEKIM_ZAMANI"].dt.date
    source = source.sort_values(["xray_room_type", "_date", "CEKIM_ZAMANI"])
    source["interdeparture_minutes"] = (
        source.groupby(["xray_room_type", "_date"])["CEKIM_ZAMANI"]
        .diff()
        .dt.total_seconds()
        .div(60.0)
    )
    source = source.dropna(subset=["interdeparture_minutes"])
    source["is_service_sample"] = (source["interdeparture_minutes"] > 0) & (
        source["interdeparture_minutes"] <= max_gap_minutes
    )
    return source[
        ["_date", "xray_room_type", "CEKIM_ZAMANI", "interdeparture_minutes", "is_service_sample"]
    ].reset_index(drop=True)


def xray_samples_by_room(
    df: pd.DataFrame,
    max_gap_minutes: float = XRAY_INTERDEPARTURE_MAX_MINUTES,
) -> dict[str, np.ndarray]:
    """Return per-room X-ray **service-time** samples (minutes), estimated as
    consecutive-departure gaps on the same modality and same day.

    Filter rule (inherited from :func:`xray_interdeparture_times`):
    ``0 < gap <= max_gap_minutes``. Gaps > ``max_gap_minutes`` are treated
    as idle time and discarded from the service-time sample.
    """

    diffs = xray_interdeparture_times(df, max_gap_minutes=max_gap_minutes)
    kept = diffs[diffs["is_service_sample"]]
    out: dict[str, np.ndarray] = {}
    for room in ("standing", "laying"):
        out[room] = kept.loc[kept["xray_room_type"] == room, "interdeparture_minutes"].to_numpy()
    return out


def compute_routing_probabilities(df: pd.DataFrame) -> pd.DataFrame:
    """Per-department X-ray routing probabilities.

    - ``xray_probability``: share of a department's visits that are sent to
      the X-ray modality (``TETKIK_ISTEK_SAATI`` present).
    - ``prob_standing`` / ``prob_laying``: conditional on being sent to X-ray,
      share routed to the standing (room suffix 031) vs laying (032) bucky.
      Rooms tagged ``other`` or ``none`` are excluded from the denominator so
      ``prob_standing + prob_laying`` sums to 1 whenever either is positive.
    """

    grouped = df.groupby("department", dropna=False)
    total = grouped.size().rename("visits")
    xray = grouped["TETKIK_ISTEK_SAATI"].apply(lambda s: s.notna().sum()).rename("xray_visits")

    xray_rows = df.dropna(subset=["TETKIK_ISTEK_SAATI"])
    room_counts = (
        xray_rows.groupby(["department", "xray_room_type"], dropna=False)
        .size()
        .unstack(fill_value=0)
    )
    standing = room_counts.get("standing", pd.Series(0, index=room_counts.index)).rename("standing_visits")
    laying = room_counts.get("laying", pd.Series(0, index=room_counts.index)).rename("laying_visits")

    out = pd.concat([total, xray, standing, laying], axis=1).fillna(0)
    out[["visits", "xray_visits", "standing_visits", "laying_visits"]] = out[
        ["visits", "xray_visits", "standing_visits", "laying_visits"]
    ].astype("int64")
    out["xray_probability"] = out["xray_visits"] / out["visits"].replace(0, np.nan)
    denom = (out["standing_visits"] + out["laying_visits"]).replace(0, np.nan)
    out["prob_standing"] = out["standing_visits"] / denom
    out["prob_laying"] = out["laying_visits"] / denom
    return out.sort_values("visits", ascending=False)


def inter_arrival_times(
    df: pd.DataFrame,
    time_column: str,
    group_columns: Iterable[str] = ("department", "patient_type"),
) -> pd.DataFrame:
    """Compute inter-arrival times (minutes) within each group and date.

    We group by calendar day as well as the caller-provided keys, otherwise
    the gap between the last patient of day N and the first patient of day
    N+1 would contaminate the sample.
    """

    df = df.dropna(subset=[time_column]).copy()
    df["_date"] = df[time_column].dt.date
    sort_keys = list(group_columns) + ["_date", time_column]
    df = df.sort_values(sort_keys)
    group_cols = list(group_columns) + ["_date"]
    df["inter_arrival_minutes"] = (
        df.groupby(group_cols)[time_column].diff().dt.total_seconds() / 60.0
    )
    result = df.dropna(subset=["inter_arrival_minutes"]).copy()
    result = result[result["inter_arrival_minutes"] > 0]
    return result[list(group_columns) + ["inter_arrival_minutes"]]


DEFAULT_FIT_CANDIDATES: tuple[str, ...] = (
    "expon",
    "lognorm",
    "gamma",
    "weibull_min",
    "triang",
    "norm",
)


def _chi_square_gof(samples: np.ndarray, dist, params: tuple, n_bins: int = 10) -> tuple[float, float]:
    """Binned chi-square goodness-of-fit.

    Observed frequencies come from equal-probability bins based on the fitted
    CDF so every bin has the same expected count, which stabilises the test.
    """

    n = len(samples)
    if n < n_bins * 5:
        return float("nan"), float("nan")
    probs = np.linspace(0, 1, n_bins + 1)
    edges = dist.ppf(probs, *params)
    edges[0] = min(edges[0], samples.min()) - 1e-9
    edges[-1] = max(edges[-1], samples.max()) + 1e-9
    observed, _ = np.histogram(samples, bins=edges)
    expected = np.full(n_bins, n / n_bins)
    chi2 = float(((observed - expected) ** 2 / expected).sum())
    n_free_params = len(params)
    dof = max(n_bins - 1 - n_free_params, 1)
    p_value = float(stats.chi2.sf(chi2, dof))
    return chi2, p_value


def fit_distributions(
    samples: Iterable[float],
    candidates: Iterable[str] = DEFAULT_FIT_CANDIDATES,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Fit each candidate distribution and score it with K-S, Chi-square, AIC.

    Returns a tidy DataFrame ordered by "best first" where "best" means
    highest K-S p-value among the candidates that are *not* rejected at
    ``alpha``. AIC is used to break ties (lower is better). The caller picks
    a winner by inspecting ``result.iloc[0]`` or filtering on
    ``is_accepted``.
    """

    arr = np.asarray(list(samples), dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    rows = []
    if len(arr) < 30:
        return pd.DataFrame(
            columns=[
                "candidate",
                "params",
                "ks_stat",
                "ks_p",
                "chi2_stat",
                "chi2_p",
                "log_likelihood",
                "aic",
                "is_accepted",
                "n",
            ]
        )

    for name in candidates:
        dist = getattr(stats, name)
        try:
            params = dist.fit(arr)
            ks_stat, ks_p = stats.kstest(arr, name, args=params)
            log_lik = float(np.sum(dist.logpdf(arr, *params)))
            aic = 2 * len(params) - 2 * log_lik
            chi2_stat, chi2_p = _chi_square_gof(arr, dist, params)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "candidate": name,
                    "params": None,
                    "ks_stat": float("nan"),
                    "ks_p": float("nan"),
                    "chi2_stat": float("nan"),
                    "chi2_p": float("nan"),
                    "log_likelihood": float("nan"),
                    "aic": float("nan"),
                    "is_accepted": False,
                    "n": len(arr),
                    "error": str(exc),
                }
            )
            continue
        rows.append(
            {
                "candidate": name,
                "params": tuple(float(p) for p in params),
                "ks_stat": float(ks_stat),
                "ks_p": float(ks_p),
                "chi2_stat": chi2_stat,
                "chi2_p": chi2_p,
                "log_likelihood": log_lik,
                "aic": float(aic),
                "is_accepted": bool(ks_p >= alpha),
                "n": len(arr),
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result.sort_values(
        by=["is_accepted", "ks_p", "aic"], ascending=[False, False, True]
    ).reset_index(drop=True)
    return result


def pick_winner(fit_table: pd.DataFrame) -> dict | None:
    """Return the best-scoring candidate from a ``fit_distributions`` table."""

    if fit_table.empty:
        return None
    row = fit_table.iloc[0].to_dict()
    return {
        "dist": row["candidate"],
        "params": list(row["params"]) if row.get("params") else None,
        "ks_p": row["ks_p"],
        "chi2_p": row["chi2_p"],
        "aic": row["aic"],
        "n": int(row["n"]),
        "is_accepted": bool(row["is_accepted"]),
    }


def iqr_outlier_stats(
    samples: Iterable[float] | np.ndarray,
    factor: float = DEFAULT_IQR_FACTOR,
) -> dict:
    """Robust IQR (Tukey) bounds on the positive, finite part of the sample.

    Intervals are :math:`[Q_1 - f \\cdot IQR,\\ Q_3 + f \\cdot IQR]`
    (default *f* = 1.5). Used to report and filter outliers before
    :func:`fit_distributions` so that heavy tails from data-entry or rare
    clinical cases do not dominate the K-S fit.
    """

    arr = np.asarray(list(samples), dtype=float)
    valid = arr[np.isfinite(arr) & (arr > 0)]
    n_in = int(valid.size)
    if n_in < 4:
        return {
            "n_in": n_in,
            "n_outliers": 0,
            "q1": float("nan"),
            "q3": float("nan"),
            "iqr": float("nan"),
            "lower": float("nan"),
            "upper": float("nan"),
            "factor": float(factor),
        }
    q1, q3 = np.quantile(valid, [0.25, 0.75])
    iqr = q3 - q1
    lower = q1 - factor * iqr
    upper = q3 + factor * iqr
    lower = max(float(lower), 0.0)
    in_fence = (valid >= lower) & (valid <= upper)
    return {
        "n_in": n_in,
        "n_outliers": int(n_in - np.sum(in_fence)),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(iqr),
        "lower": float(lower),
        "upper": float(upper),
        "factor": float(factor),
    }


def apply_iqr_filter(
    samples: Iterable[float] | np.ndarray,
    factor: float = DEFAULT_IQR_FACTOR,
) -> tuple[np.ndarray, dict]:
    """Drop samples outside the IQR fence; return ``(kept, stats)``."""

    arr = np.asarray(list(samples), dtype=float)
    stats_dict = iqr_outlier_stats(arr, factor=factor)
    if stats_dict["n_in"] < 4 or not np.isfinite(stats_dict["lower"]):
        kept = arr[np.isfinite(arr) & (arr > 0)]
        n_pos = int((np.isfinite(arr) & (arr > 0)).sum())
        return kept, {**stats_dict, "n_after": int(kept.size), "n_before": n_pos}
    lo, hi = stats_dict["lower"], stats_dict["upper"]
    mask = np.isfinite(arr) & (arr > 0) & (arr >= lo) & (arr <= hi)
    kept = arr[mask]
    return kept, {
        **stats_dict,
        "n_before": int((np.isfinite(arr) & (arr > 0)).sum()),
        "n_after": int(kept.size),
    }
