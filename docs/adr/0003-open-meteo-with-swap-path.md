# 0003: Open-Meteo with a weather source boundary

Use Open-Meteo's ECMWF and GFS ensembles for the initial forecasts, behind a `WeatherSource` interface that returns forecast series and cost headers. The adapter validates units and preserves missing variables rather than substituting values, so rules can report when they cannot be evaluated. Open-Meteo's free tier is non-commercial, so commercial reuse requires a suitable plan or a replacement source such as the GEFS swap path; another source must satisfy the interface and its data contract.
