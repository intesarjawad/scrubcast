# 0009: Preserve hourly denominators and consume the resolved rule selection

The rule engine and [ADR 0002](0002-member-union-not-product.md) use different
denominators deliberately. Each rule's risk is its violating members divided
by its evaluable members, or absent when none are evaluable. The combined risk
is the member union of direct and medium confidence, non-reference rules,
divided by all supplied members. Missing evidence never counts as a violation.
With no supplied members, the union fraction is absent.

The hourly result exposes each rule's evaluable and violating member counts,
its member verdicts and plotted values, and the union's integer violating count.
For example, one wind violation and one member without wind evidence give
wind risk 1/1 and union risk 1/2. Consequently, the union-versus-rule comparison
property applies only to fully evaluable inputs and eligible rules. Mixed
evaluability has explicit denominator tests instead.

`assess_hour` accepts the committed `RuleSelection` from the loader. It evaluates
the selected site rules and the optional vehicle wind criterion together,
including the vehicle's sustained or peak measurement. Callers do not assemble
a synthetic rule set. Site reference flags apply to site rules; the independently
selected published vehicle wind limit remains eligible for the union. Omitted
criteria and their reasons pass through from the selection.

Window comparisons retain integer union counts. The lowest-hour materiality
gates compare `diff >= 5` and `diff * 100 >= 10 * members` (at least five members and
ten percentage points below T-0) before converting the selected result to a risk fraction.
