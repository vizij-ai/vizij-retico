# Brand marks

Used by `src/face/BrandMark.tsx` for the `vizij × retico` lockup in the top bar.

## vizij.png

The project's own icon, copied verbatim from
`vizij-web/apps/vizij-showcase/public/assets/vizij-icon.png` and downscaled 1024 → 128 px.
Transparent background; its shapes are mid-tone and saturated, so one file reads on both
light and dark. No variant pair needed.

## retico-on-dark.png · retico-on-light.png

Derived from the `retico-team` GitHub organisation avatar
(`https://avatars.githubusercontent.com/u/96519443`, native 381 px), which ships as an
**opaque white tile**. Two things follow from that:

- Dropping the tile means keying out the white. The artwork contains white too, so the
  outer background is removed by flood-filling from the corners, and the bubble's own
  fill is then removed separately — leaving the outline and the waveform.
- The outline is dark navy `#1a3144`, almost the value of our bar (`#0a0a0a`). Left as-is
  it is invisible on dark, so `retico-on-dark` lifts it to `#ebeef2`.

| file | outline | use on |
|---|---|---|
| `retico-on-dark.png` | near-white `#ebeef2` | dark surfaces — the app bar |
| `retico-on-light.png` | retico's navy `#1a3144` | light surfaces — docs, the paper, GitHub light mode |

Each is illegible on the other background; that is the reason both exist.

## Caveats

These are **reconstructions from a raster avatar**, not source files, and
`retico-on-dark` alters retico's mark by recolouring the outline. 381 px is also thin for
print. If the retico maintainers can supply a transparent PNG or an SVG, prefer it over
both of these — `retico-on-light` is essentially what we would be asking them for.
