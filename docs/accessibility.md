# Accessibility checks

Checked 2026-11-06. The regression checks live in
`site/tests/e2e/accessibility.spec.ts`. No browser session was available while
this document was written, so the Playwright and VoiceOver results below are
recorded as not run. Run them before treating a release as verified:

```sh
cd site
npm run fixtures
npm run build
npx playwright test accessibility.spec.ts
```

| Check | Method | Result | Date |
| --- | --- | --- | --- |
| Keyboard walk, home | Tab from the top, skip link to main, first mission link receives focus with a visible ring | Automated regression added; not run in this environment | 2026-11-06 |
| Keyboard walk, launch | Skip link, rule and model buttons, hourly slider and table disclosure all receive focus in order | Automated regression added; not run in this environment | 2026-11-06 |
| Keyboard walk, audit | Skip link to main, next focusable control has a visible ring, audit tables are reachable | Automated regression added; not run in this environment | 2026-11-06 |
| Rule board row, VoiceOver | VoiceOver reads the row header, rule title and both model member counts | Manual check not run; DOM contract covered by `accessibility.spec.ts` | 2026-11-06 |
| Scrubber readout, VoiceOver | VoiceOver announces the polite atomic status and the slider value text | Manual check not run; DOM contract covered by `accessibility.spec.ts` | 2026-11-06 |
| Table disclosure, VoiceOver | "Each hour in figures" opens and closes from the keyboard and the table has a caption | Manual check not run; DOM contract covered by `accessibility.spec.ts` | 2026-11-06 |
| 200 percent zoom | Home, launch and audit at 1280 px with browser zoom at 200 percent, no horizontal scroll | Automated regression added; not run in this environment | 2026-11-06 |
| Reduced motion | The scrubber traces keep a zero transition duration when reduced motion is requested | Existing coverage in `scrubber.spec.ts`; not run in this environment | 2026-11-06 |
| Automated rules | Every page passes axe with no violations at 320, 390 and 1280 px in light and dark schemes | Existing coverage in `home.spec.ts` and `launch.spec.ts`; not run in this environment | 2026-11-06 |

The VoiceOver checks use the macOS screen reader with the page loaded in Safari.
The rule board row check covers the table row header and both member count cells.
The scrubber readout check covers the live status after an arrow key step and
after Home and End. The table disclosure check covers the summary control and the caption of the table it reveals.

## Defects found

Inspection found no missing requirement and no page behaviour changed. The
existing rule board uses table roles that survive the narrow two-column layout,
the scrubber readout is a polite atomic status, and the hourly evidence table
sits behind a native disclosure with a caption. The automated checks above are
the regression tests for those three behaviours, so a later change that removes
a role, name or caption fails a test.
