"""Offline terminal, JSON, HTML, and retry reports."""

from __future__ import annotations

import html
import json
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.parse import quote

from rendervet.models import BatchResult, FileRecord, Finding, ScanResult, Severity


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def render_terminal(result: ScanResult, color: bool = True) -> str:
    palette = {
        "reset": "\033[0m" if color else "",
        "bold": "\033[1m" if color else "",
        "green": "\033[32m" if color else "",
        "yellow": "\033[33m" if color else "",
        "red": "\033[31m" if color else "",
        "dim": "\033[2m" if color else "",
    }
    status = "PASS" if result.passed else "FAIL"
    status_color = palette["green"] if result.passed else palette["red"]
    lines = [
        f"{palette['bold']}RenderVet{palette['reset']}  {result.project_name}",
        f"{status_color}{palette['bold']}{status}{palette['reset']}  "
        f"{result.files} files · {result.errors} errors · {result.warnings} warnings",
        "",
    ]
    for batch in result.batches:
        icon = "✓" if batch.passed else "✗"
        icon_color = palette["green"] if batch.passed else palette["red"]
        lines.append(
            f"{icon_color}{icon}{palette['reset']} {batch.batch_id}: "
            f"{len(batch.records)} files · {batch.errors} errors · {batch.warnings} warnings"
        )
        for finding in batch.findings:
            finding_color = (
                palette["red"] if finding.severity is Severity.ERROR else palette["yellow"]
            )
            location = f" [{finding.path}]" if finding.path else ""
            lines.append(
                f"  {finding_color}{finding.severity.value.upper():7}{palette['reset']} "
                f"{finding.code}: {finding.message}{location}"
            )
    return "\n".join(lines)


def _finding_index(batch: BatchResult) -> Dict[str, List[Finding]]:
    indexed: Dict[str, List[Finding]] = {}
    for finding in batch.findings:
        if finding.path:
            indexed.setdefault(finding.path, []).append(finding)
    return indexed


def _image_uri(record: FileRecord, report_path: Path) -> str:
    relative = os.path.relpath(str(record.path), str(report_path.parent)).replace(os.sep, "/")
    return quote(relative, safe="/._-")


def _severity_badge(severity: Severity) -> str:
    return f'<span class="badge {severity.value}">{severity.value}</span>'


def _render_file_card(
    record: FileRecord,
    findings: Iterable[Finding],
    report_path: Path,
) -> str:
    finding_list = list(findings)
    severity = (
        "error"
        if any(item.severity is Severity.ERROR for item in finding_list)
        else ("warning" if finding_list else "pass")
    )
    preview = ""
    if record.media.kind == "image" and record.media.probe == "native":
        preview = (
            f'<img loading="lazy" src="{_image_uri(record, report_path)}" '
            f'alt="Preview of {html.escape(record.relative_path)}">'
        )
    else:
        preview = f'<div class="file-icon">{html.escape(record.media.kind.upper())}</div>'
    issues = (
        "".join(
            f"<li>{_severity_badge(item.severity)} <code>{html.escape(item.code)}</code> "
            f"{html.escape(item.message)}</li>"
            for item in finding_list
        )
        or '<li><span class="badge pass">pass</span> Contract checks passed</li>'
    )
    sequence = "—" if record.sequence_number is None else str(record.sequence_number)
    return f"""
    <article class="file-card {severity}" data-status="{severity}">
      <div class="preview">{preview}</div>
      <div class="file-body">
        <h4 title="{html.escape(record.relative_path)}">{html.escape(record.relative_path)}</h4>
        <p class="meta">#{sequence} · {human_bytes(record.size)} · {html.escape(record.media.summary())}</p>
        <ul>{issues}</ul>
        <p class="hash">sha256 {record.sha256[:12]}…</p>
      </div>
    </article>
    """


def render_html(result: ScanResult, report_path: Path) -> str:
    status = "PASS" if result.passed else "FAIL"
    batch_sections: List[str] = []
    for batch in result.batches:
        indexed = _finding_index(batch)
        cards = "".join(
            _render_file_card(record, indexed.get(record.relative_path, []), report_path)
            for record in batch.records
        )
        missing_cards = "".join(
            f"""
            <article class="file-card error" data-status="error">
              <div class="preview missing">MISSING</div>
              <div class="file-body"><h4>Sequence #{number}</h4>
              <ul><li>{_severity_badge(Severity.ERROR)} Expected output is missing</li></ul></div>
            </article>
            """
            for number in batch.missing_sequence_numbers
        )
        record_paths = {record.relative_path for record in batch.records}
        general_findings = [
            item for item in batch.findings if not item.path or item.path not in record_paths
        ]
        finding_rows = (
            "".join(
                f"<tr><td>{_severity_badge(item.severity)}</td>"
                f"<td><code>{html.escape(item.code)}</code></td>"
                f"<td><code>{html.escape(item.path) if item.path else '—'}</code></td>"
                f"<td>{html.escape(item.message)}</td></tr>"
                for item in general_findings
            )
            or '<tr><td colspan="4" class="muted">No batch-level findings.</td></tr>'
        )
        batch_sections.append(
            f"""
            <section>
              <div class="section-title">
                <div><h2>{html.escape(batch.batch_id)}</h2><code>{html.escape(batch.matched_glob)}</code></div>
                <strong class="batch-status {"pass" if batch.passed else "error"}">
                  {"PASS" if batch.passed else "FAIL"}
                </strong>
              </div>
              <table><thead><tr><th>Severity</th><th>Code</th><th>Path</th><th>Finding</th></tr></thead>
              <tbody>{finding_rows}</tbody></table>
              <div class="file-grid">{missing_cards}{cards}</div>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RenderVet · {html.escape(result.project_name)}</title>
<style>
:root{{--bg:#0b1020;--panel:#121a2d;--panel2:#172238;--text:#edf3ff;--muted:#94a3b8;
--line:#283650;--pass:#35d07f;--warn:#f6c453;--error:#ff6b6b;--accent:#7aa2ff}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(145deg,#08101f,#11192b 60%,#0c1424);
color:var(--text);font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1240px;margin:auto;padding:40px 24px 80px}} h1,h2,h4,p{{margin-top:0}} h1{{font-size:40px;margin-bottom:4px}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#c9d7f2}} .eyebrow{{color:var(--accent);font-weight:700;letter-spacing:.12em;text-transform:uppercase}}
.hero{{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}} .run-meta{{color:var(--muted);text-align:right}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}} .metric{{background:rgba(18,26,45,.9);border:1px solid var(--line);border-radius:16px;padding:18px}}
.metric strong{{display:block;font-size:30px}} .metric span{{color:var(--muted)}} .metric.status strong.pass{{color:var(--pass)}} .metric.status strong.error{{color:var(--error)}}
.filters{{display:flex;gap:8px;margin:20px 0}} button{{border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--text);padding:8px 14px;cursor:pointer}}
button.active{{border-color:var(--accent);background:#20335d}} section{{background:rgba(18,26,45,.84);border:1px solid var(--line);border-radius:18px;padding:22px;margin:20px 0}}
.section-title{{display:flex;align-items:center;justify-content:space-between;gap:16px}} .batch-status{{border-radius:999px;padding:7px 12px}} .batch-status.pass{{background:#163c2a;color:var(--pass)}} .batch-status.error{{background:#4b2027;color:#ff9b9b}}
table{{border-collapse:collapse;width:100%;margin:16px 0 22px}} th,td{{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}} th{{color:var(--muted);font-size:12px;text-transform:uppercase}}
.file-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}} .file-card{{overflow:hidden;border:1px solid var(--line);border-radius:14px;background:var(--panel2)}}
.file-card.error{{border-color:#7e3038}} .file-card.warning{{border-color:#6b5523}} .preview{{height:150px;background:#0b1221;display:grid;place-items:center;overflow:hidden}}
.preview img{{width:100%;height:100%;object-fit:cover}} .preview.missing{{color:#ff9b9b;font-weight:800;letter-spacing:.12em;background:repeating-linear-gradient(135deg,#251821,#251821 10px,#321b25 10px,#321b25 20px)}}
.file-icon{{color:var(--muted);font-size:20px;font-weight:800}} .file-body{{padding:14px}} .file-body h4{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:5px}}
.meta,.hash,.muted{{color:var(--muted)}} .hash{{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;margin-bottom:0}} ul{{padding-left:18px;margin:10px 0}}
.badge{{display:inline-block;border-radius:6px;padding:1px 6px;font-size:10px;font-weight:800;text-transform:uppercase}} .badge.error{{background:#4b2027;color:#ff9b9b}}
.badge.warning{{background:#4a3b1c;color:#ffd978}} .badge.pass{{background:#163c2a;color:#78e7ab}} footer{{color:var(--muted);text-align:center;margin-top:32px}}
@media(max-width:720px){{.hero{{display:block}}.run-meta{{text-align:left}}.summary{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body><main>
<div class="hero"><div><div class="eyebrow">Batch preflight report</div><h1>RenderVet</h1>
<p>{html.escape(result.project_name)}</p></div><div class="run-meta">{html.escape(result.generated_at.isoformat())}<br>local root: .</div></div>
<div class="summary">
  <div class="metric status"><strong class="{"pass" if result.passed else "error"}">{status}</strong><span>overall status</span></div>
  <div class="metric"><strong>{result.files}</strong><span>files inspected</span></div>
  <div class="metric"><strong>{result.errors}</strong><span>errors</span></div>
  <div class="metric"><strong>{result.warnings}</strong><span>warnings</span></div>
</div>
<div class="filters" aria-label="Filter files"><button class="active" data-filter="all">All</button><button data-filter="error">Errors</button><button data-filter="warning">Warnings</button><button data-filter="pass">Passed</button></div>
{"".join(batch_sections)}
<footer>Generated locally by RenderVet. No media was uploaded or modified.</footer>
</main>
<script>
for (const button of document.querySelectorAll('[data-filter]')) {{
  button.addEventListener('click', () => {{
    document.querySelectorAll('[data-filter]').forEach(x => x.classList.remove('active'));
    button.classList.add('active'); const wanted = button.dataset.filter;
    document.querySelectorAll('.file-card').forEach(card => {{
      card.style.display = wanted === 'all' || card.dataset.status === wanted ? '' : 'none';
    }});
  }});
}}
</script>
</body></html>"""


def build_retry_manifest(result: ScanResult) -> Dict[str, object]:
    batches: List[Dict[str, object]] = []
    for batch in result.batches:
        failures: List[Dict[str, object]] = []
        for number in batch.missing_sequence_numbers:
            failures.append(
                {
                    "sequence_number": number,
                    "path": None,
                    "reasons": ["sequence_item_missing"],
                }
            )
        by_path = _finding_index(batch)
        for path in batch.retry_paths:
            reasons = sorted(
                {item.code for item in by_path.get(path, []) if item.severity is Severity.ERROR}
            )
            failures.append({"sequence_number": None, "path": path, "reasons": reasons})
        if failures:
            batches.append({"id": batch.batch_id, "failures": failures})
    return {
        "version": 1,
        "project": result.project_name,
        "generated_at": result.generated_at.isoformat(),
        "root": ".",
        "batches": batches,
    }


def _atomic_write(path: Path, content: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError(f"refusing unsafe report target: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def _reject_symlink_components(path: Path) -> None:
    """Reject existing symlinks anywhere in an absolute directory path."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode):
            raise OSError("refusing report directory with symlink component")


def write_reports(result: ScanResult, report_dir: Path) -> Tuple[Path, Path, Path]:
    report_dir = Path(os.path.abspath(os.fspath(report_dir)))
    _reject_symlink_components(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(report_dir)
    html_path = report_dir / "report.html"
    json_path = report_dir / "report.json"
    retry_path = report_dir / "retry-manifest.json"
    _reject_symlink_components(report_dir)
    _atomic_write(html_path, render_html(result, html_path))
    _reject_symlink_components(report_dir)
    _atomic_write(
        json_path,
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
    )
    _reject_symlink_components(report_dir)
    _atomic_write(
        retry_path,
        json.dumps(build_retry_manifest(result), indent=2, ensure_ascii=False) + "\n",
    )
    return html_path, json_path, retry_path
