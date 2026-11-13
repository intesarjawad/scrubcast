# Design direction

Scrubcast has one job: let someone read the official launch forecast, see which
weather rule the forecast models break and at what hour, and decide when to watch.
Every choice below serves that reading order.

The page shows the forecast as one evening, printed 82 times. Each ensemble member
writes the same typeset page about the launch window. All 82 pages are overprinted
on one sheet. Where the members agree, the type prints solid. Where they disagree,
it blurs.

## What it steals, and from whom

- **Idris Khan, the *every...* overprints (2004).** Every instance of a series goes
  onto one sheet at low density. What the instances share builds up to solid black,
  and what differs stays a grey blur. Agreement becomes sharpness, so a reader needs
  no chart literacy to see where the models disagree.
- **Bernd and Hilla Becher, the *Typologies*.** Khan's overprint only works because
  the Bechers held the framing fixed, and the page holds its layout fixed for the
  same reason. Every member's page has the same sentences in the same places, so a
  blur can only mean the members gave different numbers.

No asset, word, mark or trade dress from either is used.

## Who reads it, and what they do

- **Launch watchers, travellers and photographers** decide whether to drive tonight
  and when inside the window. They need the launch, the official number, the
  highest-risk rule and where the members disagree, all in the first viewport.
- **Educators, journalists and meteorologists** check the rules and what happened.
  They need sources, thresholds, approximation labels, cannot-evaluate limits and
  audit links to be legible. Official concerns are forecasts, never observed truth.
- **Someone opening a shared link** should recognise the mission, the official
  number and the verdict from the card alone, at thumbnail size.

## Reading order

1. Mission, pad, T-0 and the official probability, quoted with its source.
2. The sheet: the evening in sentences, the figure rule's hourly values, every
   rule's status and the member verdict.
3. The fan under the sheet: one figure's 82 values against the limit.
4. The facts column: official forecast, how many members break each rule, the
   track record and when the forecast was fetched.
5. What every page leaves blank: the rules no model can evaluate, each with its
   reason, in two columns under the fan.
6. Below the fold: the window scrubber, the rule board, method, audit and data
   links.

On a phone the sheet comes first, so the first figure is above the fold, and the
facts, the blank rules and the pages control follow the fan in that order.

## Signature moment: the overprint

The page is real DOM text first. Each member's numbers sit in fixed slots inside
the sentences, so screen readers, search and copy all get the ensemble's typical
value and every member's value is listed in the fan's caption.

Over that text, one WebGL2 canvas prints the sheet:

- Every member's page is a set of glyph quads added into a half-float buffer. Each
  page lays 1/82 of the ink, so a word all 82 members print is solid and a figure
  24 members share prints at 29%. The density is the real share of members, with
  three floors, and the facts column and the fan give every exact count:
  - a group fewer than 12% of members print is raised to 12% (`MIN_SHARE`), so one
    member's value shows as a faint mark instead of a hole;
  - a group that breaks a rule is raised to 35% (`ALARM_SHARE`) and prints in red
    ink, so the alarm is the easiest thing on the sheet to read;
  - a figure's typical value prints at 35% (`TYPICAL_SHARE`) from its cluster's
    first page, with each member that agrees adding its share, so the figure reads
    even when few members agree on its last digit.
- Only figures that agree on their leading digits overprint. A slot clusters its
  members' values by the digit in the limit's leading place (thousands for a
  1,400 m limit, tens for 13.4 m/s), and below that place by their number of
  digits, so every member of a cluster is as long as its typical value. Each
  cluster gets its own place in the
  slot, set apart with commas and "or" in the sentence's own type: "0, 2,073, 3,314
  or 4,762 m". Digits of different values therefore never add up into a number no
  member forecast; `site/tests/unit/sheet.test.ts` checks every slot on the stormy
  fixture.
- Inside a cluster each figure prints digit by digit against the typical value, the
  one most members are within one display step of (`register`). Every digit prints
  in its own place, inside the typical figure's box. A digit a member shares with
  the typical value sits on the line. Every digit that differs is lifted when the
  member's value is above the typical one and dropped when it is below: 0.3 em for
  one display step, 0.025 em more for each doubling of the gap, up to 0.4 em. So
  2,078 against 2,069 lifts its 7 and 8 together. In each place the ghosts never
  carry more than half the typical digit's ink at any frame of the press
  (`ghostScales` in `sheet.ts`), so a thin 1 or 7 stays the digit you read. No
  member's digit stands on the line as if the typical value had it, and no figure
  grows a place: the 17:00 wind reads "6.7" with ghosts above and below it.
- A word slot works the same way: each different word has its own place, so words
  never overlap into a misprint ("clear" beside "no field", not over it).
- The verdict line prints each member's own count, so on the stormy fixture it
  reads "Members break 0, 1 or 3 of 5 rules" at the counts' real shares and the
  counts above zero are red. The facts column states how many members break each
  rule at any hour, counted the same way, with the hour most of them do
  (`peakHour`): "Thick cloud 42 of 82 (peak 19:00)". The stormy fixture checks 5
  rules and the calm night 6, because the fixture has no published liftoff wind
  limit; the "Left blank" list under the fan says so for every rule a page cannot
  check.
- The final pass turns ink density into colour with dot gain, 1 − (1 − c)², ink
  spread from an 8-tap ring, starvation on the paper's tooth and fbm paper grain
  with no directional fibre. Figures print in EB Garamond Bold, so even a 29% share
  reads as dense ink.
- Pages register in place on a fixed sheet, inside crop marks that build up with
  the type. Every printed page holds its share, 1/38 at 38 pages, and the pages
  still striking share at most one page more between them, so words print as solid
  mid-press as on the finished sheet. Until a
  group's first page prints, a hairline holds its width in the sentence, so
  "Anvil: clear or no field" never opens a gap. Page *i* strikes heavier than its
  share for 80 ms, then settles to it over
  240 + 760 × 0.9<sup>*i*</sup> ms, and the next page starts
  26 + 430 × 0.84<sup>*i*</sup> ms later, 5.4 s for 82 pages. ECMWF's 51 pages
  print first, then GFS's 31. The DOM text is hidden while the press runs, so
  nothing sharp sits under the ink. The page-number slot shows only the page on the
  press, and the finished sheet reads "No. 82".
- Pointing at or focusing a figure fans its 82 copies into columns on a scale
  below the sheet, in the page's serif. The scale is cut into 14 columns in data
  units (`FAN_COLUMNS`), the same at every viewport, and each column stands as tall
  as its share of members, so 58 identical zeros tower over a column of 6. Copies
  overprint up the column a few pixels apart. A column holding one of the sheet's
  figures is labelled with that figure, so the fan and the sentence print the same
  "6.7"; any other column is labelled with the value most of its members are near
  (`fanLabels`). On a phone a column too close to its neighbour for their copies
  to stand apart joins it, under the label of the one holding a sheet figure. The
  member count sits above in a smaller italic "×N". The
  caption changes hour only once the old hour's columns have left the scale. The scale is ticked on a 1, 2 or 5 step (every 2 m/s for
  wind, every 1,000 m for cloud). Copies rise from the axis, so nothing crosses the
  sentences while they move. The limit prints in red, and the caption reads it
  out: "19:00, all 82 members: 2.8 to 7.2 m/s. None break the 13.4 m/s limit."
- Values that break their rule print in the alarm ink, a second channel in the same
  buffer, so a stormy night smudges red where members break the rule.
- Dragging the pages control rewinds the press live to the first *n* pages, ECMWF's
  51 then GFS's 31.

The GL code is a separate 2.8 KB gzip chunk, loaded only when the sheet starts. The
canvas caps device pixels at 2, and at 1 when the sheet is in its narrow layout. It
stops drawing when the sheet is off screen or the tab is hidden. Without WebGL2 and
half-float render targets, or if the context fails, a Canvas 2D renderer prints the
same finished sheet without grain. The share card uses that renderer on purpose so
every build matches.

### What the recorded night shows, honestly

The recorded launch forecast is calm. No member breaks any of the six rules, so the
alarm ink never appears on that page and the verdict prints solid: "Members
break 0 of 6 rules." The track record is empty (n=0) and the facts column says so.

To check the page on a night the members disagree, `scripts/record_storm_fixture.py`
assesses the repository's own recorded Cape Canaveral ensemble over its cloudiest
four hours and writes `tests/fixtures/worst_case/storm-night.json`. No launch was
scheduled then. The fixture's launch is named "Fixture night, Cape ensemble, not a
launch" and is never shown as one. On it, thick cloud ranges from 0 to 4,770 m at
19:00, 42 of 82 members break the 1,400 m limit at some hour and up to 58% of GFS
members break it in one hour, so the alarm ink and the wide smudges both show.
ECMWF members break the rule too, so red appears with the first pages and deepens
as GFS lands; it does not wait for GFS. The
window, 00:00 to 04:00 UTC, precedes the 09:00 UTC time it is assessed at, so
these are model hours for an evening already past, not a forecast anyone could
have acted on. The README clip shows this night and its
first caption says it is a fixture.

## Type

| Role | Family | Use |
|---|---|---|
| The sheet, the fan and the rule board | EB Garamond, roman 400 to 800 and italic 400 | Page text in Medium, figures in Bold, the fan, the board and its sentences |
| Notes and the plot | Public Sans | Notes, facts, the plot's labels and readout |

Both are self-hosted under the SIL Open Font License and recorded in
`site/public/fonts/credits.json`. A book face for the page makes it read as a
printed statement, which is what an overprint needs. The variable EB Garamond file
already carries weights up to 800, so the heavier figures cost no extra download.

Sizes: 11, 13, 15, 17, 21, 22, 28, 42, 48, 68 and 88 px, plus three fluid sizes for
the sheet: page text `clamp(19px, 2.4vw, 34px)`, status line `clamp(15px, 1.7vw,
24px)` and title `clamp(46px, 4.4vw, 64px)`. Under 700 px the page text is 22 px
SemiBold. Line heights: 0.96, 1, 1.08, 1.25, 1.3 and 1.5. Spacing: 4, 8, 12, 16,
20, 24, 32, 40 and 80 px. Nothing outside the token block sets a raw size.

## Colour

The ground is uncoated stock, and the inks are a warm black and one alarm red. The
light theme is primary because the sheet is paper. The dark theme prints light ink
on dark stock for night reading.

| Token | Role | Light | Dark |
|---|---|---|---|
| `--bg` | Paper | `#e8e5de` | `#191816` |
| `--surface` | The skip link's panel | `#dcd8ce` | `#262421` |
| `--ink` | Body text and the sheet's ink | `#171513` | `#ece8df` |
| `--muted`, `--rule` | Secondary text, threshold line | `#55504a` | `#b2aca1` |
| `--line` | Separators only | `#b3ada3` | `#4a4640` |
| `--graphic` | Member traces, axes, control borders | `#77716a` | `#8b857b` |
| `--alarm` | The sheet's alarm ink | `#8a1a0c` | `#f08a6c` |
| `--accent`, `--focus` | Exceeding members in the plot, focus ring | `#a8321f` | `#f08a6c` |

The red appears only where a member breaks a rule and on focus.
If it shows up anywhere else, it stops meaning "this member breaks the rule".

Risk is never carried by colour alone. The fan prints every value with the limit
line beside it and the caption counts the members that break it. The verdict
sentence gives the count in words. Below the fold, exceeding members are 3 px
against 1 px and every rule on the board has its count. Both models' traces are
solid, told apart by their labelled panes.

The sheet's alarm ink is a deeper red than the plot's accent because it prints at
a share, not at full strength. On the stormy fixture 41 of 82 members break one
rule, so the verdict's red "1" prints at half density; through dot gain that reads
at 4.57:1 on light paper and 4.6:1 on dark (`sheet.test.ts` computes it from the
tokens), above the 3:1 that large bold type needs. Paper grain takes about 0.1
off on screen.

Measured contrast on the opaque token pairs:

| Pair | Light | Dark | Needs |
|---|---|---|---|
| Body text on ground | 14.48:1 | 14.51:1 | 4.5:1 |
| Secondary text on ground | 6.34:1 | 7.86:1 | 4.5:1 |
| Secondary text on panel | 5.61:1 | 6.86:1 | 4.5:1 |
| Accent text on ground | 5.31:1 | 7.23:1 | 4.5:1 |
| Alarm ink on ground | 7.47:1 | 7.23:1 | 4.5:1 |
| Member traces on ground | 3.83:1 | 4.85:1 | 3:1 |
| Threshold on ground | 6.34:1 | 7.86:1 | 3:1 |

`site/tests/unit/tokens.test.ts` recomputes these from the stylesheet, so the
table cannot drift from the tokens.

In forced-colours mode the canvas is hidden and the DOM text shows in system
colours, with each slot holding the ensemble's typical value.

## Layout

A spread on the header's grid: the wordmark, the sheet and the notes share one left
edge, and the nav and the notes share one right edge, 1280 px apart at most. The
sheet is on the left; a 400 px notes column on the right holds the mission, title,
legend, pages control and facts. Under 700 px of width the spread becomes one
column (mission, facts, title and legend, sheet, the unprinted words, then the
pages control), so the sheet starts in the first screen at 390×844. Crop marks print only where all four have a
margin to stand in, so a phone shows none. The sheet and the notes fill the first
viewport at 1440×900. The page reflows without
horizontal scrolling at 320 CSS px and at 200% zoom. Controls are at least 44 px,
except the rule and model names that sit inside sentences.

Below the fold the page keeps the sheet's voice. The rule board is a printed table
in EB Garamond with hairline rules and no fills, listing only rules some member
breaks at T-0; the rules no member breaks are named in one sentence after it. Each
rule name is a button that plots that rule, and the model choice is a sentence:
"Read the members of ECMWF or GFS." On a night no member breaks anything the plot
opens on the sheet's figure rule, so it draws the members' values instead of a row
of zeros. The plot is a printed figure: serif labels, open axes, no frames or
window stubs, and a count printed only when some member breaks the rule, since the
readout above already states the zero. The notes, "Each hour in figures" among
them, open from underlined serif headings, without disclosure triangles. A
focused figure is underlined in ink, because red on this page means a broken rule.

## Motion

- The press run, once, when the sheet first prints, and live while the pages
  control is dragged.
- The fan, 900 ms, when a figure is pointed at or focused, inside the band below
  the sheet.
- On the stormy night the GFS pages land after the ECMWF ones, so the red cloud
  figure splits sideways into its clusters as they strike: each cluster, its red
  rule and the comma or "or" before it arrive with the cluster's first page, the
  digits members disagree on spread beside their places, the verdict's red "1"
  deepens page by page, and dragging the pages control back rewinds it.

Under `prefers-reduced-motion: reduce` neither runs: the finished sheet prints at
once and the fan switches without travel. No parallax and no animated backgrounds.

## Terminal

The 80-column board uses the same reading order and reads without colour. It
wraps at 60 and 120 columns and honours `NO_COLOR`.

## What does not change

- The official probability is quoted with its wording and source, never restated
  as a launch chance computed here.
- Model member shares are never called probabilities.
- A blur means members disagree. Nothing on the sheet is blurred for effect.
- The text stays in the DOM. The canvas only prints what the text already says.
- No account, key, cookie, analytics or tracking script on the first-run path.
- No icons as decoration, no gradient hero, no status dots.

## Where each number comes from

| On screen | Script |
|---|---|
| The 82 members, 51 ECMWF and 31 GFS | `src/scrubcast/build/site_data.py`, `members_total` in `latest.json` |
| Every value on a member's page, the verdicts and alarms | `site/src/charts/sheet-data.ts` `buildSheet`, reading the assessment written by `src/scrubcast/assess/launch.py` |
| The figure rule and its hours | `figureRule` and `figureHours` in `sheet-data.ts` |
| Which values overprint, and each cluster's place | `cluster` and the slot groups in `slot`, `sheet-data.ts` |
| Each cluster's typical value | `densest` in `sheet-data.ts` |
| Where each member's digits print, in register or aside | `register` in `sheet-data.ts`, placed on the typical value's tabular places by `figureLayout` in `sheet.ts` |
| The 35% floors for an alarm and for a typical value's digits | `ALARM_SHARE` and `TYPICAL_SHARE` in `sheet-data.ts` |
| The fan caption | `fanSummary` in `sheet-data.ts` |
| The fan's columns, labels and "×N" counts | `FAN_COLUMNS`, `fanColumns` and `fanLabels` in `sheet-data.ts`, heights scaled to the band in `sheet.ts` |
| How far a ghost digit rises, and its ink against the typical digit | `register` in `sheet-data.ts`; `ghostScales` and `GHOST_RATIO` in `sheet.ts` |
| The peak hour in the facts column | `peakHour` in `sheet-data.ts` |
| Members breaking each rule, in the facts column | `membersBreaking` in `sheet-data.ts` |
| The 12% floor for a rare value | `MIN_SHARE` in `sheet-data.ts` |
| The verdict red's contrast, 4.57:1 and 4.6:1 | `site/tests/unit/sheet.test.ts`, from the tokens and the dot-gain curve |
| Press-run timing | `pressSchedule` in `sheet-data.ts`, plus `STRIKE_MS` in `sheet.ts` |
| Official probability | Launch Library 2, through `src/scrubcast/sources/` into the assessment |
| Track record, n=0 | `forecast_audit.n_launches` in `hindcast.json` |
| The demo page and the repository preview | `tests/fixtures/demo`, built by `site/scripts/fixtures.py` |
| The stormy fixture and the README clip | `scripts/record_storm_fixture.py` |

## How I check it

- Token contrast and scale tests in `site/tests/unit`.
- `site/tests/unit/sheet.test.ts` checks member order, the figure rule, "no field"
  against "clear", alarms and the fan caption on the stormy fixture, that every
  overprinted cluster agrees on its leading digits and length, that every mark sits
  inside the typical value's places, that no differing digit prints on the line at
  any stage of the press, that a ghost rises for a higher value and drops for a
  lower one, further for a wider gap, that every typical digit carries at least
  twice its ghosts' ink at every page count and mid-strike, that the fan labels a
  figure's column with the sheet's own value, the peak hour, the calm wind figures'
  typical values, the
  alarm and rare-value floors, the verdict red's contrast, the page-number slot and
  the fan's column packing.
- `site/tests/e2e/worst-case.spec.ts` reads the ink box of every glyph the press
  draws, on the stormy fixture and the calm recording at half the pages and at all
  82, and fails if any glyph on a figure's line sits outside a slot's box. It then
  reads the printed pixels in every figure place that has ghosts and fails unless
  they match the typical digit's shape more closely than any ghost digit's shape.
- axe, keyboard and forced-colours runs in Chromium and WebKit.
- Screenshots at 1440×900, mid press run, mid fan, 390×844 with its fan, the stormy
  fixture, reduced motion and dark.
- The share card at 1200×630; the preview at 1280×640 and again at 400×200.

## The recording

The demo GIF and the X and Bluesky clip are recorded from the fixture build with `npm
--prefix site run fixtures && npm --prefix site run build && npm --prefix site run
record-demo`. They show the stormy fixture night from
`tests/fixtures/worst_case/storm-night.json`, served beside the build; the sheet
names it a fixture and so does the first caption. The repository preview is the
calm recorded launch from `tests/fixtures/demo`. The page is recorded at 1440×810 CSS
px in the light theme under a frozen clock, one frame every 83 ms, and scaled to
1280×720. The cursor only hovers, so the focus ring never appears in the recording.

Frames read at 640 px wide:

| Time | What the frame shows | What to look for |
|---|---|---|
| 0.0 to 5.5 s | Pages strike and settle on the fixed sheet and the page-number slot ticks to 82 | Each page lands dark and settles to its share while the sheet's ink stays one page deep, so words hold solid and figures blur as members disagree; the red cloud figure splits into its clusters, each arriving with its comma or "or", and the verdict's red "1" deepens as the GFS pages land |
| 5.5 to 6.5 s | The finished sheet with the 19:00 fan open | Solid sentences, red-ghosted figures, "0, 2,073, 3,314 or 4,762 m" with no cluster over another, "clear or no field" for anvil, the verdict "0, 1 or 3 of 5 rules" with the "1" and "3" in red |
| 6.5 to 8.0 s | The cursor points at the 21:00 figure and its copies rise into columns | The zero column caps with "+51", the breaking columns print red against the red limit |
| 8.0 to 10.0 s | Hold, with the fan caption as the subtitle | "21:00, all 82 members: 0 to 3,314 m. 22 of 82 break the 1,400 m limit." |

The repository preview (`site/public/social-preview.png`, also the `og:image` for pages
without their own card) is the finished calm sheet under reduced motion. At 400×200
the title, the solid sentences and the blurred figures read; the facts column does not.

Known limits:

- The recorded launch is calm, so the clip shows the stormy fixture instead. It is
  real model output but not a launch, and its window was already past when it was
  assessed.
- A value one member wrote prints at the 12% floor, not its real 1/82, so it can be
  seen at all, and an alarm or a typical value's digits at 35%. Exact counts are in
  the facts column and the fan.
- Ghosts are capped at half the typical digit's ink, so on a split night the
  sheet understates how many members disagree. The fan and its caption carry the
  exact values.
- A gap of 16 display steps or more lifts its ghosts the full 0.4 em, so a very
  wide spread prints its tails on one spot.
- The 2D fallback and the share card have no paper grain.
- Rendering was checked in headless Chromium and Brave only.
