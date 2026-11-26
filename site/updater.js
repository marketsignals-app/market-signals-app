/* "A new version is ready": the service worker (sw.js) takes over as soon as a new one is installed, and then the page that is open is the old one. A slim bar
 * says so and offers a reload. It is not shown on the very first visit, when nothing was replaced. The app also asks for a newer version when it comes back to
 * the foreground and every half hour, so an installed copy that stays open notices a release without being closed.
 * Everything it touches is passed in, so it can be tested in Node with fakes. */
(function (root) {
  'use strict';

  const HALF_HOUR = 30 * 60 * 1000;

  function watch(env) {
    const sw = env.serviceWorker;
    if (!sw || !env.bar) return false;
    const hadController = !!sw.controller;
    sw.addEventListener('controllerchange', () => { if (hadController) env.bar.hidden = false; });
    if (env.reload) env.reload.addEventListener('click', () => env.reloadPage());
    if (env.dismiss) env.dismiss.addEventListener('click', () => { env.bar.hidden = true; });
    const look = () => { Promise.resolve(sw.getRegistration()).then((r) => (r ? r.update() : null)).catch(() => { /* offline: the next look tries again */ }); };
    if (env.document) env.document.addEventListener('visibilitychange', () => { if (!env.document.hidden) look(); });
    if (env.every) env.every(look, HALF_HOUR);
    return true;
  }

  const api = { watch, HALF_HOUR };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Updater = api;
}(typeof window !== 'undefined' ? window : globalThis));
