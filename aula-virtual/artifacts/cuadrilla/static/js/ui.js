(function () {
  'use strict';
  var body = document.body;
  var toggle = document.querySelector('[data-menu-toggle]');
  var sidebar = document.querySelector('[data-sidebar]');
  var scrim = document.querySelector('[data-scrim]');

  // Notifications live outside the page layout. Show one at a time, with no time limit.
  var notifications = document.querySelector('[data-notifications]');
  if (notifications) {
    var notices = Array.from(notifications.querySelectorAll('[data-notification]'));
    var controls = notifications.querySelector('[data-notification-controls]');
    var nextNotice = notifications.querySelector('[data-notification-next]');
    var currentNotice = 0;
    function showNotice() {
      notifications.hidden = !notices.length;
      notices.forEach(function (notice, index) { notice.hidden = index !== currentNotice; });
      controls.hidden = notices.length < 2;
      notifications.querySelector('[data-notification-count]').textContent = notices.length + ' avisos';
      if (notices[currentNotice]) {
        var copy = notices[currentNotice].querySelector('.notification-copy');
        // Long validation lists remain readable by keyboard without growing over the page.
        if (copy.scrollHeight > copy.clientHeight) copy.setAttribute('tabindex', '0');
      }
    }
    notices.forEach(function (notice) {
      notice.querySelector('[data-notification-close]').addEventListener('click', function () {
        var restoreFocus = notice.contains(document.activeElement);
        if (notice.hasAttribute('data-notification-flash')) {
          var url = new URL(window.location.href);
          url.searchParams.delete('ok');
          window.history.replaceState(window.history.state, '', url);
        }
        notices.splice(notices.indexOf(notice), 1);
        notice.remove();
        currentNotice = Math.min(currentNotice, Math.max(0, notices.length - 1));
        showNotice();
        if (restoreFocus) {
          var target = notices[currentNotice] ? notices[currentNotice].querySelector('[data-notification-close]') : document.querySelector('#contenido');
          if (target) target.focus({preventScroll: true});
        }
      });
    });
    nextNotice.addEventListener('click', function () {
      currentNotice = (currentNotice + 1) % notices.length;
      showNotice();
    });
    showNotice();
  }

  function setMenu(open) {
    if (!toggle || !sidebar) return;
    body.classList.toggle('menu-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
    toggle.querySelector('[data-icon-open]').hidden = open;
    toggle.querySelector('[data-icon-close]').hidden = !open;
    if (scrim) scrim.hidden = !open;
  }
  if (toggle) {
    toggle.addEventListener('click', function () { setMenu(!body.classList.contains('menu-open')); });
    if (scrim) scrim.addEventListener('click', function () { setMenu(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && body.classList.contains('menu-open')) { setMenu(false); toggle.focus(); }
    });
    window.addEventListener('resize', function () { if (window.innerWidth > 800) setMenu(false); });
  }

  // Shared confirmation for every profile. requestSubmit preserves the clicked action.
  var dialog = document.querySelector('[data-confirm-dialog]');
  var pending = null;
  var confirmForms = new Set(document.querySelectorAll('form[data-confirm], form[data-delete]'));
  document.querySelectorAll('button[data-confirm]').forEach(function (button) {
    if (button.form) confirmForms.add(button.form);
  });
  confirmForms.forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      if (form.dataset.confirmed === '1') { delete form.dataset.confirmed; return; }
      var button = e.submitter || form.querySelector('button[type="submit"]');
      var message = (button && button.getAttribute('data-confirm')) || form.getAttribute('data-confirm');
      if (!message && !form.hasAttribute('data-delete')) return;
      message = message || '¿Eliminar definitivamente estos datos? Esta acción no se puede deshacer.';
      if (!dialog || !dialog.showModal) {
        if (!window.confirm(message)) e.preventDefault();
        return;
      }
      e.preventDefault();
      if (pending) return;
      pending = {form: form, button: button};
      dialog.querySelector('#confirm-title').textContent = form.getAttribute('data-confirm-title') || 'Confirmar acción';
      dialog.querySelector('#confirm-copy').textContent = message;
      dialog.querySelector('[data-confirm-accept]').textContent = form.getAttribute('data-confirm-label') || 'Confirmar';
      dialog.showModal();
      dialog.querySelector('[data-confirm-cancel]').focus();
    });
  });
  if (dialog) {
    dialog.querySelector('[data-confirm-cancel]').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('close', function () { pending = null; });
    dialog.querySelector('[data-confirm-accept]').addEventListener('click', function () {
      if (!pending) return;
      var action = pending;
      pending = null;
      dialog.close();
      action.form.dataset.confirmed = '1';
      action.form.requestSubmit(action.button || undefined);
      delete action.form.dataset.confirmed;
    });
  }

  // Avoid double submissions on slow requests.
  document.querySelectorAll('form[method="post"]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      if (form.dataset.sent === '1') { e.preventDefault(); return; }
      form.dataset.sent = '1';
      setTimeout(function () { form.dataset.sent = ''; }, 8000);
    });
  });

  // The clicked action alone gets AI feedback; keep its name/value in the POST.
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var button = e.submitter || form.querySelector('button[type="submit"]');
      queueMicrotask(function () {
        if (e.defaultPrevented || !button || !button.hasAttribute('data-ai-action')) return;
        button.classList.add('is-ai-busy');
        button.setAttribute('aria-busy', 'true');
      });
    });
  });
  // A browser Back navigation can restore the submitted page from its cache.
  window.addEventListener('pageshow', function () {
    if (dialog && dialog.open) dialog.close();
    pending = null;
    document.querySelectorAll('.is-ai-busy').forEach(function (button) {
      button.classList.remove('is-ai-busy');
      button.removeAttribute('aria-busy');
    });
    document.querySelectorAll('form[data-sent]').forEach(function (form) { form.dataset.sent = ''; });
  });

  // Pages waiting for background work reload themselves (processing, pending grading).
  var refresh = parseInt(body.getAttribute('data-refresh') || '0', 10);
  if (refresh > 0) {
    function refreshPage() {
      var typing = document.activeElement && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
      if (typing || (dialog && dialog.open)) setTimeout(refreshPage, refresh * 1000);
      else window.location.reload();
    }
    setTimeout(refreshPage, refresh * 1000);
  }
})();
