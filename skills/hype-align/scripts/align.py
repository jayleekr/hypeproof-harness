#!/usr/bin/env python3
"""hype-align: one run, one verdict over a product requirement ledger.

  next    rank ready work items and name the single next one
  record  write a completion record for one work item into the ledger (never commits)
  check   verify each item's intent -> requirement -> design -> test -> implementation (-> Lab) chain
  drift   compare the Lab member catalog with the Studio requirement inventory

The ledger is loaded, audited, classified and judged complete by the canonical Harness
scripts/work-discovery/discover.py. This file adds ranking, recording and link checks on
top of it; it does not interpret the ledger a second way. Rules: references/ledger-contract.md.

Exit codes: 0 verdict holds, 1 negative verdict (gap, broken link, drift, refusal),
2 could not evaluate (missing checkout, unreadable file, outdated Harness).
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

MANIFEST = 'config/requirement-work.json'
TESTING_GLOB = 'docs/testing/**/*.md'
REQUIREMENT_DIR = 'docs/requirements'
PLAN_DIR = 'docs/plan'
LAB_CATALOG = 'web/scripts/lib/studio_catalog.mjs'
LAB_DATA = 'web/src/content/private/studio-prd'
UNRANKED = 99  # sorts an item without a priority or week tag after every tagged one


class Refusal(Exception):
    """A negative verdict on the request itself (exit 1), not a failure to evaluate (exit 2)."""


# --- canonical discovery engine -------------------------------------------------------------

def harness_candidates():
    here = Path(__file__).resolve()
    # Running inside the Harness itself: use the discover.py shipped in the same revision.
    yield here.parents[3]
    configured = os.environ.get('HYPEPROOF_HARNESS')
    if configured:
        yield Path(configured).expanduser()
    # A vendored copy in a product repo: the Harness checkout next to that repo.
    proc = subprocess.run(['git', '-C', str(here.parent), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                          capture_output=True, text=True, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        yield Path(proc.stdout.strip()).parent.parent / 'hypeproof-harness'


@functools.lru_cache(maxsize=None)
def discovery():
    for root in harness_candidates():
        script = root / 'scripts/work-discovery/discover.py'
        if script.is_file():
            spec = importlib.util.spec_from_file_location('hype_align_discover', script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, 'load_snapshot'):
                raise FileNotFoundError(f'{script} predates hype-align; update that Harness checkout to current main')
            return module
    raise FileNotFoundError('canonical Harness scripts/work-discovery/discover.py not found; '
                            'set HYPEPROOF_HARNESS to a hypeproof-harness checkout')


# --- requirement and test text --------------------------------------------------------------

ID = r'[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+'  # the first-column shape discover.requirement_ids accepts
ROW = re.compile(r'^\|\s*`?(' + ID + r')`?\s*\|(.*)$', re.M)
# An ID token plus shorthand continuations: CA-T16/17, SX-T02·03, SX-T52~57, MC-21–25.
TOKEN = re.compile(r'(?<![A-Za-z0-9-])([A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*)-(T?)(\d+)(?![A-Za-z0-9])'
                   r'((?:\s*(?:/|·|~|–|\.\.)\s*T?\d+(?![A-Za-z0-9]))*)')
PART = re.compile(r'(/|·|~|–|\.\.)\s*T?(\d+)')
PRIORITY = re.compile(r'^\s*P(\d)(?![\d-])')
WEEK = r'(?:(?:[Ww]eek\s*|W)(\d+)|(\d+)\s*주차)(?!\d)'
WEEK_TAG = re.compile(r'(?<![A-Za-z0-9-])' + WEEK)
WEEK_CELL = re.compile(r'^\s*' + WEEK + r'(?:\s*[,/·~–-]\s*' + WEEK + r')*\s*$')
# String.prototype.trim() whitespace, spelled as code points so no invisible character sits in the source.
JS_WHITESPACE = ' \t\n\r\x0b\x0c' + ''.join(map(chr, (0xA0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF)))


def expand(match):
    prefix, test, first, rest = match.groups()
    numbers = [int(first)]
    for separator, value in PART.findall(rest):
        value = int(value)
        if separator in ('~', '–', '..') and 0 < value - numbers[-1] <= 200:
            numbers.extend(range(numbers[-1] + 1, value + 1))
        else:
            numbers.append(value)
    return [f'{prefix}-{test}{str(n).zfill(len(first))}' for n in numbers]


def tokens(text, tests_only=False):
    return {token for match in TOKEN.finditer(text or '') if not tests_only or match.group(2) == 'T'
            for token in expand(match)}


def weeks(text, pattern):
    return [int(a or b) for a, b in pattern.findall(text)]


def table_rows(text):
    rows = {}
    for rid, rest in ROW.findall(text):
        cells = [cell.strip() for cell in rest.split('|')]
        if cells and not cells[-1]:
            cells.pop()
        rows.setdefault(rid, []).append(cells)
    return rows


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# --- product checkout -----------------------------------------------------------------------

class Ledger:
    """A product checkout and its config/requirement-work.json, read through discover.py."""

    def __init__(self, root):
        self.d = discovery()
        self.root = Path(root).expanduser().resolve()
        if not (self.root / MANIFEST).is_file():
            raise FileNotFoundError(f'{self.root / MANIFEST} not found; pass the product checkout that owns the ledger')
        self.manifest = self.d.load_manifest(self.root, MANIFEST)
        self.docs = {doc['path']: doc for doc in self.manifest['documents']}
        self.items = self.manifest['work_items']
        self.index = {item['id']: n for n, item in enumerate(self.items)}

    def exists(self, rel):
        return bool(rel) and (self.root / rel).exists()

    def is_file(self, rel):
        return bool(rel) and (self.root / rel).is_file()

    @functools.lru_cache(maxsize=None)
    def text(self, rel):
        path = self.root / rel
        return path.read_text(encoding='utf-8') if path.is_file() else None

    @functools.lru_cache(maxsize=None)
    def rows(self, rel):
        return table_rows(self.text(rel) or '')

    @functools.cached_property
    def testing_docs(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.glob(TESTING_GLOB) if p.is_file())

    @functools.cached_property
    def test_ids(self):
        """Defined test IDs: any `-T<n>` token, or the first cell of a table row, in a testing document.

        A registered test document outside docs/testing (tests hosted in a requirement document)
        contributes only its `-T<n>` tokens, so a requirement ID never defines itself as a test.
        """
        defined = set()
        for rel in self.testing_docs:
            text = self.text(rel) or ''
            defined |= tokens(text, tests_only=True) | {rid for rid, _ in ROW.findall(text)}
        for doc in self.manifest['documents']:
            if self.is_file(doc.get('test')) and doc['test'] not in self.testing_docs:
                defined |= tokens(self.text(doc['test']), tests_only=True)
        return defined

    @functools.cached_property
    def testing_mentions(self):
        return set().union(set(), *(tokens(self.text(rel)) for rel in self.testing_docs))

    @functools.cached_property
    def unambiguous_prefixes(self):
        owners = {}
        for doc in self.manifest['documents']:
            for rid in doc['ids']:
                owners.setdefault(rid.rsplit('-', 1)[0], set()).add(doc['path'])
        return {prefix for prefix, paths in owners.items() if len(paths) == 1}

    def reverse_linked(self, path, rid):
        """A testing document names the requirement.

        Its registered test document always counts. Any docs/testing document counts when the ID's
        prefix belongs to one registered document, so the mention cannot mean another family's ID.
        Tests hosted in the requirement document count on a line that also names a test ID.
        """
        test = self.docs[path].get('test')
        if test and test != path and rid in tokens(self.text(test)):
            return True
        if rid.rsplit('-', 1)[0] in self.unambiguous_prefixes and rid in self.testing_mentions:
            return True
        if test == path:
            for line in (self.text(path) or '').splitlines():
                own = ROW.match(line)
                if (not own or own.group(1) != rid) and rid in tokens(line) and tokens(line, tests_only=True):
                    return True
        return False

    def facts(self, path, rid):
        """(priority, week, cited test IDs) from the requirement's table row(s)."""
        priority = week = None
        cited = set()
        for cells in self.rows(path).get(rid, []):
            for cell in cells:
                found = PRIORITY.match(cell)
                if found and priority is None:
                    priority = int(found.group(1))
                    tagged = weeks(cell, WEEK_TAG)
                    week = min(tagged) if tagged and week is None else week
                if week is None and WEEK_CELL.match(cell):
                    week = min(weeks(cell, WEEK_TAG))
                cited |= tokens(cell, tests_only=True)
        return priority, week, sorted(cited)

    def item_facts(self, item):
        priorities, tagged, cited = [], [], set()
        for ref in item.get('requirements', []):
            if ref['path'] not in self.docs:
                continue
            for rid in ref['ids']:
                priority, week, tests = self.facts(ref['path'], rid)
                priorities += [priority] if priority is not None else []
                tagged += [week] if week is not None else []
                cited |= set(tests)
        explicit = item.get('curriculum_week')
        if explicit is not None:
            tagged = [int(w) for w in (explicit if isinstance(explicit, list) else [explicit])]
        return (min(priorities) if priorities else None, min(tagged) if tagged else None, sorted(cited))

    def depths(self):
        """Longest depends_on chain above each item across the whole ledger (0 for a root)."""
        memo = {}

        def depth(name, trail):
            if name in memo:
                return memo[name]
            if name in trail:  # a cycle; discover.audit reports it
                return 0
            deps = [dep for dep in self.items[self.index[name]].get('depends_on', []) if dep in self.index]
            memo[name] = 1 + max((depth(dep, trail | {name}) for dep in deps), default=-1)
            return memo[name]

        return {item['id']: depth(item['id'], frozenset()) for item in self.items}

    def select(self, items, args):
        wanted_items = set(args.item or [])
        unknown = wanted_items - set(self.index)
        if unknown:
            raise Refusal('unknown work item: ' + ', '.join(sorted(unknown)))
        docs = set(args.doc or [])

        def cites(item):
            return any(ref['path'] in docs or Path(ref['path']).name in docs or Path(ref['path']).stem in docs
                       for ref in item.get('requirements', []))

        return [item for item in items
                if (not wanted_items or item['id'] in wanted_items)
                and (not docs or cites(item))
                and (not args.prefix or any(item['id'].startswith(p) for p in args.prefix))]


def studio_root(args):
    root = args.studio or os.environ.get('HYPEPROOF_STUDIO')
    if not root:
        raise FileNotFoundError('pass --studio <product checkout> or set HYPEPROOF_STUDIO')
    return root


def offline_snapshot(manifest, now):
    """Every tracked issue open, no PRs: the ledger-only view. Claims and PRs are NOT known."""
    numbers = sorted({item['issue'] for item in manifest['work_items'] if isinstance(item.get('issue'), int)})
    return {'repository': manifest['repository'], 'complete': True, 'fetched_at': now.isoformat(),
            'issues': [{'number': n, 'state': 'OPEN', 'labels': []} for n in numbers], 'pull_requests': []}


def emit(args, payload, lines):
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print('\n'.join(lines))


# --- next -----------------------------------------------------------------------------------

def label(priority, week):
    return f"P{priority if priority is not None else '?'} week {week if week is not None else '-'}"


def cmd_next(args):
    ledger = Ledger(studio_root(args))
    d, now = ledger.d, datetime.now(timezone.utc)
    gaps = d.audit(ledger.root, ledger.manifest)
    if args.live or args.snapshot:
        snapshot = d.load_snapshot(ledger.manifest, now, args.snapshot)
        availability = f"checked at {snapshot['fetched_at']}"
    else:
        snapshot = offline_snapshot(ledger.manifest, now)
        availability = 'unchecked (ledger only; open PRs and claims not read)'
    rows = ledger.select(d.classify(ledger.root, ledger.manifest, snapshot, now), args)
    depth = ledger.depths()
    ranked = []
    for row in rows:
        if row['state'] != 'ready':
            continue
        priority, week, _ = ledger.item_facts(row)
        ranked.append({'id': row['id'], 'issue': row['issue'], 'title': row['title'], 'kind': row['kind'],
                       'depth': depth[row['id']], 'priority': priority, 'week': week,
                       'ledger_index': ledger.index[row['id']], 'next_action': row['next_action'],
                       'requirements': row['requirements'], 'depends_on': row.get('depends_on', []),
                       'reason': row['reason']})
    ranked.sort(key=lambda r: (r['depth'], UNRANKED if r['priority'] is None else r['priority'],
                               UNRANKED if r['week'] is None else r['week'], r['ledger_index']))
    for position, entry in enumerate(ranked, 1):
        entry['rank'] = position
    counts = dict(sorted(Counter(row['state'] for row in rows).items()))
    chosen = ranked[0] if ranked else None
    if gaps:
        verdict = f'reconcile the requirement ledger first ({len(gaps)} gaps); the ranking below is advisory'
    elif chosen:
        verdict = f"next is {chosen['id']} (#{chosen['issue']})"
    else:
        verdict = 'no ready item in scope; this is not evidence that the scope is complete'
    payload = {'repository': ledger.manifest['repository'], 'checkout': str(ledger.root),
               'availability': availability, 'scope_items': len(rows), 'counts': counts,
               'ledger_gaps': gaps, 'next': chosen, 'ranked': ranked, 'verdict': verdict}
    lines = [f"hype-align next · {ledger.manifest['repository']} · {len(rows)} of {len(ledger.items)} items in scope",
             f'availability: {availability}',
             'states: ' + (', '.join(f'{k} {v}' for k, v in counts.items()) or 'none')]
    lines += [f'GAP: {gap}' for gap in gaps]
    if chosen:
        lines += [f"NEXT: {chosen['id']} #{chosen['issue']} [{chosen['kind']}] {chosen['title']}",
                  f"  {label(chosen['priority'], chosen['week'])} · depth {chosen['depth']}",
                  f"  next_action: {chosen['next_action']}"]
    else:
        lines.append('NEXT: none')
    if ranked:
        lines.append('Ranked ready items (depth, priority, week, ledger order):')
        lines += [f"  {r['rank']:>2}. {r['id']} #{r['issue']} · depth {r['depth']} · {label(r['priority'], r['week'])} · {r['title']}"
                  for r in ranked]
    lines.append(f'Verdict: {verdict}')
    emit(args, payload, lines)
    return 1 if gaps else 0


# --- check ----------------------------------------------------------------------------------

class Lab:
    """The Lab member feature catalog: features.ts (hand-written) and work.json (synced)."""

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        data = self.root / LAB_DATA
        self.features = parse_features((data / 'features.ts').read_text(encoding='utf-8'))
        if not self.features:
            raise ValueError(f'no feature definitions found in {data / "features.ts"}')
        self.work = json.loads((data / 'work.json').read_text(encoding='utf-8')).get('features', {})

    def link(self, item):
        for feature, entries in sorted(self.work.items()):
            for entry in entries:
                if entry.get('id') == item['id'] or entry.get('issue') == item.get('issue'):
                    return f'work.json {feature}'
        cited = {}
        for ref in item.get('requirements', []):
            cited.setdefault(Path(ref['path']).stem, set()).update(ref['ids'])
        for feature, sources in self.features.items():
            for slug, ids in sources:
                if slug in cited and (ids is None or cited[slug] & set(ids)):
                    return f'features.ts {feature}'
        return None


def item_links(ledger, item, lab=None):
    """(broken links, warnings) for one work item's alignment chain."""
    broken, warnings = [], []

    def add(bucket, kind, detail):
        entry = {'item': item['id'], 'kind': kind, 'detail': detail}
        if entry not in bucket:
            bucket.append(entry)

    has_test_link = False
    for ref in item.get('requirements', []):
        path, doc = ref['path'], ledger.docs.get(ref['path'])
        if doc is None:
            add(broken, 'requirement-doc', f'{path} is not a registered requirement document')
            continue
        text = ledger.text(path)
        if text is None:
            add(broken, 'requirement-doc', f'{path} does not exist')
            continue
        for key, kind in (('intent', 'intent'), ('design', 'design'), ('test', 'test-doc')):
            if not ledger.is_file(doc.get(key)):
                add(broken, kind, f"{path}: {key} document {doc.get(key) or '(unset)'} does not exist")
        defined = set(ledger.d.requirement_ids(text, doc.get('inline_prefixes', [])))
        for rid in ref['ids']:
            if rid not in defined:
                add(broken, 'requirement', f'{rid} is not defined in {path}')
                continue
            _, _, cited = ledger.facts(path, rid)
            for test in cited:
                if test not in ledger.test_ids:
                    add(broken, 'test-id', f'{rid} cites {test}, which no testing document defines')
            linked = bool(cited) or ledger.reverse_linked(path, rid)
            has_test_link |= linked
            if not linked:
                add(warnings, 'untested-requirement', f"{rid}: its row cites no test ID and {doc.get('test')} does not name it")
    completion = item.get('completion')
    if completion:
        recorded = completion.get('test_ids') or []
        has_test_link |= bool(recorded)
        if not recorded:
            add(broken, 'completion', 'completion records no test_ids')
        for test in recorded:
            if test not in ledger.test_ids:
                add(broken, 'completion', f'recorded test {test} is not defined in any testing document')
        if not ledger.is_file(completion.get('report')):
            add(broken, 'completion', f"evidence {completion.get('report') or '(unset)'} does not exist")
        elif not ledger.d.fulfilled(ledger.root, item):
            add(broken, 'completion', 'completion no longer holds (scope, inputs or evidence changed); verify again and re-record')
        paths = item.get('implementation_paths') or []
        if not paths:
            add(broken, 'implementation', 'completed item lists no implementation_paths')
        for rel in paths:
            if not ledger.exists(rel):
                add(broken, 'implementation', f'{rel} does not exist')
    if item.get('requirements') and not has_test_link:
        add(broken, 'test-link', 'no cited requirement has a test ID or a testing document that names it')
    if lab is not None:
        if not lab.link(item):
            ids = [rid for ref in item.get('requirements', []) for rid in ref['ids']]
            shown = ', '.join(ids[:3]) + (f' or {len(ids) - 3} more' if len(ids) > 3 else '')
            add(broken, 'lab', f"Lab work.json and features.ts link neither issue #{item.get('issue')} nor {shown}")
        for feature in item.get('feature_ids') or []:
            if feature not in lab.features:
                add(broken, 'lab-feature', f'feature {feature} is not defined in Lab features.ts')
    return broken, warnings


def cmd_check(args):
    ledger = Ledger(studio_root(args))
    lab = Lab(args.lab) if args.lab else None
    items = ledger.select(ledger.items, args)
    broken, warnings = [], []
    for item in items:
        b, w = item_links(ledger, item, lab)
        broken += b
        warnings += w
    failing = sorted({b['item'] for b in broken}, key=ledger.index.get)
    verdict = (f'{len(broken)} broken links in {len(failing)} of {len(items)} items' if broken
               else f'chain intact for {len(items)} items')
    payload = {'repository': ledger.manifest['repository'], 'checkout': str(ledger.root),
               'lab': str(lab.root) if lab else None, 'items_checked': len(items), 'ok': not broken,
               'broken': broken, 'warnings': warnings, 'verdict': verdict}
    lines = [f"hype-align check · {ledger.manifest['repository']} · {len(items)} items · "
             f"lab: {lab.root if lab else 'not checked (pass --lab)'}"]
    for name in failing:
        lines.append(f'BROKEN {name}')
        lines += [f"  {b['kind']}: {b['detail']}" for b in broken if b['item'] == name]
    untested = Counter(w['item'] for w in warnings)
    if untested:
        lines.append(f'warning: {sum(untested.values())} cited requirements without a test link in {len(untested)} items '
                     '(see --json warnings)')
    lines.append(f'Verdict: {verdict}')
    emit(args, payload, lines)
    return 1 if broken else 0


# --- record ---------------------------------------------------------------------------------

def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False)


def inside(ledger, rel, what):
    if not rel:
        raise Refusal(f'{what} is required')
    path = (ledger.root / rel).resolve()
    try:
        relative = str(path.relative_to(ledger.root))
    except ValueError:
        raise Refusal(f'{what} {rel} is outside the checkout; commit it into the product repository') from None
    if not path.is_file():
        raise Refusal(f'{what} {rel} is not a file in the checkout')
    return relative


def pr_number(value):
    if value is None:
        return None
    found = re.fullmatch(r'#?(\d+)|https://github\.com/[^/]+/[^/]+/pull/(\d+)/?', value.strip())
    if not found:
        raise Refusal(f'--pr {value} is not a PR number or URL')
    return int(found.group(1) or found.group(2))


def cmd_record(args):
    ledger = Ledger(studio_root(args))
    d = ledger.d
    if args.item not in ledger.index:
        raise Refusal(f'unknown work item: {args.item}')
    item = ledger.items[ledger.index[args.item]]
    tests = sorted({t.strip() for group in args.tests or [] for t in group.split(',') if t.strip()})
    if not tests:
        raise Refusal('--tests is required: name the test IDs whose results this completion rests on')
    unknown = [t for t in tests if t not in ledger.test_ids]
    if unknown:
        raise Refusal('test IDs not defined in any testing document: ' + ', '.join(unknown))
    report = inside(ledger, args.evidence, '--evidence')
    if report == MANIFEST:
        raise Refusal('--evidence cannot be the ledger itself')
    if not (args.reviewed_by or '').strip():
        raise Refusal('--reviewed-by is required: the independent reviewer of this verdict')
    if not re.fullmatch(r'[0-9a-f]{7,40}', args.commit or ''):
        raise Refusal('--commit must be a 7-40 character hexadecimal commit SHA')
    if git(ledger.root, 'rev-parse', '--is-inside-work-tree').returncode == 0 and \
            git(ledger.root, 'cat-file', '-e', f'{args.commit}^{{commit}}').returncode != 0:
        raise Refusal(f'commit {args.commit} is not in this checkout; fetch it or use a checkout that contains the merge')
    if item.get('completion') and not args.replace:
        raise Refusal(f'{args.item} already has a completion record; pass --replace to supersede it')
    candidate = copy.deepcopy(item)
    inputs = list(candidate.get('verification_inputs') or [])
    for extra in args.input or []:
        rel = inside(ledger, extra, '--input')
        if rel not in inputs:
            inputs.append(rel)
    if not inputs:
        raise Refusal(f'{args.item} has no verification_inputs; pass --input for the implementation and test files verified')
    for rel in inputs:
        if not ledger.is_file(rel):
            raise Refusal(f'verification input {rel} is not a file in the checkout')
    candidate['verification_inputs'] = inputs
    pinned = sorted({ref['path'] for ref in candidate['requirements']} | set(inputs) | {report})
    completion = {'verdict': 'PASS', 'reviewed_by': args.reviewed_by.strip(), 'report': report,
                  'scope_sha256': d.scope_digest(candidate),
                  'inputs': {rel: d.digest(ledger.root / rel) for rel in pinned},
                  'commit': args.commit, 'test_ids': tests,
                  'recorded_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')}
    number = pr_number(args.pr)
    if number is not None:
        completion['pr'] = number
    candidate['completion'] = completion
    if not d.fulfilled(ledger.root, candidate):
        raise Refusal('discover.py would not classify this record as complete; see references/ledger-contract.md')
    broken, _ = item_links(ledger, candidate)
    if broken:
        raise Refusal('alignment chain broken: ' + '; '.join(f"{b['kind']}: {b['detail']}" for b in broken))
    if not args.dry_run:
        manifest = json.loads((ledger.root / MANIFEST).read_text(encoding='utf-8'))
        manifest['work_items'][ledger.index[args.item]] = candidate
        (ledger.root / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    verdict = (f"{args.item} would be recorded complete (dry run)" if args.dry_run
               else f"{args.item} recorded complete in {MANIFEST}; not committed")
    payload = {'item': args.item, 'checkout': str(ledger.root), 'written': not args.dry_run,
               'completion': completion, 'verification_inputs': inputs, 'verdict': verdict}
    lines = [f'hype-align record · {args.item} #{item.get("issue")} · {item.get("title")}',
             f"  commit {args.commit} · PR {('#' + str(number)) if number else '(none)'} · reviewed by {completion['reviewed_by']}",
             f"  tests {', '.join(tests)} · evidence {report}",
             f"  pinned inputs: {len(completion['inputs'])} · scope {completion['scope_sha256'][:12]}",
             f'Verdict: {verdict}']
    emit(args, payload, lines)
    return 0


# --- drift ----------------------------------------------------------------------------------

STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')


def skip_string(text, i):
    quote, i = text[i], i + 1
    while i < len(text):
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    raise ValueError('unterminated string literal')


def skip_comment(text, i):
    if text.startswith('//', i):
        end = text.find('\n', i)
        return len(text) if end < 0 else end
    if text.startswith('/*', i):
        end = text.find('*/', i + 2)
        if end < 0:
            raise ValueError('unterminated comment')
        return end + 2
    return i


def close(text, start):
    """Index just past the bracket that closes text[start], skipping strings and comments."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c in '"\'`':
            i = skip_string(text, i)
            continue
        after = skip_comment(text, i)
        if after != i:
            i = after
            continue
        if c in '[{(':
            depth += 1
        elif c in ']})':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('unbalanced brackets')


def children(text, start):
    """(start, end) spans of the bracketed values directly inside the array opening at text[start]."""
    end, spans, i = close(text, start), [], start + 1
    while i < end - 1:
        c = text[i]
        if c in '"\'`':
            i = skip_string(text, i)
            continue
        after = skip_comment(text, i)
        if after != i:
            i = after
            continue
        if c in '[{':
            j = close(text, i)
            spans.append((i, j))
            i = j
            continue
        i += 1
    return spans


def strings(text):
    return [a if a or not b else b for a, b in STRING.findall(text)]


def array_after(text, pattern, what):
    found = re.search(pattern, text)
    if not found:
        raise ValueError(f'{what} not found')
    return found.end() - 1


def field(text, name):
    found = re.search(r'(?<![\w$])' + name + r'\s*:\s*(["\'])((?:(?!\1).)*)\1', text)
    return found.group(2) if found else None


def parse_features(ts):
    """features.ts: {feature id: [(slug, ids or None)]} from the exported feature array."""
    features = {}
    start = array_after(ts, r'export\s+const\s+features\b[^=]*=\s*\[', 'export const features')
    for s, e in children(ts, start):
        obj = ts[s:e]
        fid = field(obj, 'id')
        if not fid:
            continue
        sources = []
        found = re.search(r'(?<![\w$])sources\s*:\s*\[', obj)
        if found:
            for ss, se in children(obj, found.end() - 1):
                source = obj[ss:se]
                ids = re.search(r'(?<![\w$])ids\s*:\s*\[', source)
                slug = field(source, 'slug')
                if slug:
                    sources.append((slug, strings(source[ids.end() - 1:close(source, ids.end() - 1)]) if ids else None))
        features[fid] = sources
    return features


def parse_catalog(mjs):
    """studio_catalog.mjs: (catalog document paths, excluded document paths)."""
    template = re.search(r'path\s*:\s*`([^`$]*)\$\{slug\}([^`]*)`', mjs)
    before, after = template.groups() if template else (REQUIREMENT_DIR + '/', '.md')
    documents = []
    for s, e in children(mjs, array_after(mjs, r'catalogSources\s*=\s*\[', 'catalogSources')):
        element = mjs[s:e]
        explicit = field(element, 'path') if element.startswith('{') else None
        slug = field(element, 'slug') if element.startswith('{') else (strings(element) or [None])[0]
        if explicit or slug:
            documents.append(explicit or f'{before}{slug}{after}')
    if not documents:
        raise ValueError('catalogSources lists no documents')
    excluded = [field(mjs[s:e], 'path') for s, e in
                children(mjs, array_after(mjs, r'excludedSources\s*=\s*\[', 'excludedSources'))]
    return documents, [path for path in excluded if path]


def cmd_drift(args):
    ledger = Ledger(studio_root(args))
    lab = Path(args.lab).expanduser().resolve()
    catalog, lab_excluded = parse_catalog((lab / LAB_CATALOG).read_text(encoding='utf-8'))
    studio = sorted(str(p.relative_to(ledger.root)) for p in (ledger.root / REQUIREMENT_DIR).rglob('*.md') if p.is_file())
    ledger_excluded = ledger.manifest.get('excluded', {})
    findings = []

    def add(kind, path, detail):
        findings.append({'kind': kind, 'path': path, 'detail': detail})

    for path in studio:
        if path in catalog or path in lab_excluded:
            continue
        if path in ledger_excluded:
            add('unclassified', path, f"the Studio ledger excludes it ({ledger_excluded[path].get('reason')}); add it to Lab excludedSources")
        elif path in ledger.docs:
            add('unclassified', path, f"registered in the Studio ledger ({len(ledger.docs[path]['ids'])} IDs); add it to Lab catalogSources")
        else:
            add('unclassified', path, 'not in the Studio ledger either; classify it in Studio first')
    for path in sorted(set(catalog) | set(lab_excluded)):
        if path not in studio:
            add('removed', path, 'Lab lists it but the Studio checkout no longer has it')
    for path in catalog:
        if path in ledger_excluded:
            add('classification', path, 'Lab shows it as a catalog document but the Studio ledger excludes it')
    for path in lab_excluded:
        if path in ledger.docs:
            add('classification', path, 'Lab excludes it but the Studio ledger registers it')

    def current(rel):
        # Lab hashes `git show` output after String.prototype.trim(); unchanged sources match exactly.
        text = ledger.text(rel)
        return sha256_text(text.strip(JS_WHITESPACE)) if text is not None else None

    pins = {}
    for name in ('catalog.json', 'work.json', 'requirements.json'):
        data_path = lab / LAB_DATA / name
        if data_path.is_file():
            pins[name] = json.loads(data_path.read_text(encoding='utf-8')).get('sourceCommit')
    catalog_json = lab / LAB_DATA / 'catalog.json'
    if catalog_json.is_file():
        pinned = json.loads(catalog_json.read_text(encoding='utf-8'))
        for doc in pinned.get('documents', []):
            if doc.get('path') in studio and current(doc['path']) != doc.get('sourceHash'):
                add('stale', doc['path'], 'content changed since the pinned sourceCommit')
            evidence = doc.get('evidence')
            if evidence and evidence != doc.get('path') and current(evidence) != doc.get('evidenceHash'):
                add('stale', evidence, f"evidence for {doc.get('slug')} changed or is missing since the pinned sourceCommit")
        for doc in pinned.get('excluded', []):
            if doc.get('path') in studio and current(doc['path']) != doc.get('sourceHash'):
                add('stale', doc['path'], 'excluded document changed since the pinned sourceCommit')
        plans_now = {str(p.relative_to(ledger.root)) for p in (ledger.root / PLAN_DIR).rglob('*') if p.is_file()}
        plans_then = {p['path']: p.get('sourceHash') for p in pinned.get('plans', [])}
        for path in sorted(plans_now - set(plans_then)):
            add('stale', path, 'plan added since the pinned sourceCommit')
        for path in sorted(set(plans_then) - plans_now):
            add('stale', path, 'plan removed since the pinned sourceCommit')
        for path in sorted(plans_now & set(plans_then)):
            if current(path) != plans_then[path]:
                add('stale', path, 'plan changed since the pinned sourceCommit')
    head = git(ledger.root, 'rev-parse', 'HEAD')
    head = head.stdout.strip() if head.returncode == 0 else None
    behind = {}
    for name, sha in pins.items():
        count = git(ledger.root, 'rev-list', '--count', f'{sha}..HEAD') if sha and head else None
        behind[name] = int(count.stdout) if count is not None and count.returncode == 0 else None
    counts = dict(sorted(Counter(f['kind'] for f in findings).items()))
    verdict = ('in sync: every Studio requirement document is classified and pinned sources are unchanged'
               if not findings else 'drift: ' + ', '.join(f'{v} {k}' for k, v in counts.items()))
    payload = {'studio': str(ledger.root), 'studio_head': head, 'lab': str(lab), 'catalog_documents': catalog,
               'lab_excluded': lab_excluded, 'studio_documents': studio, 'ledger_excluded': sorted(ledger_excluded),
               'pins': pins, 'commits_behind': behind, 'findings': findings, 'counts': counts, 'verdict': verdict}
    lines = [f"hype-align drift · Studio {head[:7] if head else '(not a git checkout)'} · Lab {lab}",
             f'Lab catalog: {len(catalog)} documents + {len(lab_excluded)} excluded · Studio: {len(studio)} documents, '
             f'{len(ledger_excluded)} excluded by the ledger']
    for name, sha in pins.items():
        lag = behind.get(name)
        lines.append(f"pin {name}: {(sha or '(none)')[:7]} · "
                     + (f'{lag} commits behind HEAD' if lag is not None else 'distance unknown in this checkout'))
    lines += [f"{f['kind'].upper()} {f['path']}: {f['detail']}" for f in findings]
    lines.append(f'Verdict: {verdict}')
    emit(args, payload, lines)
    return 1 if findings else 0


# --- CLI ------------------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog='hype-align', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    def common(p, scope=True):
        p.add_argument('--studio', help='product checkout that owns config/requirement-work.json (default: $HYPEPROOF_STUDIO)')
        p.add_argument('--json', action='store_true', help='machine-readable output')
        if scope:
            p.add_argument('--item', action='append', help='limit to this work item id (repeatable)')
            p.add_argument('--doc', action='append', help='limit to items citing this requirement document: path, file name or stem (repeatable)')
            p.add_argument('--prefix', action='append', help='limit to work item ids with this prefix (repeatable)')

    p = sub.add_parser('next', help='rank ready work items and name the next one')
    common(p)
    source = p.add_mutually_exclusive_group()
    source.add_argument('--snapshot', type=Path, help='recorded discover.py GitHub snapshot (max age 1h)')
    source.add_argument('--live', action='store_true', help='read open PRs and claims from GitHub via gh')
    p.set_defaults(func=cmd_next)

    p = sub.add_parser('record', help='write a completion record for one work item (never commits)')
    common(p, scope=False)
    p.add_argument('item', help='work item id')
    p.add_argument('--commit', required=True, help='merged commit SHA that delivered the item')
    p.add_argument('--tests', action='append', help='test IDs verified, comma separated or repeated')
    p.add_argument('--evidence', help='repo-relative evidence report committed in the product checkout')
    p.add_argument('--reviewed-by', help='independent reviewer of the verdict')
    p.add_argument('--pr', help='merged PR number or URL (optional)')
    p.add_argument('--input', action='append', help='extra verification input (implementation/test file) to pin (repeatable)')
    p.add_argument('--replace', action='store_true', help='supersede an existing completion record')
    p.add_argument('--dry-run', action='store_true', help='validate and print without writing')
    p.set_defaults(func=cmd_record)

    p = sub.add_parser('check', help='verify each work item\'s alignment chain')
    common(p)
    p.add_argument('--lab', help='hypeprooflab checkout; also require Lab features to link each item')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('drift', help='compare the Lab catalog with the Studio requirement inventory')
    common(p, scope=False)
    p.add_argument('--lab', required=True, help='hypeprooflab checkout')
    p.set_defaults(func=cmd_drift)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Refusal as exc:
        print(f'hype-align {args.command}: refused: {exc}', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f'hype-align {args.command}: could not evaluate: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
