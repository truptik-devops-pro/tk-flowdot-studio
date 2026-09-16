import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "tk-flowdot-studio" / "scripts" / "flowdot.py"
SPEC = importlib.util.spec_from_file_location("flowdot", SCRIPT)
flowdot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = flowdot
SPEC.loader.exec_module(flowdot)


class FlowdotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.image_path = self.root / "input.png"
        image = Image.new("RGBA", (32, 20), (250, 251, 252, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 16, 31, 19), fill=(230, 231, 232, 255))
        image.save(self.image_path)

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, value):
        path = self.root / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def run_cli(self, command, config, output, *extra):
        config_path = self.write_config(config)
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                command,
                "--image",
                str(self.image_path),
                "--config",
                str(config_path),
                "--output",
                str(output),
                *extra,
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
        )

    def base_config(self):
        return {
            "image_size": [32, 20],
            "routes": [
                {
                    "id": "main",
                    "points": [[2, 2], [28, 2]],
                    "speed": 8,
                    "diameter": 4,
                    "color": "#800020",
                }
            ],
        }

    def test_position_at_corners_diagonal_reverse_phase_and_wrap(self):
        route = flowdot.Route(
            id="corner",
            points=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)),
            phase=0.0,
            reverse=False,
            speed=5.0,
            diameter=4,
            color="#800020",
        )
        self.assertEqual(flowdot.position_at(route, 0), (0.0, 0.0))
        self.assertEqual(flowdot.position_at(route, 1), (5.0, 0.0))
        self.assertEqual(flowdot.position_at(route, 2), (10.0, 0.0))
        self.assertEqual(flowdot.position_at(route, 3), (10.0, 5.0))

        diagonal = flowdot.Route(
            id="diagonal",
            points=((0.0, 0.0), (3.0, 4.0)),
            phase=0.0,
            reverse=False,
            speed=1.0,
            diameter=2,
            color="#000000",
        )
        self.assertAlmostEqual(flowdot.position_at(diagonal, 2.5)[0], 1.5)
        self.assertAlmostEqual(flowdot.position_at(diagonal, 2.5)[1], 2.0)
        self.assertAlmostEqual(flowdot.position_at(diagonal, 5.5)[0], 0.3)
        self.assertAlmostEqual(flowdot.position_at(diagonal, 5.5)[1], 0.4)

        reversed_route = flowdot.Route(
            id="reverse",
            points=((0.0, 0.0), (10.0, 0.0)),
            phase=0.25,
            reverse=True,
            speed=2.0,
            diameter=2,
            color="#000000",
        )
        self.assertEqual(flowdot.position_at(reversed_route, 0), (2.5, 0.0))

        normalized_reverse = flowdot.normalize_config(
            {
                "image_size": [32, 20],
                "routes": [
                    {
                        "id": "normalized",
                        "points": [[0, 0], [10, 0]],
                        "reverse": True,
                        "speed": 2,
                        "phase": 0,
                    }
                ],
            },
            (32, 20),
        )[2][0]
        self.assertEqual(normalized_reverse.points, ((10.0, 0.0), (0.0, 0.0)))
        self.assertEqual(flowdot.position_at(normalized_reverse, 0), (10.0, 0.0))
        normalized_phase = flowdot.normalize_config(
            {
                "image_size": [32, 20],
                "routes": [
                    {
                        "id": "normalized-phase",
                        "points": [[0, 0], [10, 0]],
                        "reverse": True,
                        "speed": 2,
                        "phase": 0.25,
                    }
                ],
            },
            (32, 20),
        )[2][0]
        self.assertEqual(flowdot.position_at(normalized_phase, 0), (7.5, 0.0))

    def test_invalid_configs_are_rejected(self):
        invalids = [
            ("unknown", {**self.base_config(), "extra": 1}, "unknown key"),
            (
                "bool numeric",
                {**self.base_config(), "frames": True},
                "frames must be an integer",
            ),
            (
                "bad points",
                {
                    **self.base_config(),
                    "routes": [{"id": "x", "points": [[0, 0], [0, 0]]}],
                },
                "consecutive points",
            ),
            (
                "out of bounds",
                {
                    **self.base_config(),
                    "routes": [{"id": "x", "points": [[0, 0], [32, 0]]}],
                },
                "outside image bounds",
            ),
            (
                "color",
                {
                    **self.base_config(),
                    "routes": [
                        {
                            "id": "x",
                            "points": [[0, 0], [1, 1]],
                            "color": "red",
                        }
                    ],
                },
                "color must match",
            ),
            (
                "mismatched image",
                {**self.base_config(), "image_size": [31, 20]},
                "does not match input image",
            ),
            (
                "invalid phase",
                {
                    **self.base_config(),
                    "routes": [
                        {
                            "id": "x",
                            "points": [[0, 0], [1, 1]],
                            "phase": 1,
                        }
                    ],
                },
                "phase must be in [0, 1)",
            ),
            (
                "nonfinite speed",
                {
                    **self.base_config(),
                    "routes": [
                        {
                            "id": "x",
                            "points": [[0, 0], [1, 1]],
                            "speed": float("nan"),
                        }
                    ],
                },
                "invalid JSON constant",
            ),
            (
                "duplicate id",
                {
                    **self.base_config(),
                    "routes": [
                        {"id": "same", "points": [[0, 0], [1, 1]]},
                        {"id": "same", "points": [[2, 2], [3, 3]]},
                    ],
                },
                "route id must be unique",
            ),
            (
                "invalid delay",
                {**self.base_config(), "delay_ms": 25},
                "delay_ms must be a multiple",
            ),
        ]
        for name, config, expected in invalids:
            with self.subTest(name=name):
                result = self.run_cli("preview", config, self.root / f"{name}.png")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_source_and_existing_output_are_protected_on_collision_or_failure(self):
        source_before = self.image_path.read_bytes()
        config = self.base_config()

        same_as_source = self.run_cli("preview", config, self.image_path, "--force")
        self.assertNotEqual(same_as_source.returncode, 0)
        self.assertIn("same as", same_as_source.stderr)
        self.assertEqual(source_before, self.image_path.read_bytes())

        config_path = self.write_config(config)
        same_as_config = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "preview",
                "--image",
                str(self.image_path),
                "--config",
                str(config_path),
                "--output",
                str(config_path),
                "--force",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(same_as_config.returncode, 0)
        self.assertIn("same as", same_as_config.stderr)

        hardlink = self.root / "hardlink.png"
        hardlink.hardlink_to(self.image_path)
        hardlink_result = self.run_cli("preview", config, hardlink, "--force")
        self.assertNotEqual(hardlink_result.returncode, 0)
        self.assertIn("same as", hardlink_result.stderr)

        existing = self.root / "existing.png"
        existing.write_bytes(b"keep this output")
        invalid = {**config, "routes": []}
        failed = self.run_cli("preview", invalid, existing, "--force")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(existing.read_bytes(), b"keep this output")

    def test_preview_is_same_size_rgb_and_draws_overlays(self):
        output = self.root / "preview.png"
        result = self.run_cli("preview", self.base_config(), output)
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(output) as preview, Image.open(self.image_path) as source:
            self.assertEqual(preview.size, source.size)
            self.assertEqual(preview.mode, "RGB")
            self.assertEqual(preview.getpixel((31, 19)), source.convert("RGB").getpixel((31, 19)))
            self.assertNotEqual(preview.getpixel((10, 2)), source.convert("RGB").getpixel((10, 2)))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for GIF integration")
    def test_render_gif_has_exact_frames_timing_and_static_background(self):
        output = self.root / "render.gif"
        source_before = self.image_path.read_bytes()
        result = self.run_cli("render", self.base_config(), output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(source_before, self.image_path.read_bytes())
        with Image.open(output) as gif, Image.open(self.image_path) as source:
            self.assertEqual(gif.size, (32, 20))
            self.assertEqual(getattr(gif, "n_frames", 0), 150)
            self.assertEqual(gif.info.get("loop"), 0)
            durations = []
            frames = []
            for _ in range(gif.n_frames):
                durations.append(gif.info.get("duration"))
                frames.append(gif.convert("RGB").copy())
                if gif.tell() + 1 < gif.n_frames:
                    gif.seek(gif.tell() + 1)
            self.assertTrue(all(duration == 30 for duration in durations))
            self.assertEqual(frames[0].getpixel((31, 19)), source.convert("RGB").getpixel((31, 19)))
            background_strip = frames[0].crop((0, 16, 32, 20)).tobytes()
            for frame in frames[1:]:
                self.assertEqual(frame.crop((0, 16, 32, 20)).tobytes(), background_strip)
            self.assertNotEqual(frames[0].tobytes(), frames[10].tobytes())
            marker_centers = set()
            for frame in frames[:80]:
                marker_pixels = [
                    (x, y)
                    for y in range(16)
                    for x in range(32)
                    if (
                        frame.getpixel((x, y))[0] < 180
                        and frame.getpixel((x, y))[1] < 100
                        and frame.getpixel((x, y))[2] < 120
                    )
                ]
                self.assertTrue(marker_pixels)
                marker_centers.add(round(sum(x for x, _ in marker_pixels) / len(marker_pixels), 1))
            self.assertGreater(len(marker_centers), 1)


if __name__ == "__main__":
    unittest.main()
