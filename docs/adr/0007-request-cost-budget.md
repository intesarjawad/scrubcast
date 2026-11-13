# 0007: Budget weather requests by cost

Plan and pace Open-Meteo requests in cost units, using the measured variable, member and forecast-day weighting, a daily budget of 7,500 units and a per-run budget of 1,875 units, with a 600-unit rolling minute limit. Prioritize Tier A points, then Tier B and Tier C, reuse shared forecast points, and retain the previous forecast when a request is deferred. Record response costs and discrepancies in the ledger; an upstream rate limit defers the point without retrying in that run, since shared runner IP limits can apply independently of this budget.
