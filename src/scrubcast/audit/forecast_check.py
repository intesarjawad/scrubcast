"""Fixed-lead surface forecasts checked against station measurements."""

from datetime import date

from scrubcast.audit.proxy_check import (
    SPLIT_DATE,
    Evidence,
    measure,
    observation_metrics,
    precipitation_metrics,
)

FORECAST_START = date(2024, 3, 7)
FORECAST_LABEL = (
    "Deterministic surface forecasts from Open-Meteo's Previous Runs archive. "
    "Scrubcast's live board uses the ensembles; this checks the same models' surface forecasts "
    "at the site, not the ensemble spread, and covers only the wind and precipitation rules."
)


def forecast_check(rows: list[Evidence]) -> dict[str, object]:
    """Report paired skill only where the same launch has a climatological reference."""
    tables: list[dict[str, object]] = []
    for model in ("ecmwf", "gfs"):
        for lead in (24, 48, 72):
            for period in ("held_out", "development"):
                selected = [
                    row
                    for row in rows
                    if row.model == model
                    and row.lead_hours == lead
                    and row.net.date() >= FORECAST_START
                    and (row.net.date() >= SPLIT_DATE) == (period == "held_out")
                ]
                wind = observation_metrics(selected)
                wind["mae_skill"] = measure(
                    [
                        [row.wind_mps, row.observed_wind_mps, row.climatology_wind_mps]
                        for row in selected
                        if row.wind_mps is not None
                        and row.observed_wind_mps is not None
                        and row.climatology_wind_mps is not None
                    ],
                    "mae_skill",
                )
                verdicts = [
                    [float(value), float(row.analysis_wind_verdict)]
                    for row in selected
                    if row.analysis_wind_verdict is not None
                    and (value := row.verdicts.get("liftoff_wind")) is not None
                ]
                tables.append(
                    {
                        "model": model,
                        "lead_hours": lead,
                        "period": period,
                        "n": len(selected),
                        "missing_metar": sum(not row.observation_present for row in selected),
                        "wind": {key: value.model_dump(mode="json") for key, value in wind.items()},
                        "liftoff_wind": {
                            "n": len(verdicts),
                            "positives": sum(int(pair[1]) for pair in verdicts),
                            "agreement": measure(verdicts, "agreement").model_dump(mode="json"),
                        },
                        "precipitation": {
                            key: {
                                name: value.model_dump(mode="json")
                                for name, value in metrics.items()
                            }
                            for key, metrics in precipitation_metrics(selected).items()
                        },
                    }
                )
    return {"label": FORECAST_LABEL, "tables": tables}
