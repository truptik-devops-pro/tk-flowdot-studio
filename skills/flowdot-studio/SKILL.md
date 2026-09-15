---
name: flowdot-studio
description: Use when animating arrows, connector lines, or paths in an existing diagram image with moving flow dots and exporting a GIF. Supports measured straight and bent paths, plus curves traced as closely spaced points, while keeping the original artwork still.
---

# FlowDot Studio

Turn a static diagram into a flow-dot GIF. Inspect the image, map its connector centreline, then use the bundled deterministic renderer. This skill does not automatically detect arrows or redraw artwork.

## Inspect and map

1. Open the actual input image and record its pixel dimensions. Keep the source unchanged. The renderer accepts static PNG and JPEG; export other formats to a separate PNG first. Transparent pixels are composited onto white.
2. Identify the requested arrows or lines and their direction. Follow visible arrowheads or the user's instruction. If direction is genuinely ambiguous, ask one focused question; do not infer traffic semantics from proximity alone.
3. Read [references/config.md](references/config.md). Write a JSON file with the original image dimensions and one route per continuous connector. Coordinates use the original image pixels, with `(0,0)` at the top left. Each route is an ordered list of centreline points. Include every corner; trace curves with enough points to keep the overlay on the visible line. Split branches into separate routes.
4. Choose a dot colour with contrast against the line and background. Default diameter is about 1.4% of image width; default speed is about 25.5% of image width per second. User instructions override these defaults. Keep frame displacement roughly half a dot diameter or less for overlapping, smooth motion. A line crossing is not automatically a junction.

## Preview and render

Resolve `SKILL_DIR` to this skill's installed directory. Use a Python environment with `requirements.txt` installed and `ffmpeg` on PATH. No API key is needed for rendering.

```bash
python "$SKILL_DIR/scripts/flowdot.py" preview \
  --image diagram.png --config routes.json --output routes-preview.png
python "$SKILL_DIR/scripts/flowdot.py" render \
  --image diagram.png --config routes.json --output diagram-flow.gif
```

Inspect the route preview before rendering. Check every route's centreline, endpoints and direction at full resolution. Correct the JSON if any overlay cuts a corner, crosses a label, or follows the wrong connector. Preview markings are diagnostic only; they do not appear in the GIF.

If the user requested animation, proceed after this inspection. If the user requested preview only or explicitly asked to approve it first, show that exact preview and wait. Do not impose the original NGINX template's approval gate on unrelated images.

Use a new output filename for revisions. `--force` explicitly replaces an existing output, but cannot overwrite the source image or config. Never modify the source to remove stationary dots without permission; explain that existing dots will remain in the artwork.

## Verify and deliver

- Reopen the GIF and inspect its first, middle, last and loop-boundary frames. Inspect a mobile-scale preview too.
- Confirm dimensions, frame count, per-frame delay, total duration and infinite loop metadata. The renderer checks these before writing its final output; this does not replace visual inspection.
- Check every marker stays on its intended centreline and travels in the correct direction. Text, icons, arrowheads, baseline lines and background must remain still.
- Deliver the GIF, original-resolution static image, route JSON and, when useful, the diagnostic preview. Report the actual dimensions, frame count, duration and file size.
- Explain material limits: GIF reduces colours to a shared palette; curves are polyline approximations; independent routes wrap at endpoints and may visibly reset at the global GIF boundary. Do not promise a seamless loop without verifying that all route periods align with the clip duration.

## Motion contract

Dots move at constant distance per second, independent of route length. They do not all share one traversal duration. `reverse` reverses the point order before applying phase. Only dot overlays move, with a clean copy of the base used for each frame. The renderer streams frames through a lossless intermediate and uses one shared GIF palette to avoid palette drift.
