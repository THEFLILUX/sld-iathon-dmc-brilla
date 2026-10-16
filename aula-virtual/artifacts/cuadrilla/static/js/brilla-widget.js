(function () {
  'use strict';
  var launcher = document.querySelector('[data-brilla-launch]');
  var panel = document.querySelector('[data-brilla-panel]');
  if (!launcher || !panel || !panel.show) return;
  var frame = panel.querySelector('[data-brilla-frame]');
  var returnFocus = launcher;
  var loadedTarget = '';
  function close() {
    panel.close();
    launcher.setAttribute('aria-expanded', 'false');
    launcher.hidden = false;
    returnFocus.focus({preventScroll: true});
  }
  function open(trigger) {
    returnFocus = trigger;
    var target = new URL(frame.dataset.src, location.href);
    if (trigger.dataset.brillaCourse) target.searchParams.set('curso_id', trigger.dataset.brillaCourse);
    if (trigger.dataset.brillaStudent) target.searchParams.set('alumno_id', trigger.dataset.brillaStudent);
    // Minimizing preserves the current draft, filters and messages in memory.
    if (!loadedTarget || trigger !== launcher) {
      frame.src = target.href;
      loadedTarget = target.href;
    }
    if (!panel.open) panel.show();
    launcher.setAttribute('aria-expanded', 'true');
    launcher.hidden = true;
    panel.querySelector('[data-brilla-close]').focus();
  }
  launcher.addEventListener('click', function (event) { event.preventDefault(); open(launcher); });
  panel.querySelector('[data-brilla-close]').addEventListener('click', close);
  document.querySelectorAll('[data-brilla-open]').forEach(function (trigger) {
    trigger.addEventListener('click', function (event) { event.preventDefault(); open(trigger); });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && panel.open) { event.preventDefault(); close(); }
  });
  window.addEventListener('message', function (event) {
    if (event.origin === location.origin && event.source === frame.contentWindow && event.data && event.data.type === 'brilla:close' && panel.open) close();
  });
})();
