# UI Feasibility Review

## Review Loop

1. Establish route, viewport, state prerequisites, and expected user task.
2. Capture an accessibility snapshot for structure and interaction targets.
3. Capture a screenshot when visual layout, spacing, clipping, contrast, or
   responsive behavior matters.
4. Inspect console or network only when the symptom points there.
5. State the concrete issue, user impact, evidence, and likely code owner.
6. Make the smallest code fix that addresses the confirmed issue.
7. Re-run the same browser evidence path.
8. Add or update a durable regression test when the project has a suitable test
   stack.

## Critique Focus

- Primary workflow completion.
- Visible broken states, clipped text, overlap, and layout shifts.
- Keyboard reachability and accessible names for controls.
- Form validation, loading, empty, and error states.
- Console errors tied to visible behavior.
- Network failures tied to UI behavior.
- Mobile and desktop viewport behavior when responsive layout is in scope.

## Evidence Format

Keep evidence compact:

```text
route: http://localhost:3000/settings
viewport: 390x844
page: chrome-devtools pageId=2
tool: take_snapshot + screenshot
finding: Save button overlaps footer after validation error.
artifact: .localsetup-maint/ui-browser-artifacts/20260629-settings-mobile.png
next: patch settings form footer spacing and add Playwright regression.
```

Do not paste large screenshots, traces, HAR files, or console dumps into public
docs. Store private artifacts under `.localsetup-maint/` and summarize only the
actionable facts.
