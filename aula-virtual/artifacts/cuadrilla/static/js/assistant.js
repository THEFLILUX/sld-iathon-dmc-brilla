(function () {
  'use strict';
  var form = document.querySelector('[data-assistant-form]');
  if (!form) return;
  var question = form.querySelector('#assistant-question');
  document.querySelectorAll('[data-assistant-question]').forEach(function (button) {
    button.addEventListener('click', function () {
      question.value = button.getAttribute('data-assistant-question');
      question.focus();
    });
  });
  form.addEventListener('submit', function (event) {
    if (event.defaultPrevented) return;
    form.querySelector('[data-assistant-status]').hidden = false;
    // No name/value needs preserving on this submit button.
    var button = form.querySelector('[data-ai-action]');
    if (button) setTimeout(function () { button.disabled = true; }, 0);
  });
  window.addEventListener('pageshow', function () {
    form.querySelector('[data-assistant-status]').hidden = true;
    var button = form.querySelector('[data-ai-action]');
    if (button) button.disabled = false;
  });
  var answer = document.querySelector('[data-assistant-answer]');
  if (answer) answer.focus({preventScroll: true});
  document.querySelectorAll('.assistant-citations a').forEach(function (link) {
    link.addEventListener('click', function () {
      var source = document.getElementById(link.hash.slice(1));
      if (source) source.open = true;
    });
  });
})();
