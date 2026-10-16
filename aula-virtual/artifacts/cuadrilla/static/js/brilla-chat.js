(function () {
  'use strict';
  var form = document.querySelector('[data-chat-form]');
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && window.parent !== window) window.parent.postMessage({type: 'brilla:close'}, location.origin);
  });
  if (!form) return;
  var question = form.querySelector('#chat-question');
  var messages = form.querySelector('[data-chat-messages]');
  var welcome = form.querySelector('[data-chat-welcome]');
  var status = form.querySelector('[data-chat-status]');
  var submit = form.querySelector('button[type="submit"]');
  var course = form.querySelector('[data-chat-course]');
  var student = form.querySelector('#chat-student');
  var period = form.querySelector('#chat-period');
  var reset = form.querySelector('[data-chat-reset]');
  var busy = false;
  function clear() {
    messages.querySelectorAll('[data-chat-turn]').forEach(function (turn) { turn.remove(); });
    welcome.hidden = false;
    status.textContent = '';
  }
  function setBusy(value) {
    busy = value;
    [submit, course, student, period, reset].forEach(function (field) { field.disabled = value; });
    submit.classList.toggle('is-ai-busy', value);
    submit.setAttribute('aria-busy', String(value));
    status.textContent = value ? 'Brilla está revisando los registros…' : '';
  }
  course.addEventListener('change', function () {
    var target = new URL(course.dataset.url, location.href);
    target.searchParams.set('curso_id', course.value);
    location.assign(target.href);
  });
  [student, period].forEach(function (field) { field.addEventListener('change', clear); });
  reset.addEventListener('click', function () { clear(); question.value = ''; question.focus(); });
  form.querySelectorAll('[data-chat-question]').forEach(function (button) {
    button.addEventListener('click', function () { question.value = button.dataset.chatQuestion; question.focus(); });
  });
  messages.addEventListener('click', function (event) {
    var closer = event.target.closest('[data-chat-error-close]');
    if (closer) { closer.closest('[data-chat-answer]').remove(); question.focus(); return; }
    var link = event.target.closest('.assistant-citations a');
    if (!link) return;
    var source = document.getElementById(link.hash.slice(1));
    if (source) { event.preventDefault(); source.open = true; source.scrollIntoView({block: 'start'}); source.querySelector('summary').focus(); }
  });
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    // Capture enabled filters before locking the controls for this request.
    var data = new FormData(form);
    var text = question.value;
    var turn = document.createElement('div');
    turn.dataset.chatTurn = '';
    var user = document.createElement('div');
    user.className = 'brilla-chat-question';
    var scope = document.createElement('small');
    scope.textContent = student.options[student.selectedIndex].text + ' · ' + period.options[period.selectedIndex].text;
    var copy = document.createElement('p');
    copy.textContent = text;
    user.append(scope, copy);
    turn.append(user);
    messages.append(turn);
    welcome.hidden = true;
    setBusy(true);
    user.scrollIntoView({block: 'start'});
    try {
      var response = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin',
        headers: {'X-Brilla-Chat': '1', 'Accept': 'text/html'}});
      var documentResult = new DOMParser().parseFromString(await response.text(), 'text/html');
      var answer = documentResult.querySelector('[data-chat-answer]');
      if (!answer) throw new Error(response.status === 403 || response.redirected ?
        'Tu sesión venció o cambió el acceso. Recarga la página para volver a consultar.' : 'No pudimos obtener una respuesta. Inténtalo de nuevo.');
      // Only escaped, same-origin Jinja output is inserted; model text is never HTML.
      turn.append(document.importNode(answer, true));
      if (response.ok && question.value === text) question.value = '';
      status.textContent = response.ok ? 'Respuesta lista. Puedes revisar las evidencias.' : 'No se completó la consulta. Puedes reintentar.';
    } catch (error) {
      var failure = document.createElement('div');
      failure.className = 'brilla-chat-error';
      failure.setAttribute('data-chat-answer', '');
      failure.setAttribute('role', 'alert');
      var dismiss = document.createElement('button');
      dismiss.type = 'button'; dismiss.className = 'icon-btn'; dismiss.dataset.chatErrorClose = '';
      dismiss.setAttribute('aria-label', 'Cerrar aviso'); dismiss.textContent = '×';
      var message = document.createElement('p');
      message.textContent = error.message === 'Failed to fetch' ? 'No pudimos conectar. Revisa tu conexión y vuelve a enviar la consulta.' : error.message;
      failure.append(dismiss, message); turn.append(failure);
      status.textContent = 'No se completó la consulta.';
    } finally {
      var finalStatus = status.textContent;
      setBusy(false);
      status.textContent = finalStatus;
      user.scrollIntoView({block: 'start'});
    }
  });
})();
