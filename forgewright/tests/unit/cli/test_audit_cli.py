"""Tests for the ``forgewright audit`` CLI dispatcher.

Exercises the three sub-actions (verify, tail, export) via
``typer.testing.CliRunner``.

A small Typer app is constructed locally that wraps :func:`audit_command`
so the tests are decoupled from the root ``forgewright`` CLI and from
``cli/app.py`` (which depends on a number of sibling modules that may
be in flux during Phase 10 development). The audit dispatcher itself
is the unit under test, and it is identical whether it is registered
on a small app or on the root ``forgewright`` Typer.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import typer
from typer.testing import CliRunner

# --------------------------------------------------------------------------- #
# Test-time import shim.
# ``forgewright.security.__init__`` re-exports ``approval`` and ``trust``,
# which are landing in parallel during Phase 10 and may have transient
# syntax / class-definition errors. We pre-stub those names with empty
# modules so the audit module can be imported cleanly. The shim is a
# no-op once those modules are clean.
# --------------------------------------------------------------------------- #
_src_root = Path(__file__).resolve().parents[3] / "src" / "forgewright"


def _ensure_audit_module() -> types.ModuleType:
    """Return the ``forgewright.security.audit`` module, loading it
    directly from the source file if the package's normal import path
    is broken."""
    try:
        import forgewright.security.audit as _audit

        return _audit
    except Exception:  # pragma: no cover - shim path
        import importlib.util

        # Pre-stub the broken submodules so security/__init__ can import.
        for broken in ("approval", "trust"):
            mod_name = f"forgewright.security.{broken}"
            if mod_name not in sys.modules:
                stub = types.ModuleType(mod_name)
                stub.ApprovalDecision = object  # type: ignore[attr-defined]
                stub.ApprovalFlow = object  # type: ignore[attr-defined]
                stub.ApprovalResult = object  # type: ignore[attr-defined]
                stub.TrustRegistry = object  # type: ignore[attr-defined]
                stub.TrustRule = object  # type: ignore[attr-defined]
                stub.TrustScope = object  # type: ignore[attr-defined]
                stub.derive_pattern = lambda *a, **kw: ""  # type: ignore[attr-defined]
                sys.modules[mod_name] = stub

        spec = importlib.util.spec_from_file_location(
            "forgewright.security.audit",
            str(_src_root / "security" / "audit.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["forgewright.security.audit"] = mod
        spec.loader.exec_module(mod)
        return mod


_audit_mod = _ensure_audit_module()
AuditEvent = _audit_mod.AuditEvent
AuditLog = _audit_mod.AuditLog

# Now that the audit module is importable, we can pull in the CLI command.
from forgewright.cli.audit import audit_command  # noqa: E402


# Build a minimal Typer app that registers the audit command under the
# same name ("audit") as the real CLI does. We add a sibling no-op
# command so Typer treats the app as a *group* (requires the subcommand
# name to dispatch). With only one command Typer auto-dispatches and
# ignores the name.
def _noop() -> None:  # pragma: no cover - registration shim only
    """Sibling command so the app behaves as a Typer group."""


app = typer.Typer(help="forgewright test app (audit dispatcher only)")
app.command(name="audit")(audit_command)
app.command(name="_noop")(_noop)

runner = CliRunner()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _seed_audit(path: Path, n: int = 2) -> None:
    """Write ``n`` events to ``path`` for the CLI to discover."""
    log = AuditLog(path)
    for i in range(n):
        log.append(
            AuditEvent(
                ts="",
                session_id=f"s-{i}",
                type="tool",
                actor={"type": "tool", "name": "Bash", "version": "0.1.0"},
                tool="Bash",
                args={"cmd": f"echo {i}"},
                result={"exit": 0, "stdout_sha256": f"ab{i:02d}{'0' * 60}"},
            )
        )


# --------------------------------------------------------------------------- #
# --help / dispatch
# --------------------------------------------------------------------------- #


def test_audit_help_lists_subactions() -> None:
    """``audit --help`` shows the sub-action argument."""
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0
    out = (result.stdout or "") + (result.stderr or "")
    assert "verify" in out
    assert "tail" in out
    assert "export" in out
    assert "query" in out


def test_audit_unknown_action_exits_2(tmp_path: Path) -> None:
    """An unknown sub-action returns exit code 2."""
    result = runner.invoke(
        app,
        ["audit", "frobnicate", "--log", str(tmp_path / "a.jsonl")],
    )
    assert result.exit_code == 2
    out = (result.stdout or "") + (result.stderr or "")
    assert "frobnicate" in out


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #


def test_audit_verify_on_empty_log_exits_0(tmp_path: Path) -> None:
    """A freshly-created log verifies as OK (no events)."""
    path = tmp_path / "empty.jsonl"
    # Pre-create the file (empty) so the CLI doesn't accidentally
    # write to the user's real audit log.
    path.touch()

    result = runner.invoke(app, ["audit", "verify", "--log", str(path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout + (result.stderr or "")
    assert "OK" in out


def test_audit_verify_on_clean_log_exits_0(tmp_path: Path) -> None:
    """A log with 2 valid events verifies as OK."""
    path = tmp_path / "clean.jsonl"
    _seed_audit(path, n=2)

    result = runner.invoke(app, ["audit", "verify", "--log", str(path)])
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout + (result.stderr or "")
    assert "OK" in out
    assert "2" in out  # total events


def test_audit_verify_on_tampered_log_exits_nonzero(tmp_path: Path) -> None:
    """A log with a corrupted hash returns a non-zero exit code."""
    path = tmp_path / "tampered.jsonl"
    _seed_audit(path, n=2)

    # Corrupt the second event's hash on disk.
    lines = path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[1])
    obj["hash"] = "0" * 64
    lines[1] = json.dumps(obj, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = runner.invoke(app, ["audit", "verify", "--log", str(path)])
    assert result.exit_code != 0
    out = result.stdout + (result.stderr or "")
    assert "BROKEN" in out
    # The line number (1-based) is mentioned.
    assert "line 2" in out


# --------------------------------------------------------------------------- #
# tail
# --------------------------------------------------------------------------- #


def test_audit_tail_prints_table(tmp_path: Path) -> None:
    """``audit tail`` renders a table with the events."""
    path = tmp_path / "tail.jsonl"
    _seed_audit(path, n=3)

    result = runner.invoke(
        app,
        ["audit", "tail", "--log", str(path), "-n", "2"],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    out = result.stdout + (result.stderr or "")
    # Rich table column headers.
    assert "ts" in out
    assert "tool" in out
    # The last 2 events (indices 1 and 2) are visible; the first (index 0)
    # is NOT in the output.
    assert "s-1" in out
    assert "s-2" in out
    assert "s-0" not in out


def test_audit_tail_on_empty_log_is_friendly(tmp_path: Path) -> None:
    """``audit tail`` on an empty log prints a dim notice."""
    path = tmp_path / "empty.jsonl"
    path.touch()

    result = runner.invoke(app, ["audit", "tail", "--log", str(path)])
    assert result.exit_code == 0
    out = result.stdout + (result.stderr or "")
    assert "No audit events" in out


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #


def test_audit_export_jsonl_to_stdout(tmp_path: Path) -> None:
    """``audit export --format jsonl`` prints the log to stdout."""
    path = tmp_path / "export.jsonl"
    _seed_audit(path, n=2)

    result = runner.invoke(
        app,
        ["audit", "export", "--log", str(path), "--format", "jsonl"],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    # Stdout should contain two JSON lines.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2
    obj = json.loads(lines[0])
    assert obj["session_id"] == "s-0"


def test_audit_export_csv_produces_csv(tmp_path: Path) -> None:
    """``audit export --format csv`` produces a CSV."""
    path = tmp_path / "export.csv.jsonl"
    _seed_audit(path, n=2)

    result = runner.invoke(
        app,
        ["audit", "export", "--log", str(path), "--format", "csv"],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines[0] == "ts,session_id,type,tool,args,result,hash"
    assert len(lines) == 3  # header + 2 rows


def test_audit_export_to_output_file(tmp_path: Path) -> None:
    """``--output`` writes the export to a file instead of stdout."""
    path = tmp_path / "out.jsonl"
    log_path = tmp_path / "src.jsonl"
    _seed_audit(log_path, n=2)

    result = runner.invoke(
        app,
        [
            "audit",
            "export",
            "--log",
            str(log_path),
            "--format",
            "jsonl",
            "--output",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    assert path.exists()
    contents = path.read_text(encoding="utf-8")
    assert contents.count("\n") == 2
    assert "s-0" in contents
    assert "s-1" in contents


def _seed_audit_with_consent(path: Path) -> None:
    """Write events with approval metadata for query tests."""
    log = AuditLog(path)
    log.append(
        AuditEvent(
            session_id="approved-yes",
            type="tool",
            tool="Bash",
            user_consent={"approved": True},
        )
    )
    log.append(
        AuditEvent(
            session_id="approved-no",
            type="tool",
            tool="Bash",
            user_consent={"approved": False},
        )
    )


def test_audit_query_filters_jsonl_stdout(tmp_path: Path) -> None:
    """``audit query`` prints matching events as JSONL."""
    path = tmp_path / "query.jsonl"
    _seed_audit_with_consent(path)

    result = runner.invoke(
        app,
        ["audit", "query", "tool=bash AND approved=false", "--log", str(path)],
    )
    assert result.exit_code == 0, result.stdout + (result.stderr or "")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["session_id"] == "approved-no"


def test_audit_query_missing_expression_exits_2(tmp_path: Path) -> None:
    """``audit query`` without an expression returns exit code 2."""
    path = tmp_path / "q.jsonl"
    path.touch()
    result = runner.invoke(app, ["audit", "query", "--log", str(path)])
    assert result.exit_code == 2


def test_audit_query_invalid_syntax_exits_2(tmp_path: Path) -> None:
    """Malformed query expressions return exit code 2."""
    path = tmp_path / "q.jsonl"
    _seed_audit(path, n=1)
    result = runner.invoke(
        app,
        ["audit", "query", "not-a-clause", "--log", str(path)],
    )
    assert result.exit_code == 2
    out = result.stdout + (result.stderr or "")
    assert "Invalid query" in out


def test_audit_export_unknown_format_exits_2(tmp_path: Path) -> None:
    """An unknown --format returns exit code 2."""
    path = tmp_path / "src.jsonl"
    _seed_audit(path, n=1)

    result = runner.invoke(
        app,
        ["audit", "export", "--log", str(path), "--format", "otel"],
    )
    assert result.exit_code == 2
    out = result.stdout + (result.stderr or "")
    assert "otel" in out
