/* Tiny step/tab wizard used by Register and Release Music. Pages may define window.WZ = {validate(i,pane), onShow(i,pane)} first. */
(function () {
  document.querySelectorAll('[data-wiz]').forEach(function (root) {
    var form = root.closest('form') || root;
    var tabs = [].slice.call(root.querySelectorAll('.wz-tab'));
    var panes = [].slice.call(root.querySelectorAll('.wz-pane'));
    var prev = root.querySelector('.wz-prev'), next = root.querySelector('.wz-next'), sub = root.querySelector('.wz-sub');
    var hooks = window.WZ || {}, cur = 0, max = 0, last = panes.length - 1;

    function inHidden(el) { return !!el.closest('[hidden]'); }
    function check(i) {
      var els = [].slice.call(panes[i].querySelectorAll('input,select,textarea')).filter(function (e) {
        return e.type !== 'button' && !e.disabled && !inHidden(e);
      });
      for (var k = 0; k < els.length; k++) {
        if (!els[k].checkValidity()) { els[k].reportValidity(); return false; }
      }
      return hooks.validate ? hooks.validate(i, panes[i]) !== false : true;
    }
    function show(i) {
      cur = i; max = Math.max(max, i);
      panes.forEach(function (p, k) { p.hidden = k !== i; });
      tabs.forEach(function (t, k) { t.classList.toggle('on', k === i); t.classList.toggle('done', k < i || k < max && k !== i); });
      if (prev) prev.hidden = i === 0;
      if (next) next.hidden = i === last;
      if (sub) sub.hidden = i !== last;
      if (hooks.onShow) hooks.onShow(i, panes[i]);
      var t = tabs[i]; if (t && t.scrollIntoView) { try { t.scrollIntoView({ block: 'nearest', inline: 'center' }); } catch (e) {} }
    }
    function goto(j) {
      if (j <= cur) { show(j); return; }
      for (var k = cur; k < j; k++) { show(k); if (!check(k)) return; }
      show(j);
    }
    tabs.forEach(function (t, k) { t.addEventListener('click', function () { goto(k); }); });
    if (prev) prev.addEventListener('click', function () { show(cur - 1); });
    if (next) next.addEventListener('click', function () { if (check(cur)) show(cur + 1); });
    form.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'BUTTON') {
        e.preventDefault(); if (cur < last && check(cur)) show(cur + 1);
      }
    });
    form.addEventListener('submit', function (e) {
      for (var k = 0; k <= last; k++) { show(k); if (!check(k)) { e.preventDefault(); return; } }
      show(last);
      var b = sub && sub.querySelector('button'); if (b) { setTimeout(function () { b.disabled = true; b.textContent = 'Submitting…'; }, 0); }
    });
    show(parseInt(root.getAttribute('data-start') || '0', 10) || 0);
  });
})();
