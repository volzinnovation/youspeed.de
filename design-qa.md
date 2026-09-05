# Design QA: Active Camera Speed-Limit Indicator

## Comparison target

- Source visual truth path: `/Users/raphaelvolz/Downloads/Bildschirmfoto 2026-09-05 um 14.17.12.png` (opened in Preview because direct filesystem access is protected by macOS).
- Implementation screenshot path: `/Users/raphaelvolz/.codex/visualizations/2026/09/05/01a07172-0b78-7de3-bbe1-e2d96a03c678/camera-limit-active-final.png`.
- Viewport: iPhone 14 Pro portrait, 393 × 852 points.
- Pixel dimensions: source 1179 × 2556 pixels; implementation 1179 × 2556 pixels.
- Density normalization: both captures are @3x at identical pixel and point dimensions; no resampling was used.
- State: speed 0 km/h, active camera-derived limit 30 km/h, Lindenweg / Bad Herrenalb / Landkreis Calw, camera badge in the no-recognition state.

## Findings

- No actionable P0, P1, or P2 visual differences remain.
- The source's white left and right brackets, centered outer tips, circular white border, black numeral, sign scale, content order, and location card content are represented in the final implementation.
- The source sketch has a faint gray hand-drawn edge immediately outside part of the white sign border. This is treated as sketch residue, not a required product token; the implementation uses the requested clean white border.

## Required fidelity surfaces

- Fonts and typography: The existing SwiftUI traffic-sign numeral and app typography remain unchanged. The numeral is black in both the source and implementation, and the camera-source color override was removed. Weight, hierarchy, wrapping, and line height match the existing app screen.
- Spacing and layout rhythm: The bracket tips share the vertical center of the sign and use the same horizontal center inset as the 44-point corner controls. Each pair of lines terminates on the calculated circular boundary. The source and implementation use the same 393 × 852-point viewport.
- Colors and visual tokens: The background stays black, the regulatory red remains the existing `SpeedLimitSignPalette.borderColor`, and the active indicator and outer sign border are solid white. Contrast is high and unambiguous.
- Image quality and asset fidelity: The source contains no new photographic or raster asset. The indicator is a resolution-independent SwiftUI state shape, so its line endpoints remain attached to the responsive sign geometry without scaling artifacts.
- Copy and content: The final fixture matches `Lindenweg`, `Bad Herrenalb`, `Landkreis Calw`, and `keine Erkennung`. Production copy outside the new state indicator is unchanged.
- Icons and controls: Existing SF Symbols and 44-point control geometry are unchanged. No controls overlap or clip at the target viewport.
- Accessibility and behavior: The decorative eye lines are hidden from accessibility. When active, the sign label says the limit was adopted from the camera. The indicator is shown only when the effective speed-limit source is actually `.camera`, not when camera evidence merely exists.

## Comparison evidence

- Full-view comparison: The source and final implementation were emitted together in one comparison input from Preview at identical dimensions. Overall composition, sign placement, vertical rhythm, location card, and bottom controls align.
- Focused region comparison: A separate crop was unnecessary because the sign-and-bracket region occupies the dominant central region in both original-resolution 1179 × 2556 captures. The white border, four line attachments, two outer tips, and black numeral were inspected at original resolution.

## Comparison history

1. Initial render — blocked by P1 state mismatch: asynchronous screenshot startup replaced the synthetic camera state with an unknown limit, so the render showed a dash and no indicator. Fix: made the camera-active screenshot fixture persist through effective-state publications. Post-fix evidence: `camera-limit-active-v2.png` showed limit 30 and the active eye indicator.
2. Second render — blocked by P2 fidelity differences: the eye stroke was visibly thinner than the sketch, the district line was missing, and the camera badge said `aus`. Fixes: increased the responsive eye stroke, supplied the district in the fixture, and made the fixture's badge presentation deterministic. Post-fix evidence: `camera-limit-active-final.png` matches the target state and geometry.
3. Final render — no actionable P0/P1/P2 findings. Source and final render were compared together at the same viewport, state, pixel dimensions, and density.

## Implementation checklist

- [x] Remove camera-dependent numeral color.
- [x] Draw white left/right eye brackets to the sign boundary.
- [x] Align outer tips with the sign center and corner-control inset.
- [x] Turn the sign's outer border white while a camera limit is active.
- [x] Bind visibility to the active `.camera` effective source.
- [x] Verify an exact-size iPhone 14 Pro render against the sketch.

final result: passed
