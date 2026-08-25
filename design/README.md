# Design

UI design work for LocalChat, as source files. Two canvases live here.

| Directory | What it is |
|---|---|
| `localchat-ui/` | Three minimal directions for the chat screen, next to a faithful reproduction of the current UI. The decision record. |
| `quiet-utility/` | The chosen direction (**A · Quiet Utility**) built out across Chat, Documents, Models and Settings, plus a design-system sheet. |

## What is tracked, and what is not

Each directory holds `*.dc.html` artboards and a `canvas.json` layout. **Those are
the source and are tracked.** The seeded `localchat-*.html` page is ~2 MB of
generated editor code rebuilt from them, and is git-ignored, as is
`from-canvas/` — scratch from reading a published canvas back.

To change a design, edit the `.dc.html` file and re-seed. Never edit the seeded
page: it is output.

## Direction A in one paragraph

Hierarchy comes from type and whitespace. No cards, no shadows, no gradients —
hairlines separate, and the reading column is capped at 680px so long grounded
answers stay comfortable. One accent (`oklch(0.55 0.07 200)`), low chroma, no
second hue. Instrument Sans at two weights. Citations are numbered footnotes
under a rule rather than filled badges.

`System.dc.html` carries the tokens, the type ramp, every control state, the
geometry, and — more useful for implementation — the list of specific rules in
`static/css/style.css` this direction **removes**. Each entry on that list was
checked against the stylesheet rather than asserted.

## Fidelity

Static mockups. Toggles and menus are drawn in their states, not operable.

Content is read from the real application — parameter names and defaults from
`src/config.py`, screen anatomy from `templates/` — not invented. Illustrative
values (VRAM figures, model names, document counts) are mock data for fields
that genuinely exist. Where the app has no such concept, nothing is drawn:
an earlier draft invented a storage-quota bar from a misread Settings card
title, and it was removed rather than kept as decoration.

## Status

The direction is settled; nothing here is implemented. Adopting it means
rewriting `static/css/style.css` and the four templates, which is not scheduled
and belongs behind the [PRODUCTION_PLAN](../docs/PRODUCTION_PLAN.md) exit
criteria like every other non-defect change.
