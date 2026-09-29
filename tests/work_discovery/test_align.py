"""hype-align over a synthetic product checkout and Lab catalog (no real product data)."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.dont_write_bytecode = True  # keep the vendored skill tree free of __pycache__
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'skills/hype-align/scripts/align.py'
spec = importlib.util.spec_from_file_location('hype_align', SCRIPT)
align = importlib.util.module_from_spec(spec)
spec.loader.exec_module(align)
d = align.discovery()

REQUIREMENTS = """# Demo notes requirements

| ID | Stage / intent | Acceptance | Test |
|---|---|---|---|
| DM-01 | P1 / W2 / INT-DM-01 | A saved note reopens. | DM-T01 |
| DM-02 | P0 / W1 / INT-DM-01 | A note survives restart and offline use. | DM-T02/03 |
| DM-03 | P0 / W3 / INT-DM-01 | A shared note opens for a guest. | — |
| DM-04 | P2 / INT-DM-01 | A note exports as a file. The week-3 demo mentions 3주차 in prose only. | DM-T04 |
"""
TESTING = """# Demo notes tests

| Test ID | Requirement | Pass condition |
|---|---|---|
| DM-T01 | DM-01 | saved note reopens |
| DM-T02 | DM-02 | reopen after restart |
| DM-T03 | DM-02 | reopen offline |
| DM-T04 | DM-04 | export writes a file |
| DM-T05 | DM-03 | guest opens the shared link |
"""
FEATURES = """/** Synthetic feature catalog. */
export type Product = "Studio" | "Chalk";
export const features: FeatureDefinition[] = [
  {
    id: "notes",
    product: "Studio",
    kind: "current",
    title: "Notes { with braces }",
    outcome: "Save, reopen and export notes.",
    scope: "// not a comment",
    sources: [{ slug: "demo", ids: ["DM-01", "DM-02", "DM-04"] }],
  },
  // a comment with ] and }
  {
    id: "sharing",
    product: "Studio",
    kind: "roadmap",
    status: "예정",
    title: "Share notes",
    outcome: "Guests open a shared note.",
    scope: "Guest links.",
    sources: [
      {
        slug: "demo",
        ids: ["DM-03"],
      },
    ],
  },
];
"""
CATALOG = """// Synthetic Lab catalog source list.
export const catalogSources = [
  ['demo', 'Demo notes', 'Everyone', 'Save and reopen notes.', 'Synthetic scope.', 'docs/testing/demo.md'],
].map(([slug, title, audience, summary, scope, evidence]) => ({ slug, title, audience, summary, scope, evidence, path: `docs/requirements/${slug}.md` }));

export const excludedSources = [{ path: 'docs/requirements/retired.md', reason: 'Historical notes.' }];
"""


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.email=ci@example.com', '-c', 'user.name=CI', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def item(name, issue, ids, **extra):
    return {'id': name, 'title': f'{name} packet', 'issue': issue, 'kind': 'implementation',
            'requirements': [{'path': 'docs/requirements/demo.md', 'ids': ids}], 'depends_on': [],
            'next_action': f'Build {name}', 'design_delta': 'Local file store', 'positive_control': 'Reopen shows the note',
            'negative_control': 'A failed write keeps the old note', 'evidence_required': 'Test output and file hashes',
            'implementation_paths': ['src'], 'verification_inputs': [], **extra}


def ledger_path(root):
    return root / 'config/requirement-work.json'


def load(root):
    return json.loads(ledger_path(root).read_text(encoding='utf-8'))


def save(root, manifest):
    ledger_path(root).parent.mkdir(parents=True, exist_ok=True)
    ledger_path(root).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@pytest.fixture
def studio(tmp_path):
    root = tmp_path / 'studio'
    write(root, 'docs/intents/demo.md', '# Intent\nINT-DM-01: people keep their notes.\n')
    write(root, 'docs/design/demo.md', '# Design\nLocal file store.\n')
    write(root, 'docs/requirements/demo.md', REQUIREMENTS)
    write(root, 'docs/requirements/retired.md', '# Retired\nHistorical notes without IDs.\n')
    write(root, 'docs/testing/demo.md', TESTING)
    write(root, 'docs/plan/demo.md', '# Plan\n')
    write(root, 'docs/evidence/beta.md', 'DM-T02 PASS, DM-T03 PASS\n')
    write(root, 'src/note.js', 'export const save = () => true;\n')
    write(root, 'test/note.test.mjs', 'import "../src/note.js";\n')
    manifest = {
        'version': 1, 'repository': 'example/demo-product', 'scope': 'synthetic',
        'requirement_globs': ['docs/requirements/*.md'],
        'excluded': {'docs/requirements/retired.md': {'reason': 'Historical notes.',
                                                      'sha256': sha((root / 'docs/requirements/retired.md').read_text())}},
        'documents': [{'path': 'docs/requirements/demo.md', 'ids': ['DM-01', 'DM-02', 'DM-03', 'DM-04'],
                       'inline_prefixes': [], 'sha256': sha(REQUIREMENTS), 'owner': 'owner',
                       'intent': 'docs/intents/demo.md', 'design': 'docs/design/demo.md', 'test': 'docs/testing/demo.md'}],
        'work_items': [
            item('alpha', 1, ['DM-01']),
            item('beta', 2, ['DM-02'], verification_inputs=['src/note.js', 'test/note.test.mjs']),
            item('gamma', 3, ['DM-03'], depends_on=['beta']),
            item('delta', 4, ['DM-04'], gate={'reason': 'A person must approve the export format'}),
            item('zeta', 5, ['DM-03']),
            item('eta', 6, ['DM-01']),
        ],
    }
    save(root, manifest)
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'fixture')
    return root


@pytest.fixture
def lab(tmp_path, studio):
    root = tmp_path / 'lab'
    write(root, align.LAB_CATALOG, CATALOG)
    write(root, f'{align.LAB_DATA}/features.ts', FEATURES)
    head = git(studio, 'rev-parse', 'HEAD')
    trimmed = lambda rel: sha((studio / rel).read_text().strip())
    write(root, f'{align.LAB_DATA}/work.json', json.dumps({'sourceCommit': head, 'features': {
        'notes': [{'id': 'alpha', 'title': 'alpha packet', 'issue': 1}]}}))
    write(root, f'{align.LAB_DATA}/catalog.json', json.dumps({
        'sourceCommit': head,
        'documents': [{'slug': 'demo', 'path': 'docs/requirements/demo.md', 'evidence': 'docs/testing/demo.md',
                       'sourceHash': trimmed('docs/requirements/demo.md'), 'evidenceHash': trimmed('docs/testing/demo.md')}],
        'excluded': [{'path': 'docs/requirements/retired.md', 'sourceHash': trimmed('docs/requirements/retired.md')}],
        'plans': [{'path': 'docs/plan/demo.md', 'sourceHash': trimmed('docs/plan/demo.md')}]}))
    return root


def run(capsys, *args):
    code = align.main([str(a) for a in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_json(capsys, *args):
    code, out, err = run(capsys, *args, '--json')
    return code, json.loads(out) if out else None, err


def record_beta(capsys, studio, *extra):
    return run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'),
               '--tests', 'DM-T02,DM-T03', '--evidence', 'docs/evidence/beta.md', '--reviewed-by', 'verifier', *extra)


def test_tokens_expand_shorthand_without_reading_inside_longer_ids():
    found = align.tokens('CA-T16/17 · SX-T02·03~05 · MC-21–23 · INT-ACCESS-01 · AE-01/02, 3 cases')
    assert {'CA-T16', 'CA-T17', 'SX-T02', 'SX-T03', 'SX-T04', 'SX-T05', 'MC-21', 'MC-22', 'MC-23',
            'INT-ACCESS-01', 'AE-01', 'AE-02'} == found
    assert align.tokens('see CA-T16/17 and MC-21', tests_only=True) == {'CA-T16', 'CA-T17'}


def test_next_ranks_priority_then_week_then_unblocked_work_then_ledger_order(capsys, studio):
    code, out, _ = run_json(capsys, 'next', '--studio', studio)
    assert code == 0
    assert [r['id'] for r in out['ranked']] == ['beta', 'zeta', 'alpha', 'eta']
    assert out['next']['id'] == 'beta' and out['next']['priority'] == 0 and out['next']['week'] == 1
    assert out['next']['unblocks'] == 1  # gamma waits on beta
    assert out['counts'] == {'blocked': 1, 'dependency': 1, 'ready': 4}
    assert out['availability'].startswith('unchecked') and out['availability_checked'] is False
    # Prose "3주차" in DM-04's acceptance cell is not a week tag.
    assert align.Ledger(studio).facts('docs/requirements/demo.md', 'DM-04') == (2, None, ['DM-T04'])


def test_next_completed_prerequisites_do_not_demote_an_item(capsys, studio):
    assert record_beta(capsys, studio)[0] == 0
    manifest = load(studio)
    manifest['work_items'][5]['curriculum_week'] = [1, 4]  # eta: explicit week beats alpha's row tag W2
    manifest['work_items'].append(item('iota', 7, ['DM-03'], depends_on=['zeta']))
    save(studio, manifest)
    code, out, _ = run_json(capsys, 'next', '--studio', studio)
    assert code == 0
    # gamma (P0) became ready when beta completed; its finished prerequisite does not rank it behind
    # P1 roots. zeta ties with it on priority and week and goes first because it unblocks iota.
    assert [(r['id'], r['unblocks']) for r in out['ranked']] == [('zeta', 1), ('gamma', 0), ('eta', 0), ('alpha', 0)]


def snapshot_file(tmp_path, studio, closed=(), pull_requests=()):
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps({'repository': 'example/demo-product', 'complete': True,
                                'fetched_at': datetime.now(timezone.utc).isoformat(),
                                'issues': [{'number': w['issue'], 'state': 'CLOSED' if w['issue'] in closed else 'OPEN',
                                            'labels': []} for w in load(studio)['work_items']],
                                'pull_requests': list(pull_requests)}))
    return path


def test_next_names_a_reopened_completion_instead_of_the_packet(capsys, studio):
    assert record_beta(capsys, studio)[0] == 0
    git(studio, 'commit', '-q', '-am', 'record beta')
    write(studio, 'test/note.test.mjs', 'import "../src/note.js"; // the next slice edits the shared test\n')
    code, out, _ = run_json(capsys, 'next', '--studio', studio)
    assert code == 0 and out['next']['id'] == 'beta' and out['next']['reopened'] is True
    assert out['next']['changed'] == ['test/note.test.mjs'] and 'record --replace' in out['next']['reason']
    assert [r['id'] for r in out['reopened']] == ['beta'] and 'beta' not in [r['id'] for r in out['ranked']]
    code, text, _ = run(capsys, 'next', '--studio', studio)
    assert 'REOPENED beta: completion no longer holds (changed since recorded: test/note.test.mjs)' in text
    assert 'next_action: Build beta' not in text
    assert text.rstrip().endswith('Verdict: next is beta (#2): re-verify its reopened completion')


def test_next_names_a_reopened_completion_whose_issue_is_closed(capsys, studio, tmp_path):
    # The normal path: beta's merged PR closed #2, and a later slice edited a file beta pins.
    assert record_beta(capsys, studio)[0] == 0
    git(studio, 'commit', '-q', '-am', 'record beta')
    write(studio, 'src/note.js', 'export const save = () => false;\n')
    git(studio, 'commit', '-q', '-am', 'later slice')
    snapshot = snapshot_file(tmp_path, studio, closed={2})
    code, out, _ = run_json(capsys, 'next', '--studio', studio, '--snapshot', snapshot)
    assert code == 0 and out['next']['id'] == 'beta' and out['next']['state'] == 'reconcile'
    assert out['next']['changed'] == ['src/note.js'] and out['counts']['reconcile'] == 1
    code, text, _ = run(capsys, 'next', '--studio', studio, '--snapshot', snapshot, '--item', 'beta', '--item', 'gamma')
    assert 'REOPENED beta #2 [reconcile]: completion no longer holds (changed since recorded: src/note.js)' in text
    assert '[dependency] gamma #3: Unfulfilled packets: beta' in text
    assert text.rstrip().endswith('Verdict: next is beta (#2): re-verify its reopened completion')


def test_next_names_merged_work_without_a_completion_and_what_blocks_the_rest(capsys, studio, tmp_path):
    # beta's PR merged and closed #2, but nobody ran record: nothing is ready in beta's chain.
    snapshot = snapshot_file(tmp_path, studio, closed={2})
    code, out, _ = run_json(capsys, 'next', '--studio', studio, '--snapshot', snapshot, '--item', 'beta', '--item', 'gamma',
                            '--item', 'delta')
    assert code == 0 and out['next'] is None and out['ranked'] == []
    assert [(e['id'], e['state']) for e in out['items']] == [('beta', 'reconcile'), ('delta', 'blocked'), ('gamma', 'dependency')]
    assert 'run record beta' in out['items'][0]['reason']
    assert out['items'][1]['reason'] == 'A person must approve the export format'
    assert out['verdict'].startswith('no ready item in scope; reconcile beta (#2) first: issue #2 is closed without a completion')
    # With ready work elsewhere, the merged item is still named.
    code, out, _ = run_json(capsys, 'next', '--studio', studio, '--snapshot', snapshot)
    assert out['next']['id'] == 'zeta' and out['verdict'] == 'next is zeta (#5); also reconcile beta (#2)'
    # Offline, the closed issue is unknown: the NEXT line says what to confirm.
    code, text, _ = run(capsys, 'next', '--studio', studio)
    assert 'offline: if #2 is closed or its PR merged, this item needs record, not new work' in text


def test_next_reads_week_tags_and_names_a_bad_curriculum_week(capsys, studio):
    manifest = load(studio)
    manifest['work_items'][5]['curriculum_week'] = 'W1'
    save(studio, manifest)
    code, out, _ = run_json(capsys, 'next', '--studio', studio)
    assert code == 0 and next(r['week'] for r in out['ranked'] if r['id'] == 'eta') == 1
    manifest['work_items'][5]['curriculum_week'] = 'soon'
    save(studio, manifest)
    code, _, err = run(capsys, 'next', '--studio', studio)
    assert code == 2 and "work item eta: curriculum_week 'soon' is not a week" in err
    manifest['work_items'][5]['curriculum_week'] = []
    save(studio, manifest)
    code, _, err = run(capsys, 'next', '--studio', studio)
    assert code == 2 and 'work item eta: curriculum_week is an empty list' in err


def test_next_uses_the_github_snapshot_when_given(capsys, studio, tmp_path):
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps({'repository': 'example/demo-product', 'complete': True,
                                    'fetched_at': datetime.now(timezone.utc).isoformat(),
                                    'issues': [{'number': n, 'state': 'OPEN', 'labels': []} for n in range(1, 7)],
                                    'pull_requests': [{'number': 40, 'issues': [2], 'closing': [2], 'mentions': []}]}))
    code, out, _ = run_json(capsys, 'next', '--studio', studio, '--snapshot', snapshot)
    assert code == 0 and out['next']['id'] == 'zeta'
    assert out['counts']['in_review'] == 1 and out['availability'].startswith('checked at') and out['availability_checked']


def test_next_scope_filters_and_ledger_gap(capsys, studio):
    code, out, _ = run_json(capsys, 'next', '--studio', studio, '--doc', 'demo', '--prefix', 'al')
    assert code == 0 and [r['id'] for r in out['ranked']] == ['alpha']
    write(studio, 'docs/requirements/demo.md', REQUIREMENTS + '| DM-05 | P0 | New row | DM-T05 |\n')
    code, out, _ = run(capsys, 'next', '--studio', studio)
    assert code == 1
    assert 'GAP: requirement inventory changed: docs/requirements/demo.md' in out
    assert 'Verdict: reconcile the requirement ledger first' in out


BASE = {'--tests': 'DM-T02,DM-T03', '--evidence': 'docs/evidence/beta.md', '--reviewed-by': 'verifier'}
BASE_FLAGS = [part for pair in BASE.items() for part in pair]


@pytest.mark.parametrize('name, override, message', [
    ('beta', {'--tests': None}, '--tests is required'),
    ('beta', {'--tests': 'DM-T02,DM-T99'}, 'not defined in any registered test document: DM-T99'),
    ('beta', {'--tests': 'DM-02'}, 'not defined in any registered test document: DM-02'),
    ('beta', {'--tests': 'DM-T02,DM-T04'}, 'tests not tied to a requirement beta cites: DM-T04'),
    ('beta', {'--evidence': None}, '--evidence is required'),
    ('beta', {'--evidence': 'docs/evidence/missing.md'}, 'is not a file'),
    ('beta', {'--evidence': '../outside.md'}, 'outside the checkout'),
    ('beta', {'--evidence': 'docs/testing/demo.md'}, 'is a registered test document'),
    ('beta', {'--evidence': 'docs/requirements/demo.md'}, 'is a registered requirement document'),
    ('beta', {'--evidence': 'src/note.js'}, 'is also a verification input of beta'),
    ('beta', {'--reviewed-by': None}, '--reviewed-by is required'),
    ('beta', {'--commit': 'abcdef1'}, 'not in this checkout'),
    ('beta', {'--commit': 'HEAD'}, 'hexadecimal'),
    ('beta', {'--input': 'config/requirement-work.json'}, 'ledger cannot be a verification input'),
    ('alpha', {}, 'has no verification_inputs'),
    ('gamma', {}, 'depends on work that is not complete: beta'),
    ('delta', {}, 'is gated: A person must approve the export format'),
    ('nope', {}, 'unknown work item: nope'),
])
def test_record_refuses_without_test_ids_or_evidence(capsys, studio, tmp_path, name, override, message):
    (tmp_path / 'outside.md').write_text('evidence outside the product repo\n')
    flags = {'--commit': git(studio, 'rev-parse', 'HEAD'), **BASE, **override}
    before = ledger_path(studio).read_bytes()
    code, out, err = run_json(capsys, 'record', name, '--studio', studio,
                              *[part for flag, value in flags.items() if value is not None for part in (flag, value)])
    assert code == 1 and message in err
    assert out['verdict'] == 'refused' and message in out['error']
    assert ledger_path(studio).read_bytes() == before


def test_record_needs_a_merged_commit_and_stores_its_full_sha(capsys, studio, tmp_path, monkeypatch):
    head = git(studio, 'rev-parse', 'HEAD')
    # A PR branch head that never reached main: the branch is deleted, the object stays.
    git(studio, 'checkout', '-q', '-b', 'side')
    write(studio, 'docs/side.md', 'side work\n')
    git(studio, 'add', '-A')
    git(studio, 'commit', '-q', '-m', 'side')
    side = git(studio, 'rev-parse', 'HEAD')
    git(studio, 'checkout', '-q', 'main')
    git(studio, 'branch', '-q', '-D', 'side')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', side, *BASE_FLAGS)
    assert code == 1 and 'is not an ancestor of HEAD' in err
    # origin/main, when the checkout has it, must contain the commit as well.
    write(studio, 'docs/plan/later.md', '# Later\n')
    git(studio, 'add', '-A')
    git(studio, 'commit', '-q', '-m', 'later')
    git(studio, 'update-ref', 'refs/remotes/origin/main', head)
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'), *BASE_FLAGS)
    assert code == 1 and 'is not an ancestor of origin/main' in err
    # A short SHA on main is stored as the full SHA.
    code, out, _ = run_json(capsys, 'record', 'beta', '--studio', studio, '--commit', head[:7], *BASE_FLAGS, '--dry-run')
    assert code == 0 and out['completion']['commit'] == head
    # Without git the commit cannot be confirmed, so nothing is recorded.
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path))
    shutil.rmtree(studio / '.git')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', head, *BASE_FLAGS)
    assert code == 1 and 'is not a git work tree' in err


def test_record_pins_only_committed_files(capsys, studio):
    head = git(studio, 'rev-parse', 'HEAD')
    write(studio, 'docs/evidence/new.md', 'DM-T02 PASS, DM-T03 PASS\n')
    flags = ['--commit', head, '--tests', 'DM-T02,DM-T03', '--reviewed-by', 'verifier']
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--evidence', 'docs/evidence/new.md', *flags)
    assert code == 1 and 'not tracked by git: docs/evidence/new.md' in err
    # A staged new report is allowed; it ships with the ledger edit.
    git(studio, 'add', 'docs/evidence/new.md')
    code, out, _ = run(capsys, 'record', 'beta', '--studio', studio, '--evidence', 'docs/evidence/new.md', *flags, '--dry-run')
    assert code == 0 and 'docs/evidence/new.md is not in HEAD yet' in out
    write(studio, 'src/note.js', 'export const save = () => "edited";\n')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--evidence', 'docs/evidence/new.md', *flags)
    assert code == 1 and 'uncommitted changes in pinned files: src/note.js' in err


def test_record_evidence_cannot_define_the_tests_it_attests(capsys, studio):
    # The report lives under docs/testing but is not a registered test document.
    write(studio, 'docs/testing/evidence/beta.md', 'DM-T02 PASS · DM-T09 DM-02 PASS\n')
    git(studio, 'add', '-A')
    git(studio, 'commit', '-q', '-m', 'evidence')
    flags = ['--commit', git(studio, 'rev-parse', 'HEAD'), '--evidence', 'docs/testing/evidence/beta.md', '--reviewed-by', 'verifier']
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--tests', 'DM-T02,DM-T09', *flags)
    assert code == 1 and 'not defined in any registered test document: DM-T09' in err
    assert run(capsys, 'record', 'beta', '--studio', studio, '--tests', 'DM-T02,DM-T03', *flags)[0] == 0
    assert run(capsys, 'check', '--studio', studio, '--item', 'beta')[0] == 0


def test_traceability_rows_beside_test_ids_are_not_tests(capsys, studio):
    # `| DM-02 | DM-T02, DM-T03 |` says which tests verify DM-02; it does not make DM-02 a test.
    coverage = '\n| Requirement | Verified by |\n|---|---|\n| DM-02 | DM-T02, DM-T03 |\n| AT-01 | manual walk-through |\n'
    write(studio, 'docs/testing/demo.md', TESTING + coverage)
    git(studio, 'commit', '-q', '-am', 'coverage table')
    defined = align.Ledger(studio).test_ids
    assert 'DM-02' not in defined and {'DM-T02', 'AT-01'} <= defined  # AT-01 is not a requirement ID
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'),
                       '--tests', 'DM-02', '--evidence', 'docs/evidence/beta.md', '--reviewed-by', 'verifier')
    assert code == 1 and 'not defined in any registered test document: DM-02' in err
    assert record_beta(capsys, studio)[0] == 0
    manifest = load(studio)
    manifest['work_items'][1]['completion']['test_ids'] = ['DM-02']
    save(studio, manifest)
    code, out, _ = run_json(capsys, 'check', '--studio', studio, '--item', 'beta')
    assert code == 1 and 'recorded test DM-02 is not defined' in out['broken'][0]['detail']
    # A test document with no -T IDs keys its tests by requirement ID, and those do count.
    write(studio, 'docs/testing/demo.md', '| Requirement | Check |\n|---|---|\n| DM-01 | reopen |\n| DM-02 | restart |\n')
    assert {'DM-01', 'DM-02'} <= align.Ledger(studio).test_ids


def test_a_test_belongs_to_its_declared_targets_not_to_ids_named_in_passing(capsys, studio):
    # DM-T06's Requirement column says DM-03; its pass condition only mentions DM-02. A prose line that
    # expands a test range and a requirement range at once pairs everything with everything.
    write(studio, 'docs/testing/demo.md', TESTING + '| DM-T06 | DM-03 | guest opens, unlike DM-02 restart |\n'
                                                    '\nScope: DM-01~04 → DM-T01~06.\n')
    ledger = align.Ledger(studio)
    beta = ledger.items[ledger.index['beta']]
    assert ledger.tied(ledger.items[ledger.index['zeta']], 'DM-T06')
    assert not ledger.tied(beta, 'DM-T06') and not ledger.tied(beta, 'DM-T04')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'),
                       '--tests', 'DM-T02,DM-T06', '--evidence', 'docs/evidence/beta.md', '--reviewed-by', 'verifier')
    assert code == 1 and 'tests not tied to a requirement beta cites: DM-T06' in err
    # Without a target column, one line naming both still ties them.
    write(studio, 'docs/testing/demo.md', TESTING + '\nDM-T06 also exercises DM-02 after a restart.\n')
    assert align.Ledger(studio).tied(beta, 'DM-T06')


def test_record_refuses_on_ledger_gaps(capsys, studio):
    write(studio, 'docs/requirements/demo.md', REQUIREMENTS + '| DM-05 | P0 | New row | DM-T05 |\n')
    git(studio, 'commit', '-q', '-am', 'new requirement row')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'), *BASE_FLAGS)
    assert code == 1 and 'the requirement ledger has 2 gaps' in err and 'requirement inventory changed' in err


def test_record_refuses_to_overwrite_without_replace(capsys, studio):
    assert record_beta(capsys, studio)[0] == 0
    code, _, err = record_beta(capsys, studio)
    assert code == 1 and 'already has a completion record' in err
    # Superseding needs something new: the same commit and an unchanged report attest nothing.
    code, _, err = record_beta(capsys, studio, '--replace')
    assert code == 1 and 'nothing new to attest' in err
    write(studio, 'docs/evidence/beta.md', 'DM-T02 PASS, DM-T03 PASS (re-run)\n')
    git(studio, 'add', 'docs/evidence/beta.md')
    code, _, err = record_beta(capsys, studio, '--replace')
    assert code == 1 and f"does not name commit {git(studio, 'rev-parse', 'HEAD')[:12]}" in err
    write(studio, 'docs/evidence/beta.md', f"DM-T02 PASS, DM-T03 PASS on {git(studio, 'rev-parse', '--short', 'HEAD')}\n")
    git(studio, 'add', 'docs/evidence/beta.md')
    assert record_beta(capsys, studio, '--replace')[0] == 0


def test_record_replace_needs_a_new_report_whatever_the_commit(capsys, studio):
    # A later slice edits a pinned file and reopens beta. Passing the new main commit alone must not
    # re-stamp the old report: it still names the old run.
    old = git(studio, 'rev-parse', 'HEAD')
    write(studio, 'docs/evidence/beta.md', f'DM-T02 PASS, DM-T03 PASS on {old}\n')
    git(studio, 'commit', '-q', '-am', 'beta report')
    assert record_beta(capsys, studio)[0] == 0
    git(studio, 'commit', '-q', '-am', 'record beta')
    write(studio, 'src/note.js', 'export const save = () => "v2";\n')
    git(studio, 'commit', '-q', '-am', 'later slice edits a pinned input')
    new = git(studio, 'rev-parse', 'HEAD')
    code, _, err = record_beta(capsys, studio, '--replace')
    assert code == 1 and 'nothing new to attest: docs/evidence/beta.md is the report the superseded completion pinned' in err
    # The same bytes under another path are the same report.
    write(studio, 'docs/evidence/beta-copy.md', f'DM-T02 PASS, DM-T03 PASS on {old}\n')
    git(studio, 'add', 'docs/evidence/beta-copy.md')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', new, '--tests', 'DM-T02,DM-T03',
                       '--evidence', 'docs/evidence/beta-copy.md', '--reviewed-by', 'verifier', '--replace')
    assert code == 1 and 'nothing new to attest' in err
    write(studio, 'docs/evidence/beta.md', f'DM-T02 PASS, DM-T03 PASS on {new[:9]} after the src/note.js change\n')
    git(studio, 'add', 'docs/evidence/beta.md')
    assert record_beta(capsys, studio, '--replace')[0] == 0


def test_record_commit_must_hold_the_pinned_content_and_the_item(capsys, studio):
    old = git(studio, 'rev-parse', 'HEAD')
    write(studio, 'src/note.js', 'export const save = () => "v2";\n')
    git(studio, 'commit', '-q', '-am', 'later slice edits a pinned input')
    code, _, err = run(capsys, 'record', 'beta', '--studio', studio, '--commit', old, *BASE_FLAGS)
    assert code == 1 and f'pinned files differ between commit {old[:12]} and HEAD: src/note.js' in err
    assert run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'), *BASE_FLAGS,
               '--dry-run')[0] == 0
    # Same pinned content, but the commit predates the work item's registration.
    before = git(studio, 'rev-parse', 'HEAD')
    manifest = load(studio)
    manifest['work_items'].append(item('theta', 7, ['DM-02'], verification_inputs=['src/note.js']))
    save(studio, manifest)
    git(studio, 'commit', '-q', '-am', 'register theta')
    code, _, err = run(capsys, 'record', 'theta', '--studio', studio, '--commit', before, *BASE_FLAGS)
    assert code == 1 and f'commit {before[:12]} predates the registration of theta' in err


def test_record_pins_a_staged_report_and_warns_where_hype_pr_needs_a_node(capsys, studio):
    write(studio, 'docs/evidence/beta.md', 'DM-T02 FAIL, edited and not staged\n')
    code, _, err = record_beta(capsys, studio)
    assert code == 1 and 'docs/evidence/beta.md has unstaged changes' in err
    git(studio, 'add', 'docs/evidence/beta.md')
    code, out, _ = record_beta(capsys, studio, '--dry-run')
    assert code == 0 and 'docs/evidence/beta.md differs from HEAD (staged edit)' in out
    # A new report on a path hype-pr reads as new criteria needs a trace node in the same PR.
    write(studio, 'docs/testing/demo-2026-09-30-evidence.md', 'DM-T02 PASS, DM-T03 PASS\n')
    git(studio, 'add', 'docs/testing/demo-2026-09-30-evidence.md')
    code, out, _ = run_json(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'),
                            '--tests', 'DM-T02,DM-T03', '--evidence', 'docs/testing/demo-2026-09-30-evidence.md',
                            '--reviewed-by', 'verifier', '--dry-run')
    assert code == 0 and out['report_needs_trace_node'] is True
    assert align.NEW_CRITERIA.pattern in (ROOT / 'scripts/hype-pr/preparation.py').read_text(encoding='utf-8')


def test_record_writes_a_completion_discover_accepts_and_never_commits(capsys, studio):
    head = git(studio, 'rev-parse', 'HEAD')
    before = load(studio)
    code, out, _ = record_beta(capsys, studio, '--pr', 'https://github.com/example/demo-product/pull/7')
    assert code == 0 and 'recorded complete' in out and 'not committed' in out
    assert git(studio, 'rev-parse', 'HEAD') == head
    assert git(studio, 'status', '--porcelain') == 'M config/requirement-work.json'
    after = load(studio)
    completion = after['work_items'][1]['completion']
    assert completion['commit'] == head and completion['pr'] == 7 and completion['test_ids'] == ['DM-T02', 'DM-T03']
    assert completion['verdict'] == 'PASS' and completion['report'] == 'docs/evidence/beta.md'
    assert completion['recorded_at'].endswith('Z')
    assert set(completion['inputs']) == {'docs/requirements/demo.md', 'src/note.js', 'test/note.test.mjs', 'docs/evidence/beta.md'}
    # Only beta changed, and the file keeps the ledger's own formatting.
    assert [w for n, w in enumerate(after['work_items']) if n != 1] == [w for n, w in enumerate(before['work_items']) if n != 1]
    assert ledger_path(studio).read_text() == json.dumps(after, ensure_ascii=False, indent=2) + '\n'
    # The canonical classifier agrees, and the dependent packet opens up.
    snapshot = align.offline_snapshot(after, datetime.now(timezone.utc))
    states = {r['id']: r['state'] for r in d.classify(studio, after, snapshot, datetime.now(timezone.utc))}
    assert states['beta'] == 'complete' and states['gamma'] == 'ready'
    # Changing a pinned implementation file reopens it (discover.py's rule, surfaced by check).
    write(studio, 'src/note.js', 'export const save = () => false;\n')
    code, out, _ = run(capsys, 'check', '--studio', studio, '--item', 'beta')
    assert code == 1 and 'completion no longer holds (changed since recorded: src/note.js)' in out


def test_record_input_extends_the_packet_and_names_shared_pins(capsys, studio):
    code, out, _ = run_json(capsys, 'record', 'alpha', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'),
                            '--tests', 'DM-T01', '--evidence', 'docs/evidence/beta.md', '--reviewed-by', 'verifier',
                            '--input', 'src/note.js', '--dry-run')
    assert code == 0 and out['written'] is False and out['verification_inputs'] == ['src/note.js']
    # beta also pins src/note.js: the next change to it reopens both packets.
    assert out['shared_inputs'] == {'src/note.js': ['beta']}
    assert 'completion' not in load(studio)['work_items'][0]


def test_check_positive_control_and_broken_links(capsys, studio, lab):
    assert record_beta(capsys, studio)[0] == 0
    code, out, _ = run_json(capsys, 'check', '--studio', studio, '--lab', lab)
    assert code == 0 and out['ok'] and out['broken'] == [] and out['items_checked'] == 6

    # Negative control: each broken link is named and turns the verdict red.
    write(studio, 'docs/requirements/demo.md', REQUIREMENTS.replace('| DM-T04 |', '| DM-T09 |'))
    (studio / 'docs/design/demo.md').unlink()
    manifest = load(studio)
    manifest['work_items'][1]['implementation_paths'] = ['src/missing.js']
    manifest['work_items'][0]['feature_ids'] = ['no-such-feature']
    save(studio, manifest)
    features = lab / align.LAB_DATA / 'features.ts'
    features.write_text(FEATURES.replace('"DM-01", "DM-02", "DM-04"', '"DM-01", "DM-02"'))
    code, out, _ = run_json(capsys, 'check', '--studio', studio, '--lab', lab)
    assert code == 1 and not out['ok']
    assert 'requirement content changed: docs/requirements/demo.md' in out['ledger_gaps']
    kinds = {(b['item'], b['kind']) for b in out['broken']}
    assert {('delta', 'test-id'), ('beta', 'implementation'), ('alpha', 'lab-feature'), ('delta', 'lab'),
            ('alpha', 'design')} <= kinds
    assert ('eta', 'lab') not in kinds  # DM-01 is still linked through the notes feature
    code, text, _ = run(capsys, 'check', '--studio', studio, '--lab', lab)
    assert 'BROKEN delta' in text and 'DM-T09, which no testing document defines' in text


def test_check_requires_a_test_link(capsys, studio):
    # beta's evidence report sits under docs/testing and names DM-03. A report is a claim about a
    # run, not a test for zeta, so it must not supply zeta's test link.
    write(studio, 'docs/testing/evidence/beta.md', 'DM-T02 PASS, DM-T03 PASS; DM-03 sharing left untouched.\n')
    git(studio, 'add', '-A')
    git(studio, 'commit', '-q', '-m', 'evidence')
    assert run(capsys, 'record', 'beta', '--studio', studio, '--commit', git(studio, 'rev-parse', 'HEAD'),
               '--tests', 'DM-T02,DM-T03', '--evidence', 'docs/testing/evidence/beta.md', '--reviewed-by', 'verifier')[0] == 0
    write(studio, 'docs/testing/demo.md', TESTING.replace('| DM-T05 | DM-03 | guest opens the shared link |\n', ''))
    code, out, _ = run_json(capsys, 'check', '--studio', studio, '--item', 'zeta')
    assert code == 1 and [b['kind'] for b in out['broken']] == ['test-link']
    assert out['warnings'][0]['kind'] == 'untested-requirement'


def test_check_fails_on_ledger_gaps(capsys, studio):
    assert run(capsys, 'check', '--studio', studio, '--item', 'beta')[0] == 0
    write(studio, 'docs/requirements/demo.md', REQUIREMENTS + '| DM-05 | P0 | New row | DM-T05 |\n')
    code, out, _ = run(capsys, 'check', '--studio', studio, '--item', 'beta')
    assert code == 1 and 'GAP: requirement inventory changed: docs/requirements/demo.md' in out
    assert 'Verdict: reconcile the requirement ledger first (2 gaps); chain intact for 1 items' in out


def test_check_lab_link_by_item_id_or_unique_issue(capsys, studio, lab):
    (lab / align.LAB_DATA / 'features.ts').write_text(FEATURES.replace('ids: ["DM-03"]', 'ids: ["DM-04"]'))
    work = lab / align.LAB_DATA / 'work.json'
    data = json.loads(work.read_text())
    data['features']['sharing'] = [{'title': 'renamed packet', 'issue': 5}]
    work.write_text(json.dumps(data))
    assert run(capsys, 'check', '--studio', studio, '--item', 'zeta', '--lab', lab)[0] == 0  # #5 is zeta's alone
    manifest = load(studio)
    manifest['work_items'][4]['issue'] = 1  # now shared with alpha, whose work.json entry must not stand in
    save(studio, manifest)
    code, out, _ = run_json(capsys, 'check', '--studio', studio, '--item', 'zeta', '--lab', lab)
    assert code == 1 and [b['kind'] for b in out['broken']] == ['lab']


def test_drift_in_sync_then_reports_each_finding(capsys, studio, lab):
    code, out, _ = run_json(capsys, 'drift', '--studio', studio, '--lab', lab)
    assert code == 0 and out['findings'] == [] and out['commits_behind']['catalog.json'] == 0

    write(studio, 'docs/requirements/newer.md', '| NW-01 | P0 | New family | NW-T01 |\n')
    write(studio, 'docs/requirements/demo.md', REQUIREMENTS + '\nEdited.\n')
    write(studio, 'docs/plan/next.md', '# Next plan\n')
    manifest = load(studio)
    manifest['excluded']['docs/requirements/newer.md'] = {'reason': 'Draft family, not yet decomposed', 'sha256': 'x'}
    save(studio, manifest)
    (studio / 'docs/requirements/retired.md').unlink()
    code, out, _ = run_json(capsys, 'drift', '--studio', studio, '--lab', lab)
    assert code == 1
    found = {(f['kind'], f['path']) for f in out['findings']}
    assert found == {('unclassified', 'docs/requirements/newer.md'), ('removed', 'docs/requirements/retired.md'),
                     ('stale', 'docs/requirements/demo.md'), ('stale', 'docs/plan/next.md')}
    assert 'Draft family, not yet decomposed' in next(f['detail'] for f in out['findings'] if f['kind'] == 'unclassified')


def test_drift_reports_classification_disagreement(capsys, studio, lab):
    catalog = lab / align.LAB_CATALOG
    catalog.write_text(CATALOG.replace("'docs/requirements/retired.md'", "'docs/requirements/demo.md'"))
    code, out, _ = run_json(capsys, 'drift', '--studio', studio, '--lab', lab)
    assert code == 1
    assert ('classification', 'docs/requirements/demo.md') in {(f['kind'], f['path']) for f in out['findings']}
    assert ('unclassified', 'docs/requirements/retired.md') in {(f['kind'], f['path']) for f in out['findings']}


def test_parsers_read_the_lab_sources():
    assert align.parse_features(FEATURES) == {'notes': [('demo', ['DM-01', 'DM-02', 'DM-04'])],
                                              'sharing': [('demo', ['DM-03'])]}
    assert align.parse_catalog(CATALOG) == (['docs/requirements/demo.md'], ['docs/requirements/retired.md'])
    with pytest.raises(ValueError):
        align.parse_catalog('export const other = [];')


def test_skill_is_discoverable_by_codex_and_claude():
    canonical = ROOT / 'skills/hype-align/SKILL.md'
    for host in ('.agents', '.claude'):
        assert (ROOT / host / 'skills/hype-align/SKILL.md').resolve() == canonical


def test_cli_uses_the_environment_checkout_and_reports_failures(studio, tmp_path):
    env = {'PATH': '/usr/bin:/bin', 'HYPEPROOF_STUDIO': str(studio)}
    result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'next'], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert 'NEXT: beta #2' in result.stdout and result.stdout.rstrip().endswith('Verdict: next is beta (#2)')
    result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'next', '--studio', str(tmp_path / 'nowhere')],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 2 and 'could not evaluate' in result.stderr


def test_vendored_copy_skips_a_harness_checkout_that_predates_it(studio, tmp_path):
    # A consumer repo vendors the skill; HYPEPROOF_HARNESS points at an old Harness, the sibling is current.
    vendored = tmp_path / 'consumer/.claude/skills/hype-align/scripts/align.py'
    vendored.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, vendored)
    git(tmp_path / 'consumer', 'init', '-q')
    stale = tmp_path / 'stale/scripts/work-discovery/discover.py'
    write(tmp_path, 'stale/scripts/work-discovery/discover.py', 'def audit(root, manifest):\n    return []\n')
    write(tmp_path, 'hypeproof-harness/scripts/work-discovery/discover.py', (ROOT / 'scripts/work-discovery/discover.py').read_text())
    env = {'PATH': '/usr/bin:/bin', 'HYPEPROOF_HARNESS': str(tmp_path / 'stale'), 'HYPEPROOF_STUDIO': str(studio)}
    result = subprocess.run([sys.executable, '-B', str(vendored), 'next'], capture_output=True, text=True, env=env)
    assert result.returncode == 0 and 'Verdict: next is beta (#2)' in result.stdout, result.stderr
    shutil.rmtree(tmp_path / 'hypeproof-harness')
    result = subprocess.run([sys.executable, '-B', str(vendored), 'next'], capture_output=True, text=True, env=env)
    assert result.returncode == 2 and f'every Harness discover.py found predates hype-align ({stale})' in result.stderr
