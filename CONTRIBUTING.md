# Contributing to RenderVet

RenderVet is deliberately narrow: it verifies whether a rendered batch is mechanically complete
and within declared constraints. It does not score aesthetics or run generation services.

## Development setup

```bash
git clone https://github.com/lierwang823/rendervet.git
cd rendervet
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check src tests
.venv/bin/pytest
```

On Windows, replace `.venv/bin/` with `.venv\Scripts\`.

## Pull requests

1. Open or reference an issue for behavior changes.
2. Keep source-media handling local and read-only.
3. Add deterministic tests using self-created or clearly licensed fixtures.
4. Add new report fields without leaking absolute paths or media contents.
5. Update the contract reference and changelog when user-visible behavior changes.

New reason codes should be lower-case snake case and tested in both JSON and retry output.

## Good first contributions

- Additional native image header fixtures.
- Platform-specific FFmpeg installation notes.
- Example contracts for real, openly documented render-folder conventions.
- Accessibility and small-screen improvements to the offline report.

Do not contribute copyrighted media, credentials, tracking code, or integrations that rely on
unauthorized platform access.
