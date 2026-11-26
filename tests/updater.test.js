const test = require('node:test');
const assert = require('node:assert/strict');
const { watch, HALF_HOUR } = require('../site/updater.js');

function target() {
  const handlers = {};
  return { handlers, addEventListener: (type, fn) => { (handlers[type] = handlers[type] || []).push(fn); }, fire: (type) => (handlers[type] || []).forEach((fn) => fn()) };
}
function setup({ controller = {}, registration = { update: () => { setup.updates += 1; return Promise.resolve(); } } } = {}) {
  setup.updates = 0;
  const sw = Object.assign(target(), { controller, getRegistration: () => Promise.resolve(registration) });
  const doc = Object.assign(target(), { hidden: false });
  const bar = { hidden: true }, reload = target(), dismiss = target();
  const timers = [];
  let reloaded = 0;
  watch({ serviceWorker: sw, document: doc, bar, reload, dismiss, reloadPage: () => { reloaded += 1; }, every: (fn, ms) => timers.push([fn, ms]) });
  return { sw, doc, bar, reload, dismiss, timers, reloaded: () => reloaded };
}
const tick = () => new Promise((r) => setImmediate(r));

test('the bar appears when a new version takes over a page that was already controlled', () => {
  const t = setup();
  assert.equal(t.bar.hidden, true);
  t.sw.fire('controllerchange');
  assert.equal(t.bar.hidden, false);
});

test('the bar does not appear on the first visit, when there was no earlier version', () => {
  const t = setup({ controller: null });
  t.sw.fire('controllerchange');
  assert.equal(t.bar.hidden, true);
});

test('Reload reloads the page and the cross hides the bar until the next version', () => {
  const t = setup();
  t.sw.fire('controllerchange');
  t.reload.fire('click');
  assert.equal(t.reloaded(), 1);
  t.dismiss.fire('click');
  assert.equal(t.bar.hidden, true);
  t.sw.fire('controllerchange');
  assert.equal(t.bar.hidden, false, 'a later version shows it again');
});

test('a newer version is looked for when the app returns to the foreground, not when it is hidden, and every half hour', async () => {
  const t = setup();
  t.doc.hidden = true; t.doc.fire('visibilitychange'); await tick();
  assert.equal(setup.updates, 0);
  t.doc.hidden = false; t.doc.fire('visibilitychange'); await tick();
  assert.equal(setup.updates, 1);
  assert.deepEqual(t.timers.map(([, ms]) => ms), [HALF_HOUR]);
  t.timers[0][0](); await tick();
  assert.equal(setup.updates, 2);
});

test('an offline or missing registration never throws', async () => {
  const none = setup({ registration: null });
  none.doc.fire('visibilitychange'); await tick();
  const failing = setup({ registration: { update: () => Promise.reject(new Error('offline')) } });
  failing.doc.fire('visibilitychange'); await tick();
  assert.equal(watch({ serviceWorker: null, bar: {} }), false, 'a browser without service workers is left alone');
});
