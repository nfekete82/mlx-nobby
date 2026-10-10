# Systeminfo modal layout regression — 2026-10-10

PR #199, branch `fix/runtime-info-sidebar-click`.

## Browser-confirmed cause

The dialog carried the legacy `runtime-popover` class inside the filtered
topbar. Three stylesheets owned its geometry: `chat.css`, `shorts-studio.css`
(including empty/active chat and mobile variants), and `media-library.css`.
The last stylesheet set `top: 50% !important` and `left: 50% !important`, then
overwrote both with the later shorthand `inset: auto !important`. Combined
with `margin: 0` and `transform: translate(-50%, -50%)`, this positioned the
native top-layer dialog at the viewport origin and translated half its size
outside the viewport. Moving the node to body did not correct that cascade.

Chromium `getComputedStyle()` and `getBoundingClientRect()` on the production
page, with fixture Agent responses, confirmed the failure before the fix:

| Viewport | Sidebar | Bounds `(x, y, width, height)` | Computed position |
| --- | --- | --- | --- |
| 1440 × 1000 | expanded and collapsed | `(-320, -365, 640, 730)` | `top: 0px; left: 0px; margin: 0px` |
| 390 × 844 | mobile navigation open | `(-179, -368.25, 358, 736.5)` | `top: 0px; left: 0px; margin: 0px` |

The initial four browser geometry cases failed on the unmodified application.
The previous source-regex tests could not detect this layout error and also
contained stale expectations; real browser tests replace them.

## Architecture

- A body-level native `<dialog>` owns the modal top layer, background inertness,
  and `::backdrop`. It is in the HTML before the runtime script executes.
- All Systeminfo geometry lives in `chat.css`: `inset: 0; margin: auto`,
  viewport-constrained width and dynamic maximum height, without transforms
  or `!important` overrides. All old runtime positioning rules and selectors
  were removed from the three stylesheets.
- Surface color, border, corner radius, shadow, and blurred backdrop follow
  the existing Talking Photo modal. The header stays visible while a single
  body region scrolls runtime data, response metrics, memory budget, and
  reliability diagnostics. Reliability previously appended outside that region.
- X, native Escape/cancel, backdrop click, and native `close()` share cleanup.
  Backdrop dismissal checks actual coordinates and both ends of the pointer
  gesture, so dialog padding and drags out of the dialog do not dismiss it.
- Initial focus goes to X; Tab/Shift+Tab stay inside; closing restores the
  actual launcher, including the collapsed sidebar rail. Automatic rendering
  preserves focus on the Thinking control. Runtime polling stops on close.
- Existing endpoints, runtime fields, metrics, budget/reliability refreshes,
  and the three-second runtime refresh remain in use. Changed assets have
  updated cache keys. The close control has English/German translations.

## Regression coverage

`tests/e2e/test_runtime_modal.py` runs the production app through the existing
isolated Agent harness in real Chromium. Its 20 cases cover:

- Empty and active chats, expanded desktop sidebar and collapsed icon rail,
  mobile navigation, and resizing an open desktop dialog to mobile.
- Actual visible coordinates and center on 1440 × 1000, 390 × 844,
  320 × 568, 844 × 390, and 1440 × 320 viewports.
- Scroll access to the last diagnostics section and visibility of X.
- All four closing paths, internal padding, drag-out gestures, reopening,
  keyboard focus cycling, and focus restoration.
- Runtime and response metrics, a changed Agent PID arriving automatically,
  focus preservation through refresh, and no system polling after close.
- Usable layout and closing after an invalid API response.

The Talking Photo mobile tests also open the sidebar through its visible
navigation control before clicking its launcher. Their former offscreen
clicks caused three pre-existing failures in PR #199's browser CI.

## Measured result

Representative empty-chat bounds after correction:

| Viewport | Bounds `(x, y, width, height)` |
| --- | --- |
| 1440 × 1000 | `(400, 134, 640, 732)` |
| 390 × 844 | `(16, 54.75, 358, 734.5)` |
| 320 × 568 | `(16, 16, 288, 536)` |
| 844 × 390 | `(102, 16, 640, 358)` |
| 1440 × 320 | `(400, 16, 640, 288)` |

Computed transform is `none`; automatic margins center the dialog. Content
height can change with live diagnostics; the viewport and centering assertions
run against the measured bounds rather than fixed content heights.

## Validation

- `.test-venv/bin/python -m pytest --e2e tests/e2e -q`: **78 passed** in
  118.94 seconds, including all **20 Systeminfo** and **6 Talking Photo** cases.
- `.test-venv/bin/python -m pytest -q`: **1938 passed**, **402 subtests passed**;
  one existing Starlette deprecation warning.
- `node --test tests/*.mjs`: **240 passed**.
- `python3 scripts/i18n-audit.py`: passed.
- Changed JavaScript syntax, Python test compilation, and `git diff --check`: passed.

Browser execution and socket integration tests require execution outside the
macOS filesystem sandbox; initial sandbox failures were permission failures,
not skipped tests. Browser tests validate the real frontend with deterministic
Agent data; they do not start model inference services.
