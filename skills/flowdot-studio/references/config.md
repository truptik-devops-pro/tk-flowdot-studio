# Route configuration

Coordinates belong to the full-resolution image. The origin is the top left: x increases rightward, y downward. Paths are polylines, not SVG path strings.

## Complete minimal example

For an 800 by 400 image with a bent connector:

```json
{
  "image_size": [800, 400],
  "frames": 150,
  "delay_ms": 30,
  "defaults": {"speed": 200, "diameter": 12, "color": "#800020"},
  "routes": [
    {
      "id": "client-to-service",
      "points": [[100, 140], [380, 140], [380, 260], [700, 260]],
      "phase": 0.0,
      "reverse": false
    }
  ]
}
```

This is an illustrative route. Measure coordinates from your own image before using it.

## Fields

| Field | Meaning | Default or constraint |
| :--- | :--- | :--- |
| `image_size` | `[width, height]` of source image | Required; exact positive integers |
| `frames` | Output frame count | 150; integer at least 2 |
| `delay_ms` | Time each GIF frame remains visible | 30; integer multiple of 10, from 20 to 1000 |
| `defaults.speed` | Distance travelled per second in pixels | `width * 320 / 1254`; finite and positive |
| `defaults.diameter` | Dot diameter in pixels | `max(2, round(width * 18 / 1254))`; positive integer, at most the larger image dimension |
| `defaults.color` | Dot colour | `#800020`; six hex digits |
| `routes` | Nonempty list of connectors | One moving dot per route |
| `routes[].id` | Unique route label for preview | Required nonempty string |
| `routes[].points` | Ordered `[x, y]` centreline points | At least two; finite and inside the image; no adjacent duplicates |
| `routes[].phase` | Starting fraction of total path length | 0; at least 0 and less than 1 |
| `routes[].reverse` | Reverse point order before phase | `false`; boolean |
| `routes[].speed`, `diameter`, `color` | Override defaults for this route | Same validation as defaults |

Unknown keys are rejected so spelling mistakes cannot silently change an animation. Numeric booleans, NaN and infinity are invalid. A dot can clip at the canvas boundary when its centre is in bounds but its radius reaches outside.

## Map a line accurately

- **Straight or diagonal:** two points, source then destination.
- **Bent:** put a point at every corner. Do not replace a bend with a diagonal shortcut.
- **Curved:** add closely spaced points along the visible centreline. Add more where curvature is stronger. Inspect the overlay at full resolution. Native Bézier commands are not accepted.
- **Branching:** create separate routes for each continuous branch. Dots are independent; this does not simulate packet conservation or synchronized arrivals.
- **Crossing:** stay on the chosen connector. Crossing lines need not be connected.
- **Reverse:** set `reverse: true` or reverse the points, not both. Phase zero starts at the reversed endpoint.
- **Several dots on one line:** duplicate its points with distinct IDs and phases such as `0.0`, `0.33`, `0.66`.

Stop the centreline before labels or icons if the dot would cover them. Existing arrowheads and any stationary dots remain part of the source.

## Speed, timing and loops

At time `t`, travelled distance is `(phase * path_length + speed * t) % path_length`. Position is interpolated along the segment containing that distance. A 100 px and 400 px route at 200 px/s take 0.5 s and 2 s respectively. Equal speed does not mean equal traversal time.

Duration is `frames * delay_ms / 1000`. Defaults produce 4.5 seconds at 33.33 frames/s. GIF stores time in centiseconds, so the renderer accepts exact multiples of 10 ms. Slower playback may be preferable for presentations.

For overlapping dot positions between frames, use `speed * delay_ms / 1000 <= diameter / 2`. This is a visual guideline, not an enforced limit.

Routes wrap from their end to their start. The entire GIF also restarts. A periodic boundary requires `speed * duration / path_length` to be an integer for each route. Do not change the requested physical speed silently to achieve this. A closed path may repeat its first point at the end, provided adjacent points differ.

## Image and output handling

Static PNG and JPEG are accepted. Export SVG, PDF or other formats to a separate PNG at your intended output resolution first. Animated inputs are rejected. Alpha is flattened onto white. GIF has a limited palette, so RGB source colours may shift; the same shared palette is used across frames.

The CLI refuses to overwrite an existing file unless `--force` is given. Input image and configuration files are protected even with `--force`. The renderer needs temporary disk space for a lossless intermediate video and cleans up after itself. Frames are streamed rather than kept as a full uncompressed sequence in memory.
