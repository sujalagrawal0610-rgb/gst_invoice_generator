(function () {
  // toasts auto-hide
  document.querySelectorAll('.toast').forEach(function (t) {
    setTimeout(function () { t.style.transition = 'opacity .4s'; t.style.opacity = 0; setTimeout(function () { t.remove(); }, 450); }, 6500);
    t.addEventListener('click', function () { t.remove(); });
  });

  // confirm before destructive forms
  document.addEventListener('submit', function (e) {
    var m = e.target.getAttribute && e.target.getAttribute('data-confirm');
    if (m && !window.confirm(m)) e.preventDefault();
  });

  // double-submit protection
  document.querySelectorAll('form').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      var b = f.querySelector('button[type=submit],button:not([type])');
      if (f.dataset.sent) { e.preventDefault(); return; }
      f.dataset.sent = '1';
      setTimeout(function () { delete f.dataset.sent; }, 4000);
    });
  });

  // OTP input: digits only + resend countdown
  var otp = document.getElementById('otp');
  if (otp) otp.addEventListener('input', function () { otp.value = otp.value.replace(/\D/g, '').slice(0, 6); });
  var rs = document.getElementById('resend');
  if (rs) {
    var n = parseInt(rs.dataset.wait || '30', 10), label = rs.textContent;
    rs.disabled = true;
    var iv = setInterval(function () {
      n--; if (n <= 0) { clearInterval(iv); rs.disabled = false; rs.textContent = label; } else rs.textContent = label + ' (' + n + 's)';
    }, 1000);
    rs.textContent = label + ' (' + n + 's)';
  }

  // ---------- area/line chart ----------
  function short(v) {
    if (v >= 1e7) return '₹' + (v / 1e7).toFixed(1).replace(/\.0$/, '') + 'Cr';
    if (v >= 1e5) return '₹' + (v / 1e5).toFixed(1).replace(/\.0$/, '') + 'L';
    if (v >= 1e3) return '₹' + (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
    return '₹' + Math.round(v);
  }
  function inr(v) { return '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function niceMax(v) {
    if (v <= 0) return 1000;
    var p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
  }
  function draw(el) {
    var data; try { data = JSON.parse(el.dataset.series); } catch (e) { return; }
    var W = 860, H = 300, L = 62, R = 18, T = 20, B = 36, ns = 'http://www.w3.org/2000/svg';
    var max = niceMax(Math.max.apply(null, data.map(function (d) { return d.value; }))), ticks = 4;
    var x = function (i) { return L + (W - L - R) * (data.length === 1 ? .5 : i / (data.length - 1)); };
    var y = function (v) { return T + (H - T - B) * (1 - v / max); };
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Invoiced per month"><defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6366f1" stop-opacity=".38"/><stop offset="1" stop-color="#6366f1" stop-opacity="0"/></linearGradient></defs>';
    for (var t = 0; t <= ticks; t++) {
      var v = max * t / ticks, yy = y(v);
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" stroke="#334155"/><text x="' + (L - 10) + '" y="' + (yy + 4) + '" text-anchor="end" fill="#94a3b8" font-size="12">' + short(v) + '</text>';
    }
    var pts = data.map(function (d, i) { return [x(i), y(d.value)]; });
    var line = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
    s += '<path d="' + line + ' L' + pts[pts.length - 1][0] + ' ' + y(0) + ' L' + pts[0][0] + ' ' + y(0) + ' Z" fill="url(#ag)"/>';
    s += '<path d="' + line + '" fill="none" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"/>';
    data.forEach(function (d, i) {
      s += '<text x="' + x(i) + '" y="' + (H - 10) + '" text-anchor="middle" fill="#94a3b8" font-size="12">' + d.label + '</text>';
      s += '<circle class="pt" data-i="' + i + '" cx="' + pts[i][0] + '" cy="' + pts[i][1] + '" r="5.5" fill="#fff" stroke="#1d2939" stroke-width="2.5"/>';
      s += '<rect data-i="' + i + '" class="hit" x="' + (x(i) - 24) + '" y="' + T + '" width="48" height="' + (H - T - B) + '" fill="transparent"/>';
    });
    el.innerHTML = s + '</svg><div class="tip"></div>';
    var tip = el.querySelector('.tip'), svg = el.querySelector('svg');
    el.querySelectorAll('.hit').forEach(function (h) {
      h.addEventListener('mouseenter', function () {
        var i = +h.dataset.i, d = data[i], r = svg.getBoundingClientRect(), k = r.width / W;
        tip.textContent = d.full + ' — ' + inr(d.value) + (d.count ? ' (' + d.count + ')' : '');
        tip.style.left = (pts[i][0] * k) + 'px'; tip.style.top = (pts[i][1] * k) + 'px'; tip.style.opacity = 1;
        el.querySelectorAll('.pt').forEach(function (c) { c.setAttribute('r', c.dataset.i == i ? 8 : 5.5); });
      });
      h.addEventListener('mouseleave', function () { tip.style.opacity = 0; el.querySelectorAll('.pt').forEach(function (c) { c.setAttribute('r', 5.5); }); });
    });
  }
  document.querySelectorAll('.chart').forEach(draw);
})();
