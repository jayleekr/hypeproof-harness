"""Canonical sync must preserve Lab channel names; no outbound network."""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_channel_name_survives_router_and_transport(tmp_path):
    notify = load("notify_bot_name_test", ROOT / "scripts/notify/notify.py")
    transport = notify._load_transport("discord_webhook", ROOT / "scripts/notify/transports")
    payloads = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            payloads.append(json.loads(kwargs["content"]))
            return type("Response", (), {"status_code": 204})()
    routes = tmp_path / "routes.yaml"
    template = tmp_path / "notice.md.j2"
    template.write_text("synthetic test")
    for configured, env, expected in [("HypeProof Lab", "Global", "HypeProof Lab"), (None, "Global", "Global"), (None, "", None)]:
        channel = {"transport": "discord_webhook", "url": "https://notify.invalid"}
        if configured: channel["bot_name"] = configured
        routes.write_text(json.dumps({"version": 1, "channels": {"lab": channel}, "routes": {"*": {"test": {"channels": ["lab"], "template": "notice"}}}}))
        with patch.object(transport.httpx, "AsyncClient", Client), patch.dict(os.environ, {"HP_NOTIFY_BOT_NAME": env}):
            result = asyncio.run(notify.notify(event_type="test", routes_path=routes, template_dir=tmp_path))
        assert result.error is None
        assert result.routes_fired[0].status == "sent"
        assert payloads[-1].get("username") == expected
        if expected is None: assert "username" not in payloads[-1]
