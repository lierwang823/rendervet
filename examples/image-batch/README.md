# Intentionally broken image batch

This fixture is generated entirely by `scripts/build_demo_assets.py`. It contains twelve expected
sequence positions and eleven actual files:

- `shot_004` is missing;
- `shot_006.png` is corrupt;
- `shot_008.png` has the wrong width;
- `shot_009.png` is an exact copy of `shot_003.png`;
- `shot_011.png` has a year-2000 modification time;
- `shot_012.jpg` has a disallowed extension and invalid JPEG bytes.

Run it from the repository root:

```bash
rendervet check examples/image-batch/rendervet.toml --open
```

The command should return exit code `1`; that is the expected proof that the failure gate worked.
