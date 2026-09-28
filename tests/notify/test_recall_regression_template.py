"""recall.regression must carry a `reason`, and say nothing new without one.

Sediment's nightly recall job passes `reason=SEDIMENT_CI_TOKEN expired...` when
the recall run failed on auth, so the alert reads as "rotate the token" rather
than "recall collapsed to 0". The block that shows it lived only in Sediment's
vendored copy, so every sync from Harness would have deleted it (#247).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "scripts/notify/templates"
TEMPLATE = "recall_regression.md.j2"
REASON_BLOCK = "{% if reason %}\n⚠️ {{ reason }}\n{% endif %}\n"

_spec = importlib.util.spec_from_file_location("hp_notify", ROOT / "scripts/notify/notify.py")
notify = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = notify  # dataclasses look their module up here
_spec.loader.exec_module(notify)

PAYLOAD = {
    "tenant_slug": "hypeproof-lab",
    "prev_pass": 40,
    "current_pass": 0,
    "threshold": 40,
    "url": "https://example.invalid/run/1",
}


def render(payload: dict, template_dir: Path = TEMPLATES) -> str:
    return notify.render_event("recall.regression", payload, template_dir=template_dir)


def test_reason_is_shown_when_given():
    reason = "SEDIMENT_CI_TOKEN expired/invalid - rotate secret (NOT a quality regression)"
    out = render({**PAYLOAD, "reason": reason})
    assert f"⚠️ {reason}\n" in out
    # It sits right under the threshold line, before the run link.
    assert out.index("Threshold:") < out.index(reason) < out.index("[Pipeline run]")


def test_without_reason_the_output_is_unchanged(tmp_path):
    """Byte-identical to the template as it was before the block existed."""
    current = (TEMPLATES / TEMPLATE).read_text(encoding="utf-8")
    assert REASON_BLOCK in current
    (tmp_path / TEMPLATE).write_text(current.replace(REASON_BLOCK, "", 1), encoding="utf-8")

    assert render(PAYLOAD) == render(PAYLOAD, template_dir=tmp_path)
    assert "⚠️" not in render(PAYLOAD)

