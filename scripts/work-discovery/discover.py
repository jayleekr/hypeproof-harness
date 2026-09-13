#!/usr/bin/env python3
"""Read-only unmet-requirement discovery. Never infers fulfillment from issue closure."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def requirement_ids(text, inline_prefixes=()):
    # IDs are scoped by document. Voice specs use headings; other specs use tables.
    pattern = r'([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)'
    found = set(re.findall(r'^\|\s*`?' + pattern + r'`?\s*\|', text, re.M)) | set(re.findall(r'^###\s+' + pattern + r'\s*$', text, re.M))
    for prefix in inline_prefixes:
        found.update(re.findall(r'(?<![A-Za-z0-9-])' + re.escape(prefix) + r'-\d+(?![A-Za-z0-9-])', text))
    return sorted(found)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root, manifest):
    errors = []
    docs = {d['path']: d for d in manifest['documents']}
    if len(docs) != len(manifest['documents']):
        errors.append('duplicate document')
    excluded = manifest.get('excluded', {})
    discovered = {str(p.relative_to(root)) for pattern in manifest['requirement_globs'] for p in root.glob(pattern)}
    for path in sorted(discovered - docs.keys() - excluded.keys()):
        errors.append(f'unregistered document: {path}')
    for path, exclusion in excluded.items():
        if not exclusion.get('reason') or not (root / path).is_file() or digest(root / path) != exclusion.get('sha256'):
            errors.append(f'stale exclusion: {path}')
    for path, doc in docs.items():
        source = root / path
        if not source.is_file():
            errors.append(f'missing document: {path}')
            continue
        actual = requirement_ids(source.read_text(), doc.get('inline_prefixes', []))
        if not actual or actual != sorted(doc['ids']):
            errors.append(f'requirement inventory changed: {path}')
        if digest(source) != doc['sha256']:
            errors.append(f'requirement content changed: {path}')
        for key in ('intent', 'design', 'test'):
            if not doc.get(key) or not (root / doc[key]).is_file():
                errors.append(f'missing {key}: {path}')
        if not doc.get('owner'):
            errors.append(f'missing owner: {path}')
    items = {w['id']: w for w in manifest['work_items']}
    if len(items) != len(manifest['work_items']):
        errors.append('duplicate work item')
    covered = set()
    for name, item in items.items():
        for field in ('title', 'next_action', 'design_delta', 'positive_control', 'negative_control', 'evidence_required', 'issue'):
            if not item.get(field):
                errors.append(f'{name}: missing {field}')
        if item.get('kind') not in ('design', 'implementation', 'validation', 'research'):
            errors.append(f'{name}: invalid kind')
        if item.get('gate') and not item['gate'].get('reason'):
            errors.append(f'{name}: gate needs reason')
        if not item.get('requirements'):
            errors.append(f'{name}: no requirements')
        for ref in item.get('requirements', []):
            doc = docs.get(ref['path'])
            for rid in ref['ids']:
                if not doc or rid not in doc['ids']:
                    errors.append(f'{name}: unknown requirement {ref["path"]}:{rid}')
                covered.add((ref['path'], rid))
        for dep in item.get('depends_on', []):
            if dep not in items:
                errors.append(f'{name}: unknown dependency {dep}')
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            errors.append(f'dependency cycle: {name}')
            return
        if name in visited or name not in items:
            return
        visiting.add(name)
        for dep in items[name].get('depends_on', []):
            visit(dep)
        visiting.remove(name)
        visited.add(name)

    for name in items:
        visit(name)
    for path, doc in docs.items():
        for rid in doc['ids']:
            if (path, rid) not in covered:
                errors.append(f'unassigned requirement: {path}:{rid}')
    return errors


def fulfilled(root, item):
    evidence = item.get('completion')
    if not evidence or evidence.get('verdict') != 'PASS' or not evidence.get('reviewed_by'):
        return False
    # Pin all implementation/test/requirement inputs used by the verdict.
    inputs = evidence.get('inputs', {})
    required = {r['path'] for r in item['requirements']} | set(item.get('verification_inputs', [])) | {evidence.get('report', '')}
    if not item.get('verification_inputs') or not required or not required.issubset(inputs):
        return False
    report = root / evidence.get('report', '')
    return report.is_file() and bool(inputs) and all(
        (root / p).is_file() and digest(root / p) == sha for p, sha in inputs.items()
    )


def classify(root, manifest, snapshot, now):
    issues = {x['number']: x for x in snapshot['issues']}
    complete = {w['id'] for w in manifest['work_items'] if fulfilled(root, w)}
    rows = []
    for item in manifest['work_items']:
        issue = issues.get(item['issue'])
        state, reason = 'ready', item['next_action']
        if item['id'] in complete:
            state, reason = 'complete', 'Reviewed evidence inputs still match; scope limited to this packet.'
        elif issue is None:
            state, reason = 'reconcile', 'Issue is missing from the complete snapshot.'
        elif issue['state'].upper() == 'CLOSED':
            state, reason = 'reconcile', 'Closed issue has no current packet completion evidence. Inspect closure/PR; do not recreate blindly.'
        elif any(item['issue'] in p.get('issues', []) for p in snapshot.get('pull_requests', [])):
            state, reason = 'in_review', 'An open PR references this issue; inspect its remaining scope.'
        elif 'wip' in [x['name'] if isinstance(x, dict) else x for x in issue.get('labels', [])]:
            claim = issue.get('claim_at')
            if claim is None or now - datetime.fromisoformat(claim.replace('Z', '+00:00')) < timedelta(hours=24):
                state, reason = 'claimed', 'Fresh claim, or claim timestamp unavailable; inspect before taking.'
            else:
                state, reason = 'reconcile', 'Claim older than 24h; verify active writer before reclaiming.'
        elif item.get('gate'):
            state, reason = 'blocked', item['gate']['reason']
        elif any(dep not in complete for dep in item.get('depends_on', [])):
            state, reason = 'dependency', 'Unfulfilled packets: ' + ', '.join(d for d in item['depends_on'] if d not in complete)
        rows.append({**item, 'state': state, 'reason': reason})
    return rows


def gh(*args):
    return json.loads(subprocess.check_output(['gh', *args], text=True))


def live_snapshot(repo):
    pages = gh('api', '--paginate', '--slurp', f'repos/{repo}/issues?state=all&per_page=100')
    issues = [i for page in pages for i in page if 'pull_request' not in i]
    for issue in issues:
        if 'wip' in [l['name'] for l in issue['labels']]:
            pages = gh('api', '--paginate', '--slurp', f'repos/{repo}/issues/{issue["number"]}/comments?per_page=100')
            claims = [c['created_at'] for page in pages for c in page
                      if re.search(r'\bclaim(?:s|ed)?\b|작업.*(?:시작|착수)|선점', c['body'], re.I)]
            issue['claim_at'] = max(claims) if claims else None
    prs = gh('pr', 'list', '--repo', repo, '--state', 'open', '--limit', '1000',
             '--json', 'number,closingIssuesReferences')
    if len(prs) == 1000:
        raise ValueError('PR listing may be truncated')
    return {'repository': repo, 'complete': True, 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'issues': issues, 'pull_requests': [{'number': p['number'], 'issues': [i['number'] for i in p['closingIssuesReferences']]} for p in prs]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, default=Path.cwd())
    parser.add_argument('--manifest', default='config/requirement-work.json')
    parser.add_argument('--check', action='store_true', help='Offline integrity only, never a work-availability verdict')
    parser.add_argument('--snapshot', type=Path, help='Complete recorded GitHub snapshot (max age 1h)')
    parser.add_argument('--save-snapshot', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    root = args.checkout.resolve()
    manifest = json.loads((root / args.manifest).read_text())
    errors = audit(root, manifest)
    now = datetime.now(timezone.utc)
    result = {'repository': manifest['repository'], 'errors': errors, 'integrity_only': args.check}
    if not args.check:
        snapshot = json.loads(args.snapshot.read_text()) if args.snapshot else live_snapshot(manifest['repository'])
        age = now - datetime.fromisoformat(snapshot['fetched_at'].replace('Z', '+00:00'))
        if snapshot.get('repository') != manifest['repository'] or snapshot.get('complete') is not True or age > timedelta(hours=1) or age < -timedelta(minutes=5):
            raise ValueError('Wrong, incomplete or stale GitHub snapshot; availability is unknown')
        if args.save_snapshot:
            args.save_snapshot.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
        result['fetched_at'] = snapshot['fetched_at']
        result['work_items'] = classify(root, manifest, snapshot, now)
        result['counts'] = dict(Counter(w['state'] for w in result['work_items']))
        result['no_remaining_work'] = not errors and bool(result['work_items']) and all(w['state'] == 'complete' for w in result['work_items'])
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{manifest['repository']}: {len(manifest['documents'])} documents, {sum(len(d['ids']) for d in manifest['documents'])} requirements")
        for error in errors:
            print('GAP:', error)
        if args.check:
            print('Integrity only. Implementation, acceptance and work availability were not evaluated.')
        else:
            print('Counts:', result['counts'])
            for item in result['work_items']:
                print(f"[{item['state']}] {item['id']} #{item['issue']} {item['title']}\n  {item['reason']}")
            print('No remaining work:', result['no_remaining_work'])
    return 1 if errors else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f'Discovery failed; availability unknown: {exc}', file=sys.stderr)
        sys.exit(2)
