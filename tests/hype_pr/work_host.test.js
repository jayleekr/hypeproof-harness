const {test} = require('node:test');
const assert = require('node:assert/strict');
const {serveWorkRequest} = require('../../scripts/hype-pr/work_host.js');
const sha = 'a'.repeat(40), head = 'b'.repeat(40);
const wrap = data => ({structuredContent: data});
function fixture() {
  const calls = [];
  const options = {repositories: ['x/one', 'x/two'], repo: 'x/one', branch: 'fix/example',
    author: 'owner', reviewers: ['reviewer'], allowCreate: true, cache: new Map()};
  const tools = {
    mcp__codex_apps__github_fetch: async ({url}) => {
      calls.push(url);
      return wrap({content: JSON.stringify({sha: url.endsWith('/fix/example') ? head : sha})});
    },
    mcp__codex_apps__github_get_user_login: async () => wrap({login: 'owner'}),
    mcp__codex_apps__github_fetch_file: async args => {
      calls.push(args.path); return wrap({encoding: 'base64', content: 'c291cmNl'});
    },
    mcp__codex_apps__github_create_pull_request: async args => {
      calls.push(args); return wrap({number: 9, url: 'https://github.com/x/one/pull/9'});
    },
    mcp__codex_apps__github_request_pull_request_reviewers: async args => {calls.push(args); return wrap({});},
    mcp__codex_apps__github_remove_pull_request_reviewers: async args => {calls.push(args); return wrap({});},
  };
  const request = {version: 1, id: 'a'.repeat(32), operation: 'create', payload: {
    repo: 'x/one', head: 'fix/example', base: 'main', author: 'owner', title: 'Fix',
    body: '<!-- hype-pr-prepared:v1 -->', expected: {head, base: sha, sources: {'x/one': head, 'x/two': sha}},
  }};
  return {calls, options, tools, request};
}
test('live refs precede create; repeated mutations and out-of-scope reviewers fail', async () => {
  const f = fixture();
  const result = await serveWorkRequest(f.tools, f.request, f.options);
  assert.equal(result.number, 9);
  assert.equal(f.calls.filter(x => typeof x === 'string').length, 3);
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /repeated/);
  const req = {...f.request, operation: 'reviewer', payload: {repo: 'x/one', pr: result.url, reviewer: 'reviewer'}};
  await serveWorkRequest(f.tools, req, f.options);
  const remove = {...f.request, operation: 'unreviewer', payload: {repo: 'x/one', pr: result.url, reviewer: 'reviewer'}};
  await serveWorkRequest(f.tools, remove, f.options);
  remove.payload.reviewer = 'intruder';
  await assert.rejects(serveWorkRequest(f.tools, remove, f.options), /scope/);
  req.payload.reviewer = 'intruder';
  await assert.rejects(serveWorkRequest(f.tools, req, f.options), /scope/);
});
test('changed upstream prevents creation', async () => {
  const f = fixture(); f.request.payload.expected.sources['x/two'] = 'c'.repeat(40);
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /advanced/);
  assert.equal(f.calls.filter(x => typeof x !== 'string').length, 0);
});
test('connector errors never become empty source', async () => {
  const f = fixture(); f.tools.mcp__codex_apps__github_fetch = async () => ({isError: true});
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /failed/);
});
test('read-only host refuses mutation and foreign repo reads', async () => {
  const f = fixture(); f.options.allowCreate = false;
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /Mutation/);
  await assert.rejects(serveWorkRequest(f.tools, {...f.request, operation: 'read',
    payload: {path: 'repos/foreign/repo/contents/file'}}, f.options), /scope/);
});
test('only immutable content is cached; live refs are never reused', async () => {
  const f = fixture();
  const read = path => serveWorkRequest(f.tools, {...f.request, operation: 'read', payload: {path}}, f.options);
  await read('repos/x/one/contents/doc?ref=' + sha);
  await read('repos/x/one/contents/doc?ref=' + sha);
  await read('repos/x/one/commits/main'); await read('repos/x/one/commits/main');
  assert.equal(f.calls.length, 3);
});
test('uncertain create failure is not retried', async () => {
  const f = fixture(); f.tools.mcp__codex_apps__github_create_pull_request = async () => {throw new Error('network');};
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /network/);
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /repeated/);
});
test('actor mismatch blocks create', async () => {
  const f = fixture(); f.options.author = f.request.payload.author = 'other';
  await assert.rejects(serveWorkRequest(f.tools, f.request, f.options), /actor/);
});
