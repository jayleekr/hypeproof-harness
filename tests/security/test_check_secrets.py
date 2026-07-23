from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "security" / "check-secrets.sh"

# Synthetic, non-functional credential shaped like a Google OAuth client secret.
# Never a real value; only its *shape* is what the scanner keys on.
SYNTHETIC_SECRET = "GOCSPX-" + "Z" * 32


def run_scan(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--files", *[str(path) for path in paths]],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_clean_placeholders_pass(tmp_path: Path) -> None:
    sample = tmp_path / ".env.example"
    sample.write_text(
        "\n".join(
            [
                "AUTH_GOOGLE_SECRET=your-google-client-secret",
                "OPENAI_API_KEY=replace-with-openai-key",
                "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY=replace-with-service-account-private-key",
            ]
        ),
        encoding="utf-8",
    )

    proc = run_scan(sample)

    assert proc.returncode == 0, proc.stderr


def test_google_oauth_client_secret_is_blocked_without_echoing_value(tmp_path: Path) -> None:
    secret = "GOCSPX-" + "A" * 32
    leaked = tmp_path / "announcement.txt"
    leaked.write_text(f"client_secret={secret}\n", encoding="utf-8")

    proc = run_scan(leaked)

    assert proc.returncode == 1
    assert "Google OAuth client secret" in proc.stderr
    assert secret not in proc.stderr


def test_real_looking_secret_in_example_file_is_still_blocked(tmp_path: Path) -> None:
    secret = "sk-" + "B" * 40
    example = tmp_path / ".env.example"
    example.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")

    proc = run_scan(example)

    assert proc.returncode == 1
    assert "OpenAI API key" in proc.stderr
    assert secret not in proc.stderr


def test_runbook_secret_is_not_excluded(tmp_path: Path) -> None:
    secret = "GOCSPX-" + "C" * 32
    runbook = tmp_path / "docs" / "runbooks" / "oauth.md"
    runbook.parent.mkdir(parents=True)
    runbook.write_text(f"Do not paste real secrets: {secret}\n", encoding="utf-8")

    proc = run_scan(runbook)

    assert proc.returncode == 1
    assert "Google OAuth client secret" in proc.stderr
    assert secret not in proc.stderr


def test_pem_private_key_header_is_blocked_without_echoing_value(tmp_path: Path) -> None:
    # Use a non-dangerous filename so the content pattern (not the path rule) is exercised.
    body = "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "b3BlbnNzaC1rZXk" + "\n"
    leaked = tmp_path / "notes.txt"
    leaked.write_text(body, encoding="utf-8")

    proc = run_scan(leaked)

    assert proc.returncode == 1, proc.stderr
    assert "PEM private key" in proc.stderr
    assert "b3BlbnNzaC1rZXk" not in proc.stderr


def test_plain_pem_private_key_header_is_blocked(tmp_path: Path) -> None:
    # No algorithm token -> exercises the optional group + leading-dash pattern handling.
    leaked = tmp_path / "leaked-key.txt"
    leaked.write_text("-----BEGIN PRIVATE KEY-----\nMIIabc\n", encoding="utf-8")

    proc = run_scan(leaked)

    assert proc.returncode == 1, proc.stderr
    assert "PEM private key" in proc.stderr


def test_discord_webhook_url_is_blocked_without_echoing_value(tmp_path: Path) -> None:
    token = "A" * 40
    url = f"https://discord.com/api/webhooks/123456789012345678/{token}"
    leaked = tmp_path / "webhook-notes.txt"
    leaked.write_text(f"DISCORD_WEBHOOK={url}\n", encoding="utf-8")

    proc = run_scan(leaked)

    assert proc.returncode == 1, proc.stderr
    assert "Discord webhook URL" in proc.stderr
    assert token not in proc.stderr


def test_dangerous_credential_path_is_blocked(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SAFE_PLACEHOLDER=1\n", encoding="utf-8")

    proc = run_scan(env_file)

    assert proc.returncode == 1
    assert "dangerous credential path" in proc.stderr


# ---------------------------------------------------------------------------
# Hermeticity regression: the git-enumeration modes (staged/--diff/--working-tree)
# must not depend on the ambient `core.quotePath`. These exercise the real
# enumeration path — not --files — by giving the script its own fixture repo as
# REPO_ROOT and forcing the hostile stock-CI default core.quotePath=true.
# ---------------------------------------------------------------------------


def _make_repo_with_script(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "security").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "security" / "check-secrets.sh")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    # Emulate a stock CI runner: core.quotePath defaults to TRUE there. The old
    # scanner only worked because a workstation's *global* config set it false.
    subprocess.run(["git", "config", "core.quotepath", "true"], cwd=repo, check=True)
    return repo


def _run_staged(repo: Path) -> subprocess.CompletedProcess[str]:
    script = repo / "scripts" / "security" / "check-secrets.sh"
    return subprocess.run(
        ["bash", str(script), "staged"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def test_non_ascii_named_secret_is_caught_under_quotepath_true(tmp_path: Path) -> None:
    # THE regression. Before the fix, under core.quotePath=true a secret in a
    # Korean-named file was word-split into a non-existent path and skipped, so
    # the scan reported "no secrets" (exit 0) — a false green. It must be caught.
    repo = _make_repo_with_script(tmp_path)
    (repo / "한글비밀.txt").write_text(
        f"client_secret={SYNTHETIC_SECRET}\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    proc = _run_staged(repo)

    assert proc.returncode == 1, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "한글비밀.txt" in proc.stderr
    assert "Google OAuth client secret" in proc.stderr
    # The matched value is never echoed, on either stream.
    assert SYNTHETIC_SECRET not in proc.stdout + proc.stderr


def test_space_bearing_named_secret_is_caught(tmp_path: Path) -> None:
    # NUL-delimited enumeration also fixes names with spaces, which the old
    # `set -- $files` split on IFS.
    repo = _make_repo_with_script(tmp_path)
    (repo / "my secret notes.txt").write_text(
        f"client_secret={SYNTHETIC_SECRET}\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    proc = _run_staged(repo)

    assert proc.returncode == 1, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "my secret notes.txt" in proc.stderr


def test_clean_non_ascii_tree_still_passes(tmp_path: Path) -> None:
    # Control against over-firing: a Korean-named file with no secret must PASS,
    # so the guard is not merely failing on every non-ASCII name.
    repo = _make_repo_with_script(tmp_path)
    (repo / "한글문서.md").write_text("# 제목\n본문\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    proc = _run_staged(repo)

    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_enumeration_mode_reports_control_invariant(tmp_path: Path) -> None:
    # The scan announces what it pinned, so any CI log shows it did not inherit
    # the ambient git config.
    repo = _make_repo_with_script(tmp_path)
    (repo / "readme.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    proc = _run_staged(repo)

    assert "core.quotePath=pinned-false" in proc.stderr
    assert "enumeration=NUL" in proc.stderr
