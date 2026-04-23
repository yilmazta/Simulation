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
}

SCOLIOSIS_ROOM_SUFFIX = 160
STANDING_ROOM_SUFFIX = 31
LAYING_ROOM_SUFFIX = 32

LATE_ARRIVAL_CUTOFF_HOUR = 16
APPOINTMENT_DEVIATION_HOURS = 1.0

SECONDARY_MIN_MINUTES = 2.0
SECONDARY_MAX_MINUTES = 10.0


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
    """Derive the four duration variables we care about, in minutes.

    - ``initial_screening_time``: from accept-into-exam (``MUAYENE_KABUL_ZAMANI``)
      until the doctor either asks for an X-ray or closes the case.
    - ``xray_wait_time``: from X-ray request to first shot.
    - ``secondary_screening_time``: from the *second* call (``CAGRILMA_ZAMANI``)
      until close. Per the updated plan we isolate the ``[2, 10]`` minute
      window so we are measuring the real post-X-ray doctor contact and not
      picking up overwritten-call artefacts.
    - ``total_system_time``: end-to-end time in the system.
    """

    df = df.copy()
    negative_counts = {}

    xray_end_or_close = df["TETKIK_ISTEK_SAATI"].fillna(df["MUAYENE_SONLANDIRMA_ZAMANI"])
    initial = xray_end_or_close - df["MUAYENE_KABUL_ZAMANI"]
    df["initial_screening_time"] = _to_minutes(initial)
    negative_counts["initial_screening_time"] = int((initial.dt.total_seconds() < 0).sum())

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
        "xray_wait_time",
        "secondary_screening_time",
        "total_system_time",
    ]
    masked = {}
    for col in duration_cols:
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

    df = consolidate_xray_duplicates(df, log)
    df = drop_room_160(df, log)
    df = flag_call_time_anomaly(df, log)
    df = flag_open_case(df, log)
    df = add_derived_columns(df, log)
    df = drop_impossible_durations(df, log)
    df = classify_walkin_vs_appointment(df, log)
    df = map_department(df, doctor_to_department, log)
    df = anonymize_doctor(df, log)
    df = tag_xray_room(df)
    return df, log


def xray_samples_by_room(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Return ``{'standing': ..., 'laying': ...}`` X-ray durations in minutes.

    Only rows that actually took an X-ray (``xray_wait_time`` present) and
    whose room type is either ``standing`` or ``laying`` are kept, so the
    caller can fit the two distributions independently.
    """

    out: dict[str, np.ndarray] = {}
    with_xray = df.dropna(subset=["xray_wait_time"])
    for room in ("standing", "laying"):
        mask = with_xray["xray_room_type"] == room
        out[room] = with_xray.loc[mask, "xray_wait_time"].to_numpy()
    return out


def compute_routing_probabilities(df: pd.DataFrame) -> pd.DataFrame:
    """Per-department probability of being sent to the X-ray room."""

    grouped = df.groupby("department", dropna=False)
    total = grouped.size().rename("visits")
    xray = grouped["TETKIK_ISTEK_SAATI"].apply(lambda s: s.notna().sum()).rename("xray_visits")
    out = pd.concat([total, xray], axis=1)
    out["xray_probability"] = out["xray_visits"] / out["visits"]
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
