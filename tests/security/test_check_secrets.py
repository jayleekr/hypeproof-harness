from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "security" / "check-secrets.sh"


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
