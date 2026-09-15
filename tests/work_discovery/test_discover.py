import copy
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/work-discovery/discover.py'
spec = importlib.util.spec_from_file_location('discovery', SCRIPT)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'docs').mkdir()
        (self.root / 'docs/req.md').write_text('| REQ-01 | Keep files |\n')
        (self.root / 'docs/contract.md').write_text('Intent, design, controls and test plan')
        self.item = dict(id='files', title='Files', issue=1, kind='implementation',
                         requirements=[dict(path='docs/req.md', ids=['REQ-01'])],
                         next_action='Implement save', design_delta='Atomic save',
                         positive_control='Save then reopen', negative_control='Failed write preserves original',
                         evidence_required='Actual hashes', depends_on=[], verification_inputs=['code.py'])
        self.manifest = dict(repository='jayleekr/hypeproof-studio', requirement_globs=['docs/req*.md'],
                             documents=[dict(path='docs/req.md', ids=['REQ-01'], sha256=d.digest(self.root/'docs/req.md'),
                                             owner='owner', intent='docs/contract.md', design='docs/contract.md', test='docs/contract.md')],
                             work_items=[self.item])
        self.now = datetime.now(timezone.utc)
        self.snapshot = dict(repository=self.manifest['repository'], complete=True, fetched_at=self.now.isoformat(),
                             issues=[dict(number=1, state='OPEN', labels=[])], pull_requests=[])

    def state(self):
        return d.classify(self.root, self.manifest, self.snapshot, self.now)[0]['state']

    def test_positive_inventory_and_ready(self):
        self.assertEqual(d.audit(self.root, self.manifest), [])
        self.assertEqual(self.state(), 'ready')

    def test_added_and_modified_requirement(self):
        (self.root/'docs/req.md').write_text('| REQ-01 | Delete files |\n| REQ-02 | New |\n')
        errors=d.audit(self.root, self.manifest)
        self.assertTrue(any('inventory changed' in e for e in errors))
        self.assertTrue(any('content changed' in e for e in errors))

    def test_new_document_and_missing_source(self):
        (self.root/'docs/req2.md').write_text('| REQ-02 | New |\n')
        (self.root/'docs/req.md').unlink()
        errors=d.audit(self.root, self.manifest)
        self.assertTrue(any('unregistered document' in e for e in errors))
        self.assertTrue(any('missing document' in e for e in errors))

    def test_unassigned_requirement(self):
        self.item['requirements']=[]
        self.assertTrue(any('unassigned requirement' in e for e in d.audit(self.root, self.manifest)))

    def test_cycle(self):
        self.item['depends_on']=['files']
        self.assertTrue(any('cycle' in e for e in d.audit(self.root, self.manifest)))

    def test_closed_issue_is_not_completion(self):
        self.snapshot['issues'][0]['state']='CLOSED'
        self.assertEqual(self.state(), 'reconcile')

    def test_claim_age_and_unknown(self):
        issue=self.snapshot['issues'][0]
        issue['labels']=[{'name':'wip'}]
        self.assertEqual(self.state(), 'claimed')
        issue['claim_at']=(self.now-timedelta(hours=1)).isoformat()
        self.assertEqual(self.state(), 'claimed')
        issue['claim_at']=(self.now-timedelta(hours=25)).isoformat()
        self.assertEqual(self.state(), 'reconcile')

    def test_review_gate_and_dependency(self):
        self.snapshot['pull_requests']=[dict(number=3,issues=[1])]
        self.assertEqual(self.state(), 'in_review')
        self.snapshot['pull_requests']=[]
        self.item['gate']={'reason':'A real participant must provide consent'}
        self.assertEqual(self.state(), 'blocked')
        del self.item['gate']
        self.item['depends_on']=['other']
        self.assertEqual(self.state(), 'dependency')

    def complete_packet(self):
        (self.root/'code.py').write_text('original')
        (self.root/'report.md').write_text('REQ-01 PASS; REQ-02 NOT RUN')
        self.item['completion']=dict(verdict='PASS',reviewed_by='reviewer',report='report.md',scope_sha256=d.scope_digest(self.item),
                                     inputs={p:d.digest(self.root/p) for p in ['code.py','docs/req.md','report.md']})

    def test_completion_requires_current_implementation_inputs(self):
        self.complete_packet()
        self.assertEqual(self.state(), 'complete')
        (self.root/'code.py').write_text('changed')
        self.assertEqual(self.state(), 'ready')

    def test_completion_is_invalidated_when_packet_scope_expands(self):
        # X2 P1 on #162: same files, same report, but REQ-02 is added to the completed packet.
        (self.root/'docs/req.md').write_text('| REQ-01 | Keep files |\n| REQ-02 | New |\n')
        self.complete_packet()
        self.assertEqual(self.state(), 'complete')
        self.item['requirements']=[dict(path='docs/req.md', ids=['REQ-01','REQ-02'])]
        self.assertEqual(self.state(), 'ready')

    def test_completion_is_invalidated_when_acceptance_contract_changes(self):
        self.complete_packet()
        self.item['negative_control']='Failed write preserves original AND reports the error'
        self.assertEqual(self.state(), 'ready')
        self.item['negative_control']='Failed write preserves original'
        self.assertEqual(self.state(), 'complete')
        self.item['next_action']='Unrelated wording change'
        self.assertEqual(self.state(), 'complete')

    def test_completion_without_scope_digest_fails_closed(self):
        self.complete_packet()
        del self.item['completion']['scope_sha256']
        self.assertEqual(self.state(), 'ready')

    def test_explicit_pr_references_count_as_active_work(self):
        # X2 P2 on #162: a PR body saying "Refs #1020, #852" overlaps the #852 packet.
        repo='jayleekr/hypeproof-studio'
        rel=lambda text, closing=(): d.issue_relations(repo, text, closing)
        self.assertEqual(rel('Refs #1020, #852', [1021]), dict(closing=[1021], related=[852, 1020], mentions=[]))
        self.assertEqual(rel('See jayleekr/hypeproof-studio#852 and other/repo#9')['related'], [852])
        self.assertEqual(rel('Part of https://github.com/jayleekr/hypeproof-studio/issues/852 https://github.com/other/repo/issues/7'),
                         dict(closing=[], related=[852], mentions=[]))
        self.assertEqual(rel('heading ## 3 and a#5 token'), dict(closing=[], related=[], mentions=[]))
        self.snapshot['pull_requests']=[d.pull_request_entry(repo, dict(number=1025, title='', body='Refs #1020, #1',
                                                                         closingIssuesReferences=[dict(number=1021)]))]
        self.assertEqual(self.state(), 'in_review')

    def test_prose_mentions_are_reported_but_do_not_hide_ready_work(self):
        # Review on #162: a contrast or follow-up note is not a work relation. The packet stays ready
        # and the mention stays visible.
        repo='jayleekr/hypeproof-studio'
        self.assertEqual(d.issue_relations(repo, '#1 과 달리 이 PR 은 저장만 고친다. #456 후속'),
                         dict(closing=[], related=[], mentions=[1, 456]))
        self.snapshot['pull_requests']=[d.pull_request_entry(repo, dict(number=1030, title='fix: unlike #1', body='',
                                                                         closingIssuesReferences=[]))]
        row=d.classify(self.root, self.manifest, self.snapshot, self.now)[0]
        self.assertEqual(row['state'], 'ready')
        self.assertEqual(row['mentioned_in_prs'], [1030])
        self.assertIn('#1030', row['reason'])

    def test_live_snapshot_keeps_non_closing_references(self):
        calls=[]
        def fake_gh(*args):
            calls.append(args)
            if args[0]=='api' and '/comments' in args[-1]:
                return [[dict(created_at='2026-09-15T00:00:00Z', body='작업 시작')]]
            if args[0]=='api':
                return [[dict(number=1, state='open', labels=[dict(name='wip')]),
                         dict(number=2, state='open', labels=[dict(name='wip')])]]
            return [dict(number=1025, title='docs(measurement)', body='Refs #1020, #1; unlike #7',
                         closingIssuesReferences=[dict(number=1021)])]
        original=d.gh; d.gh=fake_gh
        try:
            snap=d.live_snapshot('jayleekr/hypeproof-studio', {1})
        finally:
            d.gh=original
        self.assertIn('body', calls[-1][calls[-1].index('--json')+1])
        self.assertEqual(snap['pull_requests'], [dict(number=1025, issues=[1, 1020, 1021], closing=[1021], mentions=[7])])
        # Claim comments are fetched for the tracked wip issue only, not for untracked wip #2.
        self.assertEqual([c for c in calls if '/comments' in c[-1]], [calls[1]])
        self.assertEqual(snap['issues'][0]['claim_at'], '2026-09-15T00:00:00Z')
        self.assertNotIn('claim_at', snap['issues'][1])

    def test_scope_digest_cli(self):
        manifest=self.root/'manifest.json'; manifest.write_text(json.dumps(self.manifest))
        result=subprocess.run(['python3',str(SCRIPT),'--checkout',str(self.root),'--manifest','manifest.json','--scope-digest','files'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(), d.scope_digest(self.item))

    def test_requirement_only_completion_is_not_enough(self):
        (self.root/'report.md').write_text('claims PASS')
        self.item['verification_inputs']=[]
        self.item['completion']=dict(verdict='PASS',reviewed_by='reviewer',report='report.md',
                                     inputs={p:d.digest(self.root/p) for p in ['docs/req.md','report.md']})
        self.assertEqual(self.state(),'ready')

    def test_voice_and_inline_ids_do_not_include_prose_references_by_default(self):
        text='### VO-01\nText VO-02.\n| TUX-SP-01 | test |\nNAT-01은 정의다.'
        self.assertEqual(d.requirement_ids(text),['TUX-SP-01','VO-01'])
        self.assertIn('NAT-01',d.requirement_ids(text,['NAT']))

    def test_cli_stale_snapshot_and_no_work_guard(self):
        manifest=self.root/'manifest.json'; manifest.write_text(json.dumps(self.manifest))
        snapshot=self.root/'snapshot.json'
        self.snapshot['fetched_at']=(self.now-timedelta(hours=2)).isoformat()
        snapshot.write_text(json.dumps(self.snapshot))
        args=['python3',str(SCRIPT),'--checkout',str(self.root),'--manifest','manifest.json','--snapshot',str(snapshot),'--json']
        result=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('availability unknown',result.stderr)
        self.snapshot['fetched_at']=self.now.isoformat()
        self.snapshot['issues'][0]['state']='CLOSED'
        snapshot.write_text(json.dumps(self.snapshot))
        result=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout)['no_remaining_work'])


if __name__ == '__main__':
    unittest.main()
