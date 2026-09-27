# LEVIATHAN backend host visual spec

Reference image: `tests/visual/reference/run_leviathan_1672x941.png`

Measured with `scripts/measure_reference.py` (gold border runs) plus a tighter border pass. All values are CSS pixels. The stage is exactly this coordinate system at scale 1. Other window sizes scale the stage uniformly and center it.

```
Reference: 1672x941
REFERENCE_ASPECT = 1672 / 941
```

## Frame

| Region | x | y | w | h |
| --- | ---: | ---: | ---: | ---: |
| Titlebar | 0 | 0 | 1672 | 28 |
| Banner | 0 | 28 | 1672 | 108 |
| Runtime control | 8 | 142 | 1656 | 62 |
| Service health | 8 | 210 | 1656 | 76 |
| Main row | 8 | 294 | 1656 | 328 |
| Lower row | 8 | 632 | 1656 | 269 |
| Status bar | 8 | 908 | 1656 | 28 |

Measured anchors:

- Titlebar / banner seam at y=28–29
- Banner bottom rule at y=136
- Main-row bottom near y=622
- Lower-row bottom near y=901
- Status rule at y=937
- Outer left stroke x=6, continuous y=29–626, y=644–904, y=907–936

## Columns

Main row (vertical strokes in y=310–610):

- Main console ends near x=674
- Workers begin near x=685
- Workers / overview split near x=1193–1204
- Right stroke x=1661

Track ratios used by the stage: `666 / 507 / 456`, gap 11px.

Lower row (y=640–890):

- Logs / ingestion split x=559–570
- Ingestion / native split x=1206–1218
- Right stroke x=1660

Track ratios: `551 / 635 / 442`, gap 11px.

## Color (sampled)

- Field: near `#05080b` (bins around rgb 0,8,16)
- Gold line: about rgb 154,114,63
- Ivory text: about rgb 230,220,200
- Start green and emergency red are painted in CSS, not sampled from live text

## Assets

Decorative only, under `src/assets/reference/`:

- `banner-skyline.png` — banner artwork, clock interior cleared
- `geometry-seal.png`
- `panel-texture.png` — quiet dark tile, no live text
- `corner-ornament-left.png`
- `corner-ornament-right.png`

Buttons, tables, statuses, charts, and the clock are HTML.
