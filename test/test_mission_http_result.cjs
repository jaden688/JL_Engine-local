const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../BYTE/src/ui.html'), 'utf8');
const source = html.slice(html.indexOf('function missionSend()'), html.indexOf('function bcNav()'));
function fixture(fetch) {
  const nodes = {
    'mission-input': { value: 'inspect status' },
    'mission-status': { textContent: 'idle', className: 'idle' },
    'mission-visual-mode': { checked: false }
  };
  const messages = [], terminal = [];
  const context = vm.createContext({
    $: id => nodes[id], fetch, console,
    agentSelect: { value: 'SparkByte' }, _missionRunning: false,
    _missionRequestId: 0, renderTabs() {},
    send: message => messages.push(message),
    termPrint: (text, kind) => terminal.push({text, kind})
  });
  vm.runInContext(source, context);
  return { context, nodes, messages, terminal };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  let failures = 0;
  async function check(name, run) {
    try { await run(); console.log('PASS', name); }
    catch (error) { failures++; console.error('FAIL', name, error.message); }
  }
  await check('HTTP tool error ends mission as FAILED and displays the reason', async () => {
    const f = fixture(async () => ({ok:false, status:500, json:async () => ({ok:false,status:'failed',error:'Missing path'})}));
    f.context.missionSend(); await settle(); await settle();
    assert.equal(f.nodes['mission-status'].textContent, 'FAILED');
    assert.equal(f.context._missionRunning, false);
    assert(f.terminal.some(x => x.kind === 'error' && x.text.includes('Missing path')));
  });
  await check('HTTP success ends mission as COMPLETED', async () => {
    const f = fixture(async () => ({ok:true,status:200,json:async () => ({ok:true,status:'completed',result:'Actual result'})}));
    f.context.missionSend(); await settle(); await settle();
    assert.equal(f.nodes['mission-status'].textContent, 'COMPLETED');
    assert.equal(f.context._missionRunning, false);
    assert(f.terminal.some(x => x.text.includes('Actual result')));
  });
  await check('network failure ends mission as FAILED', async () => {
    const f = fixture(async () => { throw new Error('Connection lost'); });
    f.context.missionSend(); await settle(); await settle();
    assert.equal(f.nodes['mission-status'].textContent, 'FAILED');
    assert(f.terminal.some(x => x.kind === 'error' && x.text.includes('Connection lost')));
  });
  await check('late completion cannot overwrite an aborted mission', async () => {
    let resolveDispatch;
    const f = fixture(url => url === '/control/cancel'
      ? Promise.resolve({ok:true,json:async () => ({ok:true})})
      : new Promise(resolve => {resolveDispatch=resolve;}));
    f.context.missionSend(); f.context.missionAbort();
    resolveDispatch({ok:true,status:200,json:async () => ({ok:true,status:'completed',result:'late'})});
    await settle(); await settle();
    assert.equal(f.nodes['mission-status'].textContent, 'ABORTED');
  });
  await check('duplicate GO does not dispatch another task', async () => {
    let calls=0;
    const f=fixture(() => {calls++;return new Promise(() => {});});
    f.context.missionSend(); f.nodes['mission-input'].value='second goal'; f.context.missionSend();
    assert.equal(calls,1);
  });
  process.exitCode = failures ? 1 : 0;
})();
