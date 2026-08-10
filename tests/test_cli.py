from __future__ import annotations

from pathlib import Path

from rendervet.cli import main


def test_init_creates_contract_without_overwriting(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path), "--name", "Example"]) == 0
    contract = tmp_path / "rendervet.toml"
    assert contract.is_file()
    assert (tmp_path / "outputs").is_dir()
    assert main(["init", str(tmp_path), "--name", "Example"]) == 2


def test_demo_returns_validation_failure_and_writes_reports(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    assert main(["demo", "--output", str(output)]) == 1
    assert (output / ".rendervet" / "report.html").is_file()
    assert (output / ".rendervet" / "retry-manifest.json").is_file()


def test_bad_contract_returns_config_error(tmp_path: Path) -> None:
    contract = tmp_path / "rendervet.toml"
    contract.write_text("version = 999\n", encoding="utf-8")
    assert main(["check", str(contract), "--no-color"]) == 2


def test_demo_force_refuses_unmarked_directory(tmp_path: Path) -> None:
    output = tmp_path / "important"
    output.mkdir()
    protected = output / "keep.txt"
    protected.write_text("keep me", encoding="utf-8")
    assert main(["demo", "--output", str(output), "--force"]) == 2
    assert protected.read_text(encoding="utf-8") == "keep me"
