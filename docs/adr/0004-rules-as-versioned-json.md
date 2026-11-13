# 0004: Store rules as versioned JSON

Keep rule definitions, sources, thresholds, approximation notes, plot parameters and site and vehicle mappings in versioned JSON validated at the input boundary. Each threshold has one authoritative value, referenced by both evaluation and presentation, so a change can be reviewed and traced to the rule set version recorded with an assessment. Rules that lack the required evidence or inputs are explicitly not evaluable rather than assigned an invented limit.
