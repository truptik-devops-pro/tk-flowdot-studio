# Demo assets

- `demo.svg`: original editable vector artwork, 1200 by 800.
- `demo.png`: raster source used by the renderer.
- `demo.json`: measured straight, bent and sampled curved paths.
- `routes-preview.png`: diagnostic overlay for reviewing the measured paths.
- `demo.gif`: rendered result with 150 frames and 30 ms per frame.

The three routes have distinct constant speeds so each completes exactly two traversals during the 4.5-second clip. This makes this demo periodic at its global loop boundary. Arbitrary routes do not automatically have this property.

The curved line is a cubic curve in the artwork and is approximated by 60 short segments in the route JSON. The renderer itself consumes only polyline points.

To reproduce the GIF, run the README quick-start command with this PNG and JSON. The artwork and configuration are covered by the repository's MIT License.
