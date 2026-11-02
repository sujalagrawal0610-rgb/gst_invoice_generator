"""Run:  python tests/test_app.py   (uses a throw-away database, your real data is never touched)"""
import os, sys, re, shutil, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp()
os.environ['DB_FILE'] = os.path.join(TMP, 't.db')
os.environ['ADMIN_EMAILS'] = 'boss@gmail.com'
shutil.copy(os.path.join(HERE, 'legacy_sample.db'), os.environ['DB_FILE'])
import config, app as A, mailer
import otp as O, db as D, services as S

codes = {}
def fake_send(to, code, purpose='login'):
    codes[(to, purpose)] = code; return True, ''
mailer.send_otp_email = fake_send
config.MAIL_USERNAME, config.MAIL_PASSWORD = 'x@gmail.com', 'pw'
O.config.OTP_RESEND_COOLDOWN_SEC = 0

def tok(client):
    with client.session_transaction() as s:
        s.setdefault('_csrf', 'tok123'); return s['_csrf']
def post(client, url, data=None, **kw):
    d = dict(data or {}); d['_csrf'] = tok(client); return client.post(url, data=d, **kw)
def ok(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond: sys.exit(1)
def login(email, admin=False):
    c = A.app.test_client()
    post(c, '/login/request', {'email': email, **({'admin': '1'} if admin else {})})
    r = post(c, '/verify', {'otp': codes[(email, 'admin' if admin else 'login')]})
    return c, r

c = A.app.test_client()
# ---- migration of the old database
cn = D.connect()
ok(cn.execute('select count(*) c from invoices').fetchone()['c'] == 6, 'legacy invoices migrated')
cn.close()

# ---- security basics
for u in ['/dashboard', '/invoices', '/invoices/new', '/admin', '/invoices/1/pdf']:
    ok(c.get(u).status_code == 302, f'unauth {u} -> redirect')
ok(c.post('/login/request', data={'email': 'a@b.com'}).status_code == 400, 'POST without CSRF rejected')
ok(b'Get Secure OTP' in c.get('/').data and b'Get Secure OTP' in c.get('/admin-login').data, 'login pages render')

# ---- normal login
post(c, '/login/request', {'email': 'Sujal@Gmail.com'})
code = codes[('sujal@gmail.com', 'login')]; ok(len(code) == 6, '6-digit OTP e-mailed')
r = post(c, '/verify', {'otp': '000000' if code != '000000' else '111111'}, follow_redirects=True); ok(b'Incorrect code' in r.data, 'wrong OTP rejected')
r = post(c, '/verify', {'otp': code}); ok(r.location.endswith('/dashboard'), 'correct OTP logs in')
r = c.get('/dashboard'); ok(r.status_code == 200 and b'All Invoices' in r.data, 'dashboard renders with "All Invoices"')
for gone in [b'Clients', b'Settings', b'Send Invoice To', b'Unpaid', b'Payment Status', b'Manage clients']:
    ok(gone not in r.data, f'dashboard has no {gone.decode()}')
ok(c.get('/clients').status_code == 404 and c.get('/settings').status_code == 404, 'clients/settings pages removed')

# ---- OTP hardening
c2, _ = login('reuse@gmail.com'); cd = codes[('reuse@gmail.com', 'login')]
c3 = A.app.test_client(); tok(c3)
with c3.session_transaction() as s: s['pending'] = {'email': 'reuse@gmail.com', 'purpose': 'login'}
ok(b'No active code' in post(c3, '/verify', {'otp': cd}, follow_redirects=True).data, 'OTP cannot be reused')
c4 = A.app.test_client(); post(c4, '/login/request', {'email': 'bf@gmail.com'}); real = codes[('bf@gmail.com', 'login')]
for i in range(5): post(c4, '/verify', {'otp': '999999' if real != '999999' else '888888'})
r = post(c4, '/verify', {'otp': real}, follow_redirects=True); ok(b'Too many' in r.data or b'No active' in r.data, 'brute force locks OTP')

# ---- ADMIN: OTP is ALWAYS sent, admin check happens after verification
ca = A.app.test_client()
r = post(ca, '/login/request', {'email': 'nobody@gmail.com', 'admin': '1'})
ok(('nobody@gmail.com', 'admin') in codes, 'non-admin email STILL receives the OTP')
r = post(ca, '/verify', {'otp': codes[('nobody@gmail.com', 'admin')]}, follow_redirects=True)
ok(b'not an admin' in r.data, 'after OTP: simple "not an admin" message')
ok(ca.get('/admin').status_code == 302 and ca.get('/dashboard').status_code == 302, 'non-admin got NO session at all')
ca, r = login('boss@gmail.com', admin=True); ok(r.location.endswith('/admin'), 'admin e-mail -> admin panel')
r = ca.get('/admin'); ok(r.status_code == 200 and b'Admin control panel' in r.data, 'admin page renders')
ok(b'Awaiting' not in r.data and b'Paid' not in r.data, 'admin page has no payment status')
ok(ca.get('/admin/export.csv').status_code == 200, 'csv export')
ok(c.get('/admin').status_code == 403, 'normal user -> 403 on admin')

# ---- invoices
def inv(client=c, **o):
    d = {'buyer_name': 'John', 'buyer_address': 'Indore MP', 'item_name': ['Laptop', 'Open Notebook'],
         'item_qty': ['2', '3'], 'item_rate': ['50000', '40'], 'item_disc': ['10', '0']}
    d.update(o); return post(client, '/invoices/new', d)
r = inv(); ok(r.status_code == 302, 'valid invoice created'); iid = int(r.location.rsplit('/', 1)[1])
cn = D.connect(); it = cn.execute('select * from invoice_items where invoice_id=?', (iid,)).fetchall(); row = cn.execute('select * from invoices where id=?', (iid,)).fetchone()
ok([x['category'] for x in it] == ['Electronics', 'Stationery'], 'categories auto (open != pen)')
ok(abs(row['total'] - (106200 + 134.4)) < 0.001, f"totals correct {row['total']}")
# nobody can force a GST rate
r = inv(item_gst=['0', '0'], item_name=['Laptop', 'Laptop'], item_rate=['100', '100'], item_qty=['1', '1'], item_disc=['0', '0'])
iid2 = int(r.location.rsplit('/', 1)[1])
ok({x['gst_rate'] for x in cn.execute('select * from invoice_items where invoice_id=?', (iid2,))} == {18.0}, 'manual GST is ignored - always auto (18%)')
cn.close()
for bad in [dict(item_rate=['nan', '1']), dict(item_rate=['inf', '1']), dict(item_rate=['-5', '1']), dict(item_rate=['', '1']),
            dict(item_qty=['0', '1']), dict(item_disc=['150', '0']), dict(item_rate=['1e999999', '1']), dict(buyer_name=''),
            dict(buyer_address=''), dict(item_name=['', ''], item_rate=['', '']), dict(item_rate=['abc', '1'])]:
    r = inv(**bad); ok(r.status_code == 200 and b'toast error' in r.data, f'bad input handled: {list(bad)[0]}={list(bad.values())[0]}')
ok(post(c, '/invoices/new', {}).status_code == 200, 'empty POST handled')
ok(S.detect_category('activity')['category'] == 'Other' and S.detect_category('TV')['category'] == 'Electronics'
   and S.detect_category('pen drive')['category'] == 'Electronics' and S.detect_category('Rolex Watch')['category'] == 'Luxury', 'category detection')

# ---- PDF in the ORIGINAL "SME TAX INVOICE" format
r = c.get(f'/invoices/{iid}/pdf?dl=1'); ok(r.status_code == 200 and r.data[:4] == b'%PDF', 'PDF generated')
p = os.path.join(TMP, 'a.pdf'); open(p, 'wb').write(r.data)
txt = subprocess.run(['pdftotext', '-layout', p, '-'], capture_output=True, text=True).stdout
for needle in ['SME TAX INVOICE', 'GST Compliant Billing System', 'ORIGINAL FOR RECIPIENT', 'Billed To:', 'Name: John', 'Item Description',
               'Grand Total:', 'computer-generated GST invoice']:
    ok(needle in txt, f'PDF contains "{needle}"')
ok('UNPAID' not in txt.upper() and 'Status' not in txt, 'PDF has no payment status')
big = inv(buyer_name='ज़ेड 😀 Üñí ' * 5, buyer_address='long address line ' * 80, item_name=['Item %d' % i for i in range(40)],
          item_qty=['1'] * 40, item_rate=['10'] * 40, item_disc=['0'] * 40)
bid = int(big.location.rsplit('/', 1)[1]); r = c.get(f'/invoices/{bid}/pdf'); ok(r.status_code == 200 and r.data[:4] == b'%PDF', 'PDF: unicode + huge address + 40 items OK')

# ---- invoice pages
r = c.get(f'/invoices/{iid}'); ok(b'Payment Status' not in r.data and b'Paid' not in r.data and b'Download PDF' in r.data, 'invoice page: no status, has PDF button')
ok(b'INV-' in c.get('/invoices?q=laptop').data, 'search by item'); ok(c.get('/invoices?page=abc&q=%25').status_code == 200, 'weird params ok')
ok(b'Laptop' in c.get(f'/invoices/new?from={iid}').data, 'duplicate prefill')
ok(b'item_gst' not in c.get('/invoices/new').data, 'no GST input exists on the form')

# ---- ownership
c5, _ = login('other@gmail.com')
ok(c5.get(f'/invoices/{iid}').status_code == 404 and c5.get(f'/invoices/{iid}/pdf').status_code == 404, 'other user cannot read')
ok(post(c5, f'/invoices/{iid}/delete').status_code == 404, 'other user cannot delete')
ok(c5.get('/admin').status_code == 403, 'normal user -> 403 admin')
ok(ca.get(f'/invoices/{iid}/pdf').status_code == 200, 'admin can open any invoice')
r = post(c, '/logout'); ok(c.get('/dashboard').status_code == 302, 'logout')
ok(b'404' in c.get('/nope').data, '404 page')
print('\nALL PASSED')
