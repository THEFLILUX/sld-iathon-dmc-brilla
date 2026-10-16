(function () {
  'use strict';
  // "Tiempo restante mm:ss" of the one-hour validation window (teacher only; students never see a timer).
  var counters = document.querySelectorAll('[data-deadline]');
  function tick() {
    var now = Date.now();
    counters.forEach(function (el) {
      var left = Math.max(0, Math.floor((Date.parse(el.getAttribute('data-deadline')) - now) / 1000));
      var m = Math.floor(left / 60), s = left % 60;
      el.textContent = left > 0 ? m + ':' + (s < 10 ? '0' : '') + s : 'publicando…';
      if (left === 0 && !el.dataset.reloaded) { el.dataset.reloaded = '1'; setTimeout(function () { window.location.reload(); }, 5000); }
    });
  }
  if (counters.length) { tick(); setInterval(tick, 1000); }

  // The mastery rubric follows the current selection, preserving edits until the form is saved.
  document.querySelectorAll('[data-nivel-maximo]').forEach(function (select) {
    var rubric = select.closest('form').querySelector('[data-rubrica-maestria]');
    if (!rubric) return;
    function update() {
      var mastery = select.value === 'maestria';
      rubric.hidden = !mastery;
      rubric.disabled = !mastery;
    }
    select.addEventListener('change', update);
    update();
  });

  // Show only the fields that apply to the selected challenge type.
  document.querySelectorAll('[data-tipo-select]').forEach(function (select) {
    var form = select.closest('form');
    function update() {
      form.querySelectorAll('[data-para-tipo]').forEach(function (field) {
        field.hidden = field.getAttribute('data-para-tipo').split(' ').indexOf(select.value) === -1;
      });
    }
    select.addEventListener('change', update);
    update();
  });

  // A basic-only topic has no other levels for the AI to complete.
  document.querySelectorAll('[data-ai-topic-form]').forEach(function (form) {
    var select = form.querySelector('[name="tema_id"]');
    var button = form.querySelector('button[type="submit"]');
    function update() {
      var option = select.options[select.selectedIndex];
      var active = !!option && option.getAttribute('data-ai-completes') === 'si';
      button.toggleAttribute('data-ai-action', active);
      if (active) button.setAttribute('title', 'Brilla · Acción con inteligencia artificial');
      else button.removeAttribute('title');
      button.querySelector('.ai-mark').hidden = !active;
      button.querySelector('[data-ai-label]').hidden = !active;
    }
    select.addEventListener('change', update);
    update();
  });

  // Upload feedback while a large recording is being sent.
  document.querySelectorAll('[data-upload]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      var status = form.querySelector('[data-status]');
      var button = form.querySelector('[data-submit]');
      if (status) status.textContent = 'Subiendo archivo…';
      if (button) button.disabled = true;
    });
  });
})();
