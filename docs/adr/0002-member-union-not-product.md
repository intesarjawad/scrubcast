# 0002: Use a member union for combined rule risk

For each model and hour, combined risk is the fraction of ensemble members that violate at least one evaluable direct or medium confidence rule that is not reference-only. Rule risks are not added or multiplied: the member union preserves the relationship between conditions within each forecast member without assuming independence. Low confidence and reference-only rules remain visible separately, and the union is not a probability of launch or a complete assessment of launch constraints.
