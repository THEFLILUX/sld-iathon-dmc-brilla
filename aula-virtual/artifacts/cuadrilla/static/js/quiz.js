(function () {
  'use strict';
  var body = document.body;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Answer form: enable "Enviar" only with an answer; open answers need a minimum length.
  document.querySelectorAll('[data-answer-form]').forEach(function (form) {
    var button = form.querySelector('[data-submit]');
    var status = form.querySelector('[data-status]');
    var minimo = parseInt(form.getAttribute('data-min') || '0', 10);
    var abierta = form.getAttribute('data-open') === 'si';
    function valor() {
      var checked = form.querySelector('input[name="respuesta"]:checked');
      if (checked) return checked.value;
      var field = form.querySelector('textarea[name="respuesta"], input[name="respuesta"]:not([type="radio"])');
      return field ? field.value.trim() : '';
    }
    function update() {
      var v = valor();
      var ok = v.length > 0 && (!abierta || v.length >= minimo);
      button.disabled = !ok;
      if (status) status.textContent = abierta && v.length > 0 && v.length < minimo ? 'Faltan ' + (minimo - v.length) + ' caracteres' : '';
    }
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    update();
    form.addEventListener('submit', function () {
      if (status) status.textContent = abierta ? 'Revisando tu respuesta…' : 'Enviando…';
    });
  });

  // Celebration: confetti and streamers for 1.6 s, then the feedback. Once per challenge.
  var key = body.getAttribute('data-celebrate');
  if (!key) return;
  var storageKey = 'cuadrilla-celebrado-' + key;
  try { if (sessionStorage.getItem(storageKey)) return; sessionStorage.setItem(storageKey, '1'); } catch (e) { /* private mode */ }
  if (reduce) return;

  var canvas = document.createElement('canvas');
  canvas.className = 'confetti-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.appendChild(canvas);
  var ctx = canvas.getContext('2d');
  if (!ctx) return;
  body.classList.add('celebrating');
  var w, h, ratio = window.devicePixelRatio || 1;
  function resize() {
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = w * ratio; canvas.height = h * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  resize();
  var colors = ['#007CBB', '#00BFD7', '#f5b700', '#e0675b', '#1b7a3d', '#ffffff'];
  var pieces = [];
  for (var i = 0; i < 140; i++) {
    var streamer = i % 7 === 0;
    pieces.push({
      x: Math.random() * w, y: -20 - Math.random() * h * 0.5,
      vx: (Math.random() - 0.5) * 3, vy: 2 + Math.random() * 3.5,
      size: streamer ? 3 : 5 + Math.random() * 5, len: streamer ? 26 + Math.random() * 30 : 0,
      rot: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.2,
      color: colors[i % colors.length], phase: Math.random() * 6.28
    });
  }
  var start = performance.now();
  var DURATION = 1600;
  var terminado = false;
  function terminar() {
    if (terminado) return;
    terminado = true;
    body.classList.remove('celebrating');
    canvas.style.transition = 'opacity .4s';
    canvas.style.opacity = '0';
    setTimeout(function () { canvas.remove(); }, 450);
  }
  // Never keep the feedback hidden, even if animation frames are paused (background tab).
  setTimeout(terminar, DURATION + 300);
  function frame(now) {
    if (terminado) return;
    var t = now - start;
    ctx.clearRect(0, 0, w, h);
    pieces.forEach(function (p) {
      p.x += p.vx + Math.sin((t / 180) + p.phase) * 0.6;
      p.y += p.vy;
      p.rot += p.vr;
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.strokeStyle = p.color;
      if (p.len) {
        ctx.lineWidth = p.size;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.bezierCurveTo(8, p.len / 3, -8, (2 * p.len) / 3, 0, p.len);
        ctx.stroke();
      } else {
        ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      }
      ctx.restore();
    });
    if (t < DURATION) requestAnimationFrame(frame);
    else terminar();
  }
  requestAnimationFrame(frame);
  window.addEventListener('resize', resize);
})();
