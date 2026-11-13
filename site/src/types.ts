export type PublicData = Latest | Past | LaunchAssessment | RuleSet | Hindcast;
export type GeneratedAt = string;
export type Assessment = boolean;
export type Id = string;
export type LastUpdated = string;
export type LaunchServiceProviderName = string;
export type Abbrev = string;
export type Name = string;
export type Net = string;
export type NetPrecision = string | null;
export type Id1 = number;
export type Latitude = number;
export type Id2 = number;
export type Name1 = string;
export type TimezoneName = string;
export type Longitude = number;
export type Name2 = string;
export type PageUrl = string;
export type Probability = number | null;
export type RocketName = string;
export type Slug = string;
/**
 * Known LL2 status abbreviations, including completed launch outcomes.
 */
export type LaunchStatus =
  | "Go"
  | "TBD"
  | "Success"
  | "Failure"
  | "Hold"
  | "In Flight"
  | "Partial Failure"
  | "TBC"
  | "Payload Deployed";
/**
 * Site coverage of published launch weather criteria.
 */
export type Tier = "A" | "B" | "C";
export type WeatherConcerns = string | null;
export type WindowEnd = string;
export type WindowStart = string;
/**
 * Evidence strength of a model-based rule assessment.
 */
export type Confidence = "direct" | "medium" | "low";
export type Label = string;
export type EnsembleModel = "ecmwf" | "gfs";
export type RiskFraction = number | null;
export type RuleId = string | null;
export type Launches = LaunchSummary[];
export type MembersTotal = number;
export type ScheduleStale = boolean;
export type SchemaVersion = 1;
export type GeneratedAt1 = string;
export type Assessment1 = boolean;
export type AttemptId = string;
export type AttemptNet = string;
export type NetNow = string | null;
export type CreatedOn = string;
export type Text = string;
export type OfficialConcerns = string[];
export type Outcome = "launched" | "launched_later" | "new_t0_pending" | "hold" | "unknown";
export type RiskFraction1 = number;
export type RuleId1 = string;
export type Title = string;
export type Scrubcast24H = AuditRule[];
export type Audit = AuditFooter[];
export type Id3 = string;
export type LastUpdated1 = string;
export type LaunchServiceProviderName1 = string;
export type Name3 = string;
export type Net1 = string;
export type NetPrecision1 = string | null;
export type PageUrl1 = string;
export type Probability1 = number | null;
export type RocketName1 = string;
export type Slug1 = string;
export type WeatherConcerns1 = string | null;
export type WindowEnd1 = string;
export type WindowStart1 = string;
export type Launches1 = PastLaunch[];
export type SchemaVersion1 = 1;
export type Audit1 = AuditFooter[];
export type ConvectiveFractionT0 = number | null;
export type ShearPercentileT0 = number | null;
export type UpperWindPercentileT0 = number | null;
export type EvaluatedAt = string;
export type ElevationM = number;
export type Lat = number;
export type Lon = number;
export type Id4 = string;
export type LastUpdated2 = string;
export type LaunchServiceProviderName2 = string;
export type Name4 = string;
export type Net2 = string;
export type NetPrecision2 = string | null;
export type Probability2 = number | null;
export type RocketName2 = string;
export type Slug2 = string;
export type WeatherConcerns2 = string | null;
export type WindowEnd2 = string;
export type WindowStart2 = string;
export type LowestHourVerified = boolean;
export type Hour = string;
export type MembersBelowT0 = number;
export type UnionRisk = number;
export type Reason = string;
export type RuleId2 = string;
export type Title1 = string;
export type NotEvaluable = OmittedRule[];
export type Concerns = string[];
export type ProbabilityGoPct = number | null;
export type Source = "Launch Library 2";
export type UnmappedConcerns = string[];
export type RefreshDeferred = boolean;
export type ApproximationNote = string;
export type EvaluableMembers = number;
export type Members = number;
export type RiskFraction2 = number | null;
export type Hours = string[];
export type Llccr = number[];
export type Origin = "source" | "scrub";
export type ReadoutPhrase = string;
export type Unit = string;
export type Variable = string;
export type ReferenceOnly = boolean;
export type RuleId3 = string;
export type RuleSetVersion = string;
export type SourceUrl = string;
export type Comparator = ">" | ">=" | "<=";
export type Unit1 = string;
export type Value = number;
export type Title2 = string;
export type Rules = RuleRisk[];
export type SchemaVersion2 = 1;
export type T0Index = number;
export type Llccr1 = number[];
export type Reason1 = string;
export type RuleId4 = string;
export type Title3 = string;
export type NotEvaluable1 = NotEvaluable2[];
export type RuleSetId = string;
export type ApproximationNote1 = string;
export type Evaluation = "proxy";
export type Llccr2 = number[];
export type Needs = string[];
export type ComparatorParam = string;
export type ReadoutPhrase1 = string;
export type ThresholdParam = string;
export type Unit2 = string;
export type Variable1 = string;
export type Parameter = number | string;
export type ReferenceOnly1 = boolean;
export type RuleId5 = string;
export type Section = string;
export type Text1 = string;
export type Title4 = string;
export type Rules1 = Rule[];
export type SourceDate = string;
export type SourceUrl1 = string;
export type Version = string;
export type Auc = number | null;
export type Interval = [unknown, unknown] | null;
export type Label1 = string;
export type Launched = number;
export type Message = string | null;
export type N = number;
export type NotLaunched = number;
export type AttemptId1 = string;
export type Net3 = string;
export type Note = string | null;
export type OfficialGoPct = number | null;
export type Outcome1 = "launched" | "launched_later" | "new_t0_pending" | "hold" | "unknown";
export type Scored = boolean;
export type UnionRisk1 = number | null;
export type Rows = AttemptRow[];
export type Unknown = number;
export type Key = "wind" | "observation" | "concerns";
export type Label2 = string;
export type N1 = number;
export type RankHistogram = number[] | null;
export type RankHistograms = {
  [k: string]: number[];
} | null;
export type Reliability = ReliabilityBin[] | null;
export type Lower = number;
export type N2 = number;
export type Observed = number | null;
export type Predicted = number | null;
export type Upper = number;
export type Baseline = number | null;
export type Interval1 = [unknown, unknown] | null;
export type Label3 = string;
export type N3 = number;
export type Sufficient = boolean;
export type Value1 = number | null;
export type Rows1 = AuditMetric[];
export type Summary = string;
export type Title5 = string;
export type Evaluations = Evaluation1[];
export type Difference = number | null;
export type Interval2 = [unknown, unknown] | null;
export type Label4 = string;
export type N4 = number;
export type PrecipitationAtLowest = number | null;
export type PrecipitationAtT0 = number | null;
export type RiskAtLowest = number | null;
export type RiskAtT0 = number | null;
export type Verified = boolean;
export type LowestHourVerified1 = boolean;
export type NLaunches = number;
export type GeneratedAt2 = string;
export type LowestHourVerified2 = boolean;
export type SchemaVersion3 = 1;
export type Summary1 = string[];

/**
 * Upcoming launches in the ten-day forecast horizon.
 */
export interface Latest {
  generated_at: GeneratedAt;
  launches: Launches;
  members_total: MembersTotal;
  schedule_stale: ScheduleStale;
  schema_version?: SchemaVersion;
  [k: string]: unknown;
}
/**
 * Schedule row with coverage and the available launch-page evidence.
 */
export interface LaunchSummary {
  assessment: Assessment;
  id: Id;
  last_updated: LastUpdated;
  launch_service_provider_name: LaunchServiceProviderName;
  mission: Mission | null;
  name: Name;
  net: Net;
  net_precision: NetPrecision;
  pad: Pad;
  page_url: PageUrl;
  probability: Probability;
  rocket_name: RocketName;
  slug: Slug;
  status: LaunchStatus;
  tier: Tier;
  weather_concerns: WeatherConcerns;
  window_end: WindowEnd;
  window_start: WindowStart;
  worst_rule: WorstRule;
  [k: string]: unknown;
}
/**
 * Mission orbit, which LL2 may not yet identify.
 */
export interface Mission {
  orbit: Orbit | null;
  [k: string]: unknown;
}
/**
 * Orbit abbreviation retained for the schedule's suborbital filter.
 */
export interface Orbit {
  abbrev: Abbrev;
  [k: string]: unknown;
}
/**
 * Launch pad position in geographic degrees and its parent site.
 */
export interface Pad {
  id: Id1;
  latitude: Latitude;
  location: Location;
  longitude: Longitude;
  name: Name2;
  [k: string]: unknown;
}
/**
 * Launch site identity and IANA time zone for local launch times.
 */
export interface Location {
  id: Id2;
  name: Name1;
  timezone_name: TimezoneName;
  [k: string]: unknown;
}
/**
 * Display label and its evidence, absent for unavailable or clear forecasts.
 */
export interface WorstRule {
  confidence?: Confidence | null;
  label: Label;
  model?: EnsembleModel | null;
  risk_fraction?: RiskFraction;
  rule_id?: RuleId;
  [k: string]: unknown;
}
/**
 * Retained launch pages for the preceding ninety days.
 */
export interface Past {
  generated_at: GeneratedAt1;
  launches: Launches1;
  schema_version?: SchemaVersion1;
  [k: string]: unknown;
}
/**
 * Retained launch row carrying the audit footers kept for ninety days.
 */
export interface PastLaunch {
  assessment: Assessment1;
  audit?: Audit;
  id: Id3;
  last_updated: LastUpdated1;
  launch_service_provider_name: LaunchServiceProviderName1;
  mission: Mission | null;
  name: Name3;
  net: Net1;
  net_precision: NetPrecision1;
  pad: Pad;
  page_url: PageUrl1;
  probability: Probability1;
  rocket_name: RocketName1;
  slug: Slug1;
  status: LaunchStatus;
  tier: Tier;
  weather_concerns: WeatherConcerns1;
  window_end: WindowEnd1;
  window_start: WindowStart1;
  worst_rule: WorstRule;
  [k: string]: unknown;
}
/**
 * Outcome of one audited launch attempt.
 */
export interface AuditFooter {
  attempt_id: AttemptId;
  attempt_net: AttemptNet;
  net_now: NetNow;
  note: AuditNote | null;
  official_concerns: OfficialConcerns;
  outcome: Outcome;
  scrubcast_24h: Scrubcast24H;
  [k: string]: unknown;
}
/**
 * Dated launch outcome evidence.
 */
export interface AuditNote {
  created_on: CreatedOn;
  text: Text;
  [k: string]: unknown;
}
/**
 * Rule evidence from an attempt's 24-hour ledger row.
 */
export interface AuditRule {
  risk_fraction: RiskFraction1;
  rule_id: RuleId1;
  title: Title;
  [k: string]: unknown;
}
/**
 * Versioned launch-page assessment contract.
 */
export interface LaunchAssessment {
  audit?: Audit1;
  context: Context;
  evaluated_at: EvaluatedAt;
  fetched_at: FetchedAt;
  grid_point: GridPoint;
  launch: Launch;
  lowest_hour_verified?: LowestHourVerified;
  lowest_union_hour: LowestHour | null;
  not_evaluable: NotEvaluable;
  official: Official;
  refresh_deferred: RefreshDeferred;
  rules: Rules;
  schema_version?: SchemaVersion2;
  t0_index: T0Index;
  tier: Tier;
  union_risk_t0: UnionRiskT0;
  [k: string]: unknown;
}
/**
 * Context values remain absent when weather or historical evidence is missing.
 */
export interface Context {
  convective_fraction_t0: ConvectiveFractionT0;
  shear_percentile_t0: ShearPercentileT0;
  upper_wind_percentile_t0: UpperWindPercentileT0;
  [k: string]: unknown;
}
export interface FetchedAt {
  [k: string]: string | null;
}
/**
 * Returned forecast cell in display units.
 */
export interface GridPoint {
  elevation_m: ElevationM;
  lat: Lat;
  lon: Lon;
  [k: string]: unknown;
}
/**
 * Consumed LL2 normal fields; probability is the official integer percent of GO.
 */
export interface Launch {
  id: Id4;
  last_updated: LastUpdated2;
  launch_service_provider_name: LaunchServiceProviderName2;
  mission: Mission | null;
  name: Name4;
  net: Net2;
  net_precision: NetPrecision2;
  pad: Pad;
  probability: Probability2;
  rocket_name: RocketName2;
  slug: Slug2;
  status: LaunchStatus;
  weather_concerns: WeatherConcerns2;
  window_end: WindowEnd2;
  window_start: WindowStart2;
  [k: string]: unknown;
}
/**
 * Material ECMWF improvement within the launch window.
 */
export interface LowestHour {
  hour: Hour;
  members_below_t0: MembersBelowT0;
  union_risk: UnionRisk;
  [k: string]: unknown;
}
/**
 * Unavailable criterion and the reason it cannot be evaluated.
 */
export interface OmittedRule {
  reason: Reason;
  rule_id: RuleId2;
  title: Title1;
  [k: string]: unknown;
}
/**
 * Official forecast kept separate from modelled member fractions.
 */
export interface Official {
  concerns: Concerns;
  probability_go_pct: ProbabilityGoPct;
  source?: Source;
  unmapped_concerns: UnmappedConcerns;
  [k: string]: unknown;
}
/**
 * Resolved criterion with hourly evidence and a separate T-0 summary.
 */
export interface RuleRisk {
  approximation_note: ApproximationNote;
  by_model: ByModel;
  confidence: Confidence;
  hours: Hours;
  llccr: Llccr;
  member_values_by_hour: MemberValuesByHour;
  member_violated_by_hour: MemberViolatedByHour;
  plot: ResolvedPlot;
  reference_only: ReferenceOnly;
  risk_by_hour: RiskByHour;
  rule_id: RuleId3;
  rule_set_version: RuleSetVersion;
  source_url: SourceUrl;
  threshold: Threshold | null;
  title: Title2;
  [k: string]: unknown;
}
export interface ByModel {
  [k: string]: ModelRisk;
}
/**
 * T-0 rule risk with its evaluable and supplied member counts.
 */
export interface ModelRisk {
  evaluable_members: EvaluableMembers;
  members: Members;
  risk_fraction: RiskFraction2;
  [k: string]: unknown;
}
export interface MemberValuesByHour {
  [k: string]: (number | null)[][] | null;
}
export interface MemberViolatedByHour {
  [k: string]: ((0 | 1) | null)[][] | null;
}
/**
 * Display-ready plot metadata without unresolved parameter names.
 */
export interface ResolvedPlot {
  origin: Origin;
  readout_phrase: ReadoutPhrase;
  unit: Unit;
  variable: Variable;
  [k: string]: unknown;
}
export interface RiskByHour {
  [k: string]: (number | null)[];
}
/**
 * Resolved comparison in the plotted variable's units.
 */
export interface Threshold {
  comparator: Comparator;
  unit: Unit1;
  value: Value;
  [k: string]: unknown;
}
export interface UnionRiskT0 {
  [k: string]: number | null;
}
/**
 * Dated source criteria loaded together before any launch is assessed.
 */
export interface RuleSet {
  not_evaluable: NotEvaluable1;
  rule_set_id: RuleSetId;
  rules: Rules1;
  source_date: SourceDate;
  source_url: SourceUrl1;
  version: Version;
  [k: string]: unknown;
}
/**
 * Criterion omitted from verdicts because the required evidence is unavailable.
 */
export interface NotEvaluable2 {
  llccr: Llccr1;
  reason: Reason1;
  rule_id: RuleId4;
  title: Title3;
  [k: string]: unknown;
}
/**
 * Published criterion and its explicitly approximate model proxy.
 */
export interface Rule {
  approximation_note: ApproximationNote1;
  confidence: Confidence;
  evaluation: Evaluation;
  llccr: Llccr2;
  needs: Needs;
  origin?: Origin1;
  plot: Plot;
  proxy: Proxy;
  reference_only?: ReferenceOnly1;
  rule_id: RuleId5;
  section: Section;
  text: Text1;
  title: Title4;
  [k: string]: unknown;
}
export interface Origin1 {
  [k: string]: "scrub";
}
/**
 * Parameter references shared by the verdict, threshold line and readout.
 */
export interface Plot {
  comparator_param: ComparatorParam;
  readout_phrase: ReadoutPhrase1;
  threshold_param: ThresholdParam;
  unit: Unit2;
  variable: Variable1;
  [k: string]: unknown;
}
export interface Proxy {
  [k: string]: Parameter;
}
/**
 * Published forward-audit summaries and the lowest-hour verification state.
 */
export interface Hindcast {
  forecast_audit?: ForecastAudit | null;
  generated_at: GeneratedAt2;
  lowest_hour_verified?: LowestHourVerified2;
  schema_version?: SchemaVersion3;
  summary?: Summary1;
  [k: string]: unknown;
}
/**
 * Forward audit tables, with an explicit insufficient-data state at every metric.
 */
export interface ForecastAudit {
  attempts: AttemptEvaluation;
  evaluations: Evaluations;
  lowest_hour: LowestHourEvaluation;
  lowest_hour_verified: LowestHourVerified1;
  n_launches: NLaunches;
  [k: string]: unknown;
}
/**
 * Launch-versus-scrub comparison, kept separate from calibration metrics.
 */
export interface AttemptEvaluation {
  auc?: Auc;
  interval?: Interval;
  label: Label1;
  launched: Launched;
  message?: Message;
  n: N;
  not_launched: NotLaunched;
  rows: Rows;
  unknown: Unknown;
  [k: string]: unknown;
}
/**
 * One audited attempt with its 24-hour union risk and official GO value.
 */
export interface AttemptRow {
  attempt_id: AttemptId1;
  net: Net3;
  note: Note;
  official_go_pct: OfficialGoPct;
  outcome: Outcome1;
  scored: Scored;
  union_risk: UnionRisk1;
  [k: string]: unknown;
}
/**
 * One of the three evidence families kept apart on the audit page.
 */
export interface Evaluation1 {
  key: Key;
  label: Label2;
  n: N1;
  rank_histogram?: RankHistogram;
  rank_histograms?: RankHistograms;
  reliability?: Reliability;
  rows: Rows1;
  summary: Summary;
  title: Title5;
  [k: string]: unknown;
}
/**
 * Predicted risk and observed event frequency in one fixed-width bin.
 */
export interface ReliabilityBin {
  lower: Lower;
  n: N2;
  observed: Observed;
  predicted: Predicted;
  upper: Upper;
  [k: string]: unknown;
}
/**
 * A printed metric with its sample size and the reference it is read against.
 */
export interface AuditMetric {
  baseline?: Baseline;
  interval?: Interval1;
  label: Label3;
  n: N3;
  sufficient?: Sufficient;
  value?: Value1;
  [k: string]: unknown;
}
/**
 * Paired observed precipitation at the marked hour and at T-0.
 */
export interface LowestHourEvaluation {
  difference: Difference;
  interval: Interval2;
  label: Label4;
  n: N4;
  precipitation_at_lowest: PrecipitationAtLowest;
  precipitation_at_t0: PrecipitationAtT0;
  risk_at_lowest: RiskAtLowest;
  risk_at_t0: RiskAtT0;
  verified: Verified;
  [k: string]: unknown;
}
