# Shared UI controls (v1.18 consistency pass)

The Chat UI and Control Center opt into the same **scoped** design system via
`body.nobby-ui` and `/assets/chat/ui-controls.css`. No new JavaScript
component library or network dependency is used.

## Visual tokens

- Background `--nobby-ui-control-bg` (`#141b28`)
- Border `--nobby-ui-control-border` (`#344052`)
- Text `--nobby-ui-control-text` (`#edf3fc`)
- Focus `--nobby-ui-focus` (`#82b4ff`)
- Picker popup `--nobby-ui-picker-bg` (`#172234`)
- Selected row `--nobby-ui-picker-selected` (`#243d5c`)
- Control height `--nobby-ui-control-height` (`41px`)
- Spacing `8 / 12 / 16 / 24px`

These values mirror the Media Library / Talking Photo control style. The
existing special-purpose overlays and layouts keep their original geometry.
The chat composer quality picker intentionally remains 32px high while adopting
our shared open-menu appearance.

## Native dropdowns

In Chromium and other engines supporting `appearance: base-select` and
`::picker(select)`, the popups use the consistent dark menu, selected row,
focus ring and matching anchor width.

On unsupported browsers, the real HTML `select` and `option` elements still
work with the native popup and `color-scheme: dark`. No fake dropdown JS or
event listeners are introduced. Accessibility and keyboard selection use the
browser's native implementation.

The selectors in `ui-controls.css` intentionally apply to **known modules**:

- Settings / model roles / model overview / Model Scout
- Inline chat voice and Voice Manager
- Shorts Studio / project editor
- Automations / Memory Manager
- Routing feedback / Observatory
- Notes and image/video configuration
- Control Center quantization and batch settings

Buttons preserve module-specific primary, danger and disabled behavior. Special
inputs (checkboxes, radio buttons, sliders, file uploads and color pickers)
are excluded from shared text-field styling.

## How to extend

1. Keep the existing semantic HTML (`label`, `select`, `button`,
   `input`) and event listeners.
2. Add the specific module class to the scoped selector lists in
   `frontend/assets/chat/ui-controls.css`; **do not** add unscoped global
   selectors such as `select { ... }` or replace native controls with divs.
3. Use CSS variables rather than hard-coded colors; keep sizing responsive.
4. Provide a visible focus state and an accessible name on every control.
5. Update `tests/test_ui_consistency.mjs` and browser tests for the actual
   interactive control before merging.

## Regression checks

```bash
node tests/test_ui_consistency.mjs
node --test tests/*.mjs
python -m pytest --e2e tests/e2e/test_ui_consistency.py -q
```

Review both desktop and mobile plus modal overlays with actual native popup
open. This pass changes presentation only, not API calls, model configuration,
media generation, storage or job execution.
