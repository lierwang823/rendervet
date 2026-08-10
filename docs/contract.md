# RenderVet contract reference

RenderVet contracts are TOML files with `version = 1`, one `[project]` table, and one or
more `[[batch]]` tables. Unknown keys are rejected so a misspelling cannot silently disable a
check. Relative paths are resolved from the contract file.

## Project table

```toml
[project]
name = "Nightly thumbnails"
root = "outputs"
report_dir = ".rendervet"
fresh_after = "2026-08-10T00:00:00Z"
```

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Human-readable report name |
| `root` | no | Directory scanned by batch globs; default `.` |
| `report_dir` | no | Offline report destination; default `.rendervet` |
| `fresh_after` | no | ISO-8601 threshold applied to every batch unless overridden |

## Batch table

```toml
[[batch]]
id = "clips"
glob = "clip_*.mp4"
kind = "video"
expected_count = 10
sequence_regex = 'clip_(\d+)'
sequence_start = 1
sequence_end = 10
allowed_extensions = [".mp4"]
min_bytes = 100000
max_bytes = 500000000
width = 1080
height = 1920
min_duration = 2.0
max_duration = 30.0
require_audio = true
duplicates = "error"
fresh_after = "2026-08-10T09:00:00+08:00"
```

| Key | Default | Meaning |
| --- | --- | --- |
| `id` | required | Unique batch identifier |
| `glob` | required | Glob evaluated inside `project.root` |
| `kind` | `auto` | `auto`, `image`, `audio`, `video`, or `file` |
| `expected_count` | unset | Exact number of matching files |
| `sequence_regex` | unset | Python regex with the numeric value in capture group 1 |
| `sequence_start` | unset | First expected sequence number, inclusive |
| `sequence_end` | unset | Last expected sequence number, inclusive |
| `allowed_extensions` | any | Case-normalized extension allowlist |
| `min_bytes` | `1` | Inclusive minimum file size |
| `max_bytes` | unset | Inclusive maximum file size |
| `width` | unset | Exact encoded width for images/video |
| `height` | unset | Exact encoded height for images/video |
| `min_duration` | unset | Inclusive audio/video duration in seconds |
| `max_duration` | unset | Inclusive audio/video duration in seconds |
| `require_audio` | `false` | Require an audio stream in audio/video files |
| `duplicates` | `error` | `error`, `warning`, or `ignore` for exact SHA-256 groups |
| `fresh_after` | project value | Per-batch ISO-8601 freshness threshold |

Sequence bounds must be set together and require `sequence_regex`. The glob must be relative
and may not contain `..`. RenderVet does not follow symbolic links.

## Media support

Image structure and dimensions are read natively for PNG, JPEG, GIF, WebP, and BMP. Audio and
video probing invokes `ffprobe` as an argument array with a fixed timeout and without a shell.
If a contract requires audio/video inspection and `ffprobe` is unavailable, that file receives
`media_probe_failed`.

## Report and retry schema

`report.json` and `retry-manifest.json` both contain `version = 1` and relative input paths.
Reason codes are stable within the major schema version. Missing numbered outputs are represented
by their sequence number; invalid existing outputs include their relative path and error codes.

The retry manifest is descriptive data. RenderVet never executes it or calls a generation service.
