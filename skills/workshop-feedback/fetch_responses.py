#!/usr/bin/env python3
"""Read Google Form responses via a token — no browser, no human babysitting.

Given a sheet manifest and a credential, pulls each form's linked response sheet
through the Sheets REST API and reports counts (and optionally rows). This is the
automation half of workshop-feedback: forms are built by build-forms.gs, responses
are collected here, then mapped to workshop.yaml for the result-report pipeline.

Credential (issuing it is a HUMAN step — cap.governance: credential issuance is
human-only; this script only *consumes* one):
  * Service account (recommended, headless/cron): set GOOGLE_APPLICATION_CREDENTIALS
    to the key path, and share each response sheet with the SA email (Viewer).
  * ADC fallback: `gcloud auth application-default login
    --scopes=https://www.googleapis.com/auth/spreadsheets.readonly`.

Manifest (json), per engagement — see engagements/<date>/forms/sheets.manifest.json:
  {"engagement":"...","forms":[{"name":"사전","sheet_id":"...","internal_only":false}, ...]}

Privacy: `internal_only` forms (연락처) are counted but their rows are NOT dumped
unless --include-internal is passed — keeps the contact track out of casual output.

Usage:
  python3 fetch_responses.py --manifest sheets.manifest.json          # counts
  python3 fetch_responses.py --manifest sheets.manifest.json --dump   # + rows (json)
  python3 fetch_responses.py --manifest sheets.manifest.json --key /path/sa.json

Exit codes: 0 ok · 1 config error · 2 auth/credential error · 3 API/permission error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import quote

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
API = "https://sheets.googleapis.com/v4/spreadsheets"


def _load_dotenv(path: str = os.path.expanduser("~/.env")) -> None:
    """Load GOOGLE_* keys from ~/.env into os.environ if not already set.
    Minimal KEY=VALUE parser (no export/quote gymnastics beyond trimming)."""
    if not os.path.exists(path):
        return
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("GOOGLE_") and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass  # ~/.env is best-effort; explicit env/--key still win


def _session():
    """Authorized session from (in order): --key path, GOOGLE_APPLICATION_CREDENTIALS
    path, GOOGLE_SERVICE_ACCOUNT_JSON inline JSON (fits ~/.env), or ADC."""
    _load_dotenv()
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"ERROR: google-auth 없음: {e}\n")
        sys.exit(2)

    key = _KEY_OVERRIDE or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    inline = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if key:
        if not os.path.exists(key):
            sys.stderr.write(f"ERROR: 서비스계정 키 파일 없음: {key}\n")
            sys.exit(2)
        creds = service_account.Credentials.from_service_account_file(key, scopes=SCOPES)
    elif inline:
        try:
            info = json.loads(inline)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"ERROR: GOOGLE_SERVICE_ACCOUNT_JSON 파싱 실패(한 줄 JSON이어야 함): {e}\n")
            sys.exit(2)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        try:
            import google.auth
            creds, _ = google.auth.default(scopes=SCOPES)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(
                "ERROR: 자격증명 없음. ~/.env(또는 환경변수)에 다음 중 하나를 두세요:\n"
                "   GOOGLE_APPLICATION_CREDENTIALS=/경로/sa-key.json   (키 파일 경로)\n"
                "   GOOGLE_SERVICE_ACCOUNT_JSON={...한 줄 JSON...}       (키 내용 통짜)\n"
                "  또는 `gcloud auth application-default login --scopes=.../spreadsheets.readonly`.\n"
                f"       ({e})\n")
            sys.exit(2)
    return AuthorizedSession(creds)


_KEY_OVERRIDE = None


def _first_tab_title(sess, sid: str) -> str:
    r = sess.get(f"{API}/{sid}", params={"fields": "sheets.properties.title"})
    if r.status_code == 403:
        raise PermissionError(f"403 — 이 시트가 서비스계정과 공유되지 않았습니다 (Viewer로 공유 필요): {sid}")
    if r.status_code == 404:
        raise FileNotFoundError(f"404 — 시트 ID를 찾을 수 없습니다: {sid}")
    r.raise_for_status()
    sheets = r.json().get("sheets", [])
    if not sheets:
        raise ValueError(f"시트에 탭이 없습니다: {sid}")
    return sheets[0]["properties"]["title"]


def _values(sess, sid: str, title: str) -> list[list]:
    rng = quote(f"'{title}'")
    r = sess.get(f"{API}/{sid}/values/{rng}")
    r.raise_for_status()
    return r.json().get("values", [])


def main(argv=None) -> int:
    global _KEY_OVERRIDE
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, help="폼별 sheet_id manifest json")
    ap.add_argument("--key", help="서비스계정 키 경로 (또는 env GOOGLE_APPLICATION_CREDENTIALS)")
    ap.add_argument("--dump", action="store_true", help="응답 행도 json으로 출력")
    ap.add_argument("--include-internal", action="store_true",
                    help="internal_only(연락처) 행까지 출력 (기본: 카운트만)")
    args = ap.parse_args(argv)
    _KEY_OVERRIDE = args.key

    try:
        man = json.loads(open(args.manifest, encoding="utf-8").read())
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"ERROR: manifest 읽기 실패: {e}\n")
        return 1
    forms = man.get("forms") or []
    if not forms:
        sys.stderr.write("ERROR: manifest에 forms 없음\n")
        return 1

    sess = _session()
    out = {"engagement": man.get("engagement"), "forms": []}
    rc = 0
    for f in forms:
        name, sid = f.get("name"), f.get("sheet_id")
        internal = bool(f.get("internal_only"))
        rec = {"name": name, "internal_only": internal}
        try:
            title = _first_tab_title(sess, sid)
            rows = _values(sess, sid, title)
            n = max(0, len(rows) - 1)  # minus header
            rec["responses"] = n
            rec["last_timestamp"] = rows[-1][0] if n > 0 else None
            if args.dump and (not internal or args.include_internal):
                rec["header"] = rows[0] if rows else []
                rec["rows"] = rows[1:] if n > 0 else []
            elif args.dump and internal:
                rec["rows"] = "REDACTED (internal_only — --include-internal 필요)"
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)
            rc = 3
        out["forms"].append(rec)

    # Human-readable summary to stderr, machine json to stdout.
    for rec in out["forms"]:
        tag = " [internal]" if rec["internal_only"] else ""
        if "error" in rec:
            sys.stderr.write(f"  ✗ {rec['name']}{tag}: {rec['error']}\n")
        else:
            ts = rec.get("last_timestamp") or "-"
            sys.stderr.write(f"  ✓ {rec['name']}{tag}: {rec['responses']}건 (마지막 {ts})\n")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
