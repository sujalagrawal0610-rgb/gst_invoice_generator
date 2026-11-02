(function () {
  var tbody = document.querySelector('#items tbody'), tpl = document.getElementById('rowTpl');
  var money = function (v) { return '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  var r2 = function (v) { return Math.round((v + Number.EPSILON) * 100) / 100; };
  var num = function (s) { var v = parseFloat(String(s).replace(/,/g, '')); return isFinite(v) && v >= 0 ? v : 0; };

  // GST is always AUTO: the server detects it from the item name. Here we only preview it.
  function calc() {
    var sub = 0, disc = 0, gst = 0, tot = 0;
    tbody.querySelectorAll('tr').forEach(function (tr) {
      var q = num(tr.querySelector('[name=item_qty]').value), rt = num(tr.querySelector('[name=item_rate]').value);
      var dp = Math.min(100, num(tr.querySelector('[name=item_disc]').value)), gp = +tr.dataset.auto || 0;
      var gross = r2(q * rt), d = r2(gross * dp / 100), g = r2((gross - d) * gp / 100), line = r2(gross - d + g);
      tr.querySelector('.lt').textContent = money(line);
      sub += gross; disc += d; gst += g; tot += line;
    });
    document.getElementById('tSub').textContent = money(r2(sub));
    document.getElementById('tDisc').textContent = money(r2(disc));
    document.getElementById('tGst').textContent = money(r2(gst));
    document.getElementById('tTot').textContent = money(r2(tot));
  }

  var timers = new WeakMap();
  function detect(tr) {
    var name = tr.querySelector('[name=item_name]').value.trim(), hint = tr.querySelector('.hint'), g = tr.querySelector('.gst');
    if (!name) { hint.textContent = ''; g.textContent = '—'; tr.dataset.auto = ''; calc(); return; }
    clearTimeout(timers.get(tr));
    timers.set(tr, setTimeout(function () {
      fetch('/api/detect?name=' + encodeURIComponent(name), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          if (!j) return;
          tr.dataset.auto = j.gst_rate;
          hint.textContent = j.category;
          g.textContent = j.gst_rate + '%';
          calc();
        }).catch(function () { });
    }, 250));
  }

  function addRow(v) {
    var tr = tpl.content.firstElementChild.cloneNode(true);
    v = v || {};
    if (v.name) tr.querySelector('[name=item_name]').value = v.name;
    if (v.qty !== undefined && v.qty !== '') tr.querySelector('[name=item_qty]').value = v.qty;
    if (v.rate !== undefined && v.rate !== '') tr.querySelector('[name=item_rate]').value = v.rate;
    if (v.disc !== undefined && v.disc !== '') tr.querySelector('[name=item_disc]').value = v.disc;
    tbody.appendChild(tr);
    if (v.name) detect(tr);
    return tr;
  }

  tbody.addEventListener('input', function (e) {
    var tr = e.target.closest('tr');
    if (e.target.name === 'item_name') detect(tr); else calc();
  });
  tbody.addEventListener('click', function (e) {
    if (e.target.closest('.rm') && tbody.children.length > 1) { e.target.closest('tr').remove(); calc(); }
  });
  document.getElementById('addRow').addEventListener('click', function () {
    if (tbody.children.length >= 50) return alert('Maximum 50 items per invoice.');
    addRow().querySelector('input').focus();
  });

  document.getElementById('invForm').addEventListener('submit', function (e) {
    var ok = false;
    tbody.querySelectorAll('tr').forEach(function (tr) {
      if (tr.querySelector('[name=item_name]').value.trim() && tr.querySelector('[name=item_rate]').value.trim()) ok = true;
    });
    var msg = '';
    if (!document.getElementById('bName').value.trim()) msg = 'Please enter the buyer name.';
    else if (!document.getElementById('bAddr').value.trim()) msg = 'Please enter the buyer address.';
    else if (!ok) msg = 'Add at least one item with a name and rate.';
    if (msg) { e.preventDefault(); alert(msg); }
  });

  var pre = []; try { pre = JSON.parse(document.getElementById('prefill').textContent) || []; } catch (e) { }
  if (pre.length) pre.forEach(addRow); else addRow();
  calc();
})();
