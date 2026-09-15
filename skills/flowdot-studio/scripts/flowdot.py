#!/usr/bin/env python3
"""Render moving dots along configured polylines over a static image."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError


DEFAULT_COLOR = "#800020"
DEFAULT_FRAMES = 150
DEFAULT_DELAY_MS = 30
SUPERSAMPLE = 4
COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\Z")


class FlowdotError(Exception):
    """An expected, user-facing flowdot error."""


def _polyline_metrics(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, ...], float]:
    cumulative = [0.0]
    for start, end in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + math.hypot(end[0] - start[0], end[1] - start[1]))
    return tuple(cumulative), cumulative[-1]


@dataclass(frozen=True)
class Route:
    """Normalized route accepted by :func:`position_at`.

    ``points`` are already in travel order.  ``position_at(route, t)`` returns
    the marker center at elapsed time ``t`` in seconds.
    """

    id: str
    points: tuple[tuple[float, float], ...]
    phase: float
    reverse: bool
    speed: float
    diameter: int
    color: str
    cumulative: tuple[float, ...] = field(default_factory=tuple, repr=False)
    total_length: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if not self.cumulative or self.total_length <= 0:
            cumulative, total = _polyline_metrics(self.points)
            object.__setattr__(self, "cumulative", cumulative)
            object.__setattr__(self, "total_length", total)


def position_at(route: Route, t: float) -> tuple[float, float]:
    """Return ``(x, y)`` at elapsed time ``t`` seconds on a normalized route."""

    if not isinstance(route, Route):
        raise TypeError("route must be a Route")
    if not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(float(t)):
        raise ValueError("time must be finite")
    length = route.total_length
    if length <= 0:
        raise ValueError("route length must be positive")
    distance = (route.phase * length + route.speed * float(t)) % length
    segment = bisect.bisect_right(route.cumulative, distance) - 1
    segment = max(0, min(segment, len(route.points) - 2))
    segment_start = route.cumulative[segment]
    segment_length = route.cumulative[segment + 1] - segment_start
    fraction = (distance - segment_start) / segment_length
    start = route.points[segment]
    end = route.points[segment + 1]
    return (
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    )


def _keys(obj: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise FlowdotError(f"{where} has unknown key(s): {', '.join(unknown)}")


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FlowdotError(f"{where} must be a number")
    if not math.isfinite(float(value)):
        raise FlowdotError(f"{where} must be finite")
    return float(value)


def _integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FlowdotError(f"{where} must be an integer")
    return value


def _color(value: Any, where: str) -> str:
    if not isinstance(value, str) or COLOR_RE.fullmatch(value) is None:
        raise FlowdotError(f"{where} must match #RRGGBB")
    return value


def _image_size(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise FlowdotError("image_size must be [width, height]")
    width = _integer(value[0], "image_size width")
    height = _integer(value[1], "image_size height")
    if width <= 0 or height <= 0:
        raise FlowdotError("image_size dimensions must be positive")
    return width, height


def _read_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant {value}")

    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream, parse_constant=reject_constant)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise FlowdotError(f"could not read config JSON: {exc}") from exc


def normalize_config(config: Any, image_size: tuple[int, int]) -> tuple[int, int, list[Route]]:
    """Validate config and return ``(frames, delay_ms, normalized_routes)``."""

    if not isinstance(config, dict):
        raise FlowdotError("config top level must be an object")
    _keys(config, {"image_size", "frames", "delay_ms", "defaults", "routes"}, "config")
    if "image_size" not in config:
        raise FlowdotError("config requires image_size")
    configured_size = _image_size(config["image_size"])
    if configured_size != image_size:
        raise FlowdotError(
            f"config image_size {configured_size} does not match input image {image_size}"
        )

    frames = _integer(config.get("frames", DEFAULT_FRAMES), "frames")
    if frames < 2:
        raise FlowdotError("frames must be at least 2")
    delay_ms = _integer(config.get("delay_ms", DEFAULT_DELAY_MS), "delay_ms")
    if delay_ms < 20 or delay_ms > 1000 or delay_ms % 10:
        raise FlowdotError("delay_ms must be a multiple of 10 from 20 to 1000")

    width, height = image_size
    max_dimension = max(width, height)
    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict):
        raise FlowdotError("defaults must be an object")
    _keys(defaults, {"speed", "diameter", "color"}, "defaults")
    default_speed = _number(defaults.get("speed", width * 320 / 1254), "defaults.speed")
    if default_speed <= 0:
        raise FlowdotError("defaults.speed must be positive")
    default_diameter = _integer(
        defaults.get("diameter", max(2, round(width * 18 / 1254))), "defaults.diameter"
    )
    if default_diameter <= 0 or default_diameter > max_dimension:
        raise FlowdotError("defaults.diameter must be positive and no larger than the image")
    default_color = _color(defaults.get("color", DEFAULT_COLOR), "defaults.color")

    raw_routes = config.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise FlowdotError("routes must be a nonempty array")

    routes: list[Route] = []
    seen_ids: set[str] = set()
    allowed_route_keys = {"id", "points", "phase", "reverse", "speed", "diameter", "color"}
    for index, raw_route in enumerate(raw_routes):
        where = f"routes[{index}]"
        if not isinstance(raw_route, dict):
            raise FlowdotError(f"{where} must be an object")
        _keys(raw_route, allowed_route_keys, where)

        route_id = raw_route.get("id")
        if not isinstance(route_id, str) or not route_id:
            raise FlowdotError(f"{where}.id must be a nonempty string")
        if route_id in seen_ids:
            raise FlowdotError(f"route id must be unique: {route_id}")
        seen_ids.add(route_id)

        raw_points = raw_route.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            raise FlowdotError(f"{where}.points must contain at least 2 points")
        points: list[tuple[float, float]] = []
        for point_index, raw_point in enumerate(raw_points):
            if not isinstance(raw_point, list) or len(raw_point) != 2:
                raise FlowdotError(f"{where}.points[{point_index}] must be [x, y]")
            x = _number(raw_point[0], f"{where}.points[{point_index}].x")
            y = _number(raw_point[1], f"{where}.points[{point_index}].y")
            if x < 0 or x >= width or y < 0 or y >= height:
                raise FlowdotError(f"{where}.points[{point_index}] outside image bounds")
            current = (x, y)
            if points and points[-1] == current:
                raise FlowdotError(f"{where} has consecutive points that are duplicates")
            points.append(current)

        phase = _number(raw_route.get("phase", 0), f"{where}.phase")
        if phase < 0 or phase >= 1:
            raise FlowdotError(f"{where}.phase must be in [0, 1)")
        reverse = raw_route.get("reverse", False)
        if not isinstance(reverse, bool):
            raise FlowdotError(f"{where}.reverse must be boolean")
        speed = _number(raw_route.get("speed", default_speed), f"{where}.speed")
        if speed <= 0:
            raise FlowdotError(f"{where}.speed must be positive")
        diameter = _integer(raw_route.get("diameter", default_diameter), f"{where}.diameter")
        if diameter <= 0 or diameter > max_dimension:
            raise FlowdotError(f"{where}.diameter must be positive and no larger than the image")
        color = _color(raw_route.get("color", default_color), f"{where}.color")

        ordered_points = tuple(reversed(points)) if reverse else tuple(points)
        routes.append(
            Route(
                id=route_id,
                points=ordered_points,
                phase=phase,
                reverse=reverse,
                speed=speed,
                diameter=diameter,
                color=color,
            )
        )
    return frames, delay_ms, routes


def _load_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as opened:
            if opened.format not in {"PNG", "JPEG"}:
                raise FlowdotError("input image must be PNG or JPEG")
            if getattr(opened, "n_frames", 1) > 1:
                raise FlowdotError("animated input images are not supported")
            rgba = opened.convert("RGBA")
            white = Image.new("RGBA", opened.size, (255, 255, 255, 255))
            return Image.alpha_composite(white, rgba).convert("RGB")
    except FlowdotError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise FlowdotError(f"could not read input image: {exc}") from exc


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]


def _draw_arrow(draw: ImageDraw.ImageDraw, route: Route, color: tuple[int, int, int]) -> None:
    end = route.points[-1]
    start = route.points[-2]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    segment_length = math.hypot(dx, dy)
    if segment_length <= 0:
        return
    ux, uy = dx / segment_length, dy / segment_length
    arrow_length = min(14.0, segment_length * 0.5)
    base = (end[0] - ux * arrow_length, end[1] - uy * arrow_length)
    wing = max(4.0, arrow_length * 0.55)
    left = (end[0] - ux * arrow_length + uy * wing, end[1] - uy * arrow_length - ux * wing)
    right = (end[0] - ux * arrow_length - uy * wing, end[1] - uy * arrow_length + ux * wing)
    draw.line((base, end), fill=color, width=3)
    draw.polygon((end, left, right), fill=color)


def make_preview(base: Image.Image, routes: Iterable[Route]) -> Image.Image:
    """Return a same-size RGB image with route guides and labels over ``base``."""

    output = base.copy().convert("RGB")
    draw = ImageDraw.Draw(output)
    width, height = output.size
    try:
        font = ImageFont.load_default(size=max(12, min(32, width // 80)))
    except TypeError:  # Pillow versions before the scalable default font.
        font = ImageFont.load_default()
    for route in routes:
        color = _rgb(route.color)
        draw.line(route.points, fill=color, width=2)
        radius = 3.0
        for x, y in route.points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        _draw_arrow(draw, route, color)
        label_x, label_y = route.points[0][0] + 4, route.points[0][1] + 4
        label_color = (35, 35, 35)
        bbox = draw.textbbox((0, 0), route.id, font=font, anchor="lt")
        label_width, label_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        label_x = min(max(0, label_x), max(0, width - label_width - 1))
        label_y = min(max(0, label_y), max(0, height - label_height - 1))
        draw.rectangle(
            (label_x - 1, label_y - 1, label_x + label_width + 1, label_y + label_height + 1),
            fill=(255, 255, 255),
        )
        draw.text((label_x, label_y), route.id, fill=label_color, font=font, anchor="lt")
    return output


def _marker_sprite(diameter: int, color: tuple[int, int, int], x: float, y: float, left: int, top: int) -> Image.Image:
    """Create one antialiased marker sprite without supersampling the canvas."""

    low_size = diameter + 2
    high_size = low_size * SUPERSAMPLE
    sprite = Image.new("RGBA", (high_size, high_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    center_x = (x - left) * SUPERSAMPLE
    center_y = (y - top) * SUPERSAMPLE
    radius = diameter * SUPERSAMPLE / 2
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill=color + (255,),
    )
    return sprite.resize((low_size, low_size), Image.Resampling.LANCZOS)


def _render_frame(base: Image.Image, routes: Iterable[Route], frame: int, delay_ms: int) -> Image.Image:
    output = base.copy().convert("RGB")
    t = frame * delay_ms / 1000.0
    for route in routes:
        x, y = position_at(route, t)
        left = math.floor(x - route.diameter / 2)
        top = math.floor(y - route.diameter / 2)
        sprite = _marker_sprite(route.diameter, _rgb(route.color), x, y, left, top)
        output.paste(sprite, (left, top), sprite)
    return output


def _output_collides(output: Path, image_path: Path, config_path: Path) -> bool:
    output_real = os.path.realpath(output)
    if output_real in {os.path.realpath(image_path), os.path.realpath(config_path)}:
        return True
    if output.exists():
        for source in (image_path, config_path):
            try:
                if source.exists() and os.path.samefile(output, source):
                    return True
            except OSError:
                pass
    return False


def _run_ffmpeg(argv: list[str], stderr_log: Path) -> None:
    try:
        with stderr_log.open("ab") as log:
            subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, stderr=log)
    except FileNotFoundError as exc:
        raise FlowdotError("ffmpeg is required for render") from exc
    except subprocess.CalledProcessError as exc:
        raise FlowdotError(
            f"ffmpeg failed with exit code {exc.returncode}: {_stderr_tail(stderr_log)}"
        ) from exc


def _stderr_tail(path: Path, limit: int = 2000) -> str:
    try:
        value = path.read_bytes()[-limit:].decode("utf-8", errors="replace").strip()
    except OSError:
        value = ""
    return value or "no ffmpeg diagnostics"


def _write_video(
    video_path: Path,
    log_path: Path,
    base: Image.Image,
    routes: list[Route],
    frames: int,
    delay_ms: int,
) -> None:
    width, height = base.size
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-framerate",
        f"1000/{delay_ms}",
        "-i",
        "pipe:0",
        "-frames:v",
        str(frames),
        "-an",
        "-c:v",
        "ffv1",
        "-pix_fmt",
        "bgr0",
        "-f",
        "matroska",
        str(video_path),
    ]
    try:
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=log,
            )
            try:
                assert process.stdin is not None
                for frame in range(frames):
                    process.stdin.write(_render_frame(base, routes, frame, delay_ms).tobytes())
                process.stdin.close()
            except BaseException:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                process.kill()
                process.wait()
                raise
            return_code = process.wait()
    except FileNotFoundError as exc:
        raise FlowdotError("ffmpeg is required for render") from exc
    except BrokenPipeError as exc:
        raise FlowdotError("ffmpeg stopped while receiving frames") from exc
    if return_code:
        raise FlowdotError(f"ffmpeg failed with exit code {return_code}: {_stderr_tail(log_path)}")


def _verify_gif(path: Path, image_size: tuple[int, int], frames: int, delay_ms: int) -> None:
    try:
        with Image.open(path) as gif:
            if gif.size != image_size:
                raise FlowdotError(f"GIF has unexpected size {gif.size}")
            if getattr(gif, "n_frames", 0) != frames:
                raise FlowdotError(f"GIF has {getattr(gif, 'n_frames', 0)} frames, expected {frames}")
            if gif.info.get("loop") != 0:
                raise FlowdotError("GIF loop count is not infinite")
            durations = []
            for index in range(frames):
                durations.append(gif.info.get("duration"))
                if index + 1 < frames:
                    gif.seek(index + 1)
            if any(duration != delay_ms for duration in durations):
                raise FlowdotError("GIF frame timing did not match delay_ms")
    except FlowdotError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise FlowdotError(f"could not verify GIF: {exc}") from exc


def render_gif(
    base: Image.Image,
    routes: list[Route],
    frames: int,
    delay_ms: int,
    output: Path,
) -> None:
    with tempfile.TemporaryDirectory(prefix=".flowdot-", dir=str(output.parent)) as temp_dir:
        temp = Path(temp_dir)
        log_path = temp / "ffmpeg.log"
        video_path = temp / "frames.mkv"
        palette_path = temp / "palette.png"
        gif_path = temp / "output.gif"
        _write_video(video_path, log_path, base, routes, frames, delay_ms)
        _run_ffmpeg(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                "palettegen=stats_mode=full",
                "-frames:v",
                "1",
                str(palette_path),
            ],
            log_path,
        )
        _run_ffmpeg(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(palette_path),
                "-filter_complex",
                "[0:v][1:v]paletteuse=dither=bayer[v]",
                "-map",
                "[v]",
                "-frames:v",
                str(frames),
                "-loop",
                "0",
                "-final_delay",
                str(delay_ms // 10),
                str(gif_path),
            ],
            log_path,
        )
        _verify_gif(gif_path, base.size, frames, delay_ms)
        os.replace(gif_path, output)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "render"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--image", required=True, type=Path)
        subparser.add_argument("--config", required=True, type=Path)
        subparser.add_argument("--output", required=True, type=Path)
        subparser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    image_path = args.image
    config_path = args.config
    output_path = args.output
    try:
        if _output_collides(output_path, image_path, config_path):
            raise FlowdotError("output path is the same as an input image or config")
        if output_path.exists() and not args.force:
            raise FlowdotError("output already exists; use --force to replace it")
        if output_path.exists() and not output_path.is_file():
            raise FlowdotError("output path is not a regular file")
        if not output_path.parent.is_dir():
            raise FlowdotError("output parent directory does not exist")

        base = _load_image(image_path)
        config = _read_json(config_path)
        frames, delay_ms, routes = normalize_config(config, base.size)
        with tempfile.TemporaryDirectory(prefix=".flowdot-", dir=str(output_path.parent)) as temp_dir:
            temp_output = Path(temp_dir) / output_path.name
            if args.command == "preview":
                make_preview(base, routes).save(temp_output, format="PNG")
                os.replace(temp_output, output_path)
                report = {
                    "command": "preview",
                    "width": base.width,
                    "height": base.height,
                    "routes": len(routes),
                    "bytes": output_path.stat().st_size,
                    "output": str(output_path),
                }
            else:
                render_gif(base, routes, frames, delay_ms, temp_output)
                os.replace(temp_output, output_path)
                report = {
                    "command": "render",
                    "width": base.width,
                    "height": base.height,
                    "frames": frames,
                    "delay_ms": delay_ms,
                    "duration_ms": frames * delay_ms,
                    "loop": 0,
                    "bytes": output_path.stat().st_size,
                    "output": str(output_path),
                }
        print(json.dumps(report, sort_keys=True))
        return 0
    except FlowdotError as exc:
        print(f"flowdot: ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"flowdot: ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
