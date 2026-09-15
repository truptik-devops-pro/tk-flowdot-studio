# Contributing

Useful contributions include a small reproducible bug report, a clearer route-mapping example, or a focused renderer fix.

For a bug, include your operating system, Python/Pillow/FFmpeg versions, the command, a minimal route JSON and a shareable image. Remove private information before posting assets.

For code changes, add a regression test that demonstrates the problem, keep the CLI and JSON contract documented, and run:

```bash
python -m unittest discover -s tests -v
```

Preserve source files, constant arc-length speed, fixed background content and explicit input errors. Do not introduce automatic resizing, skipped routes or sampling as silent fallbacks.

For visual changes, include the static source and resulting GIF. Inspect full resolution, mobile size and the loop boundary. Keep examples original or appropriately licensed. Use plain language and avoid em dashes in documentation.
