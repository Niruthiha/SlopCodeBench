"""Regression checks: python tests/run_tests.py (uses the venv interpreter)."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
S = os.path.join(HERE, 's.csv')
P = os.path.join(HERE, 'p.csv')
V = 'mtl_version 1.5\n'     # version header prepended to every DSL
with open(os.path.join(HERE, 'base_schema.mtl')) as f:
    BASE = f.read()

CASES = [
    # (dsl, expected_exit, expected_json_or_None, extra_args)
    ("aggregate count(*) as n, sum(price) as s, median(extra_n) as m, var(extra_n) as v",
     0, {"m": 5, "n": 5, "s": 19.73, "v": 2.0}, []),
    ("filter('pp' in item)\ngroup_by(flag)\naggregate count(*) as n, max(price) as mx",
     0, [{"flag": False, "mx": 1.5, "n": 1}, {"flag": True, "mx": 1.25, "n": 1}], []),
    ("window(1d)\naggregate count(*) as n", 0,
     [{"window_start": "2025-09-14T00:00:00Z", "window_end": "2025-09-15T00:00:00Z", "n": 4},
      {"window_start": "2025-09-15T00:00:00Z", "window_end": "2025-09-16T00:00:00Z", "n": 1}],
     ['--tz', 'America/New_York']),
    ("filter(price > 100)\naggregate count(*) as n, sum(price) as s", 0, {"n": 0, "s": None}, []),
    ("filter(\n  price > 1 # c\n  | item == 'banana'\n)\naggregate count(*) as n # t", 0, {"n": 5}, []),
    ("filter(!category == 'fruit')\naggregate count(*) as n", 0, {"n": 2}, []),
    ("apply(len(item), item)\ngroup_by(item)\naggregate count(*) as n, sum(price) as s", 0,
     [{"item": 4, "n": 1, "s": 3.49}, {"item": 5, "n": 3, "s": 15.74}, {"item": 6, "n": 1, "s": 0.5}], []),
    ("aggregate\n  count(*) as n\n  , sum(price) as s", 0, {"n": 5, "s": 19.73}, []),
    ("apply(round(price * quantity, 1), r)\ngroup_by(category)\naggregate sum(r) as t", 0,
     [{"category": "dairy", "t": 3.5}, {"category": "fruit", "t": 30.0}, {"category": "meat", "t": 26.0}], []),
    ("filter(price > 1)", 1, None, []),
    ("aggregate count(*) as n\naggregate count(*) as m", 1, None, []),
    ("group_by(item)\ngroup_by(unit)\naggregate count(*) as n", 1, None, []),
    ("window(1h)\nwindow(1d)\naggregate count(*) as n", 1, None, []),
    ("aggregate count(*) as n, sum(price) as n", 1, None, []),
    ("window(30s)\naggregate count(*) as n", 1, None, []),
    ("aggregate mean(price) as n", 1, None, []),
    ("aggregate count(*)", 1, None, []),
    ("filter(\"a\" in item)\naggregate count(*) as n", 1, None, []),
    ("filter(1 < 2 < 3)\naggregate count(*) as n", 1, None, []),
    ("filter(price > 1\naggregate count(*) as n", 1, None, []),
    ("filter(item > 3)\naggregate count(*) as n", 2, None, []),
    ("filter(item in 'apple')\naggregate count(*) as n", 2, None, []),
    ("filter('a' in 'apple')\naggregate count(*) as n", 2, None, []),
    ("aggregate sum(item) as n", 2, None, []),
    ("aggregate sum(*) as n", 2, None, []),
    ("apply(len(price), l)\naggregate count(*) as n", 2, None, []),
    ("apply(day(price), l)\naggregate count(*) as n", 2, None, []),
    ("filter(nope > 1)\naggregate count(*) as n", 2, None, []),
    ("filter(price)\naggregate count(*) as n", 2, None, []),
    ("filter(timestamp > '2025-01-01')\naggregate count(*) as n", 2, None, []),
    ("apply(round(price, 1.5), x)\naggregate count(*) as n", 2, None, []),
    ("apply(item + 1, x)\naggregate count(*) as n", 2, None, []),
    ("apply(price / 0, x)\naggregate sum(x) as n", 4, None, []),
    ("apply(price * 1e308 * 10, x)\naggregate sum(x) as n", 4, None, []),
    ("aggregate count(*) as n", 3, None, ['--tz', 'Mars/Base']),
]

# Part 2: schemas, params, calcs, lag/lead (run against p.csv, BaseSale prepended)
PIPE = 'pipeline X using S {\n'
CASES2 = [
    ("schema S extends BaseSale { promo_code: string\n rev: float = price * quantity }\n" + PIPE +
     "params {\n p: string = 'Q3-'\n k: int = 1\n}\n"
     "filter(promo_code starts_with param(\"p\"))\nwindow(1h)\ngroup_by(['location'])\n"
     "aggregate sum(rev) as total, count(*) as n\n"
     "calc prev = lag(total, param('k')) : float @stage(post_agg)\n"
     "calc d = total - coalesce(prev, 0.0) : float @stage(post_agg)\n}", 0,
     [{"window_start": "2025-09-14T08:00:00Z", "window_end": "2025-09-14T09:00:00Z", "location": "NYC",
       "n": 2, "total": 22.5, "d": 22.5, "prev": None},
      {"window_start": "2025-09-14T09:00:00Z", "window_end": "2025-09-14T10:00:00Z", "location": "NYC",
       "n": 1, "total": 3.49, "d": -19.009999999999998, "prev": 22.5},
      {"window_start": "2025-09-14T09:00:00Z", "window_end": "2025-09-14T10:00:00Z", "location": "SF",
       "n": 1, "total": 7.5, "d": 4.01, "prev": 3.49},
      {"window_start": "2025-09-14T10:00:00Z", "window_end": "2025-09-14T11:00:00Z", "location": "NYC",
       "n": 1, "total": 0.0, "d": -7.5, "prev": 7.5}], []),
    ("schema S extends BaseSale { }\n" + PIPE + "params { k: int }\nfilter(quantity > param('k'))\n"
     "aggregate count(*) as n\ncalc x = lead(n, 1) : int @stage(post_agg)\n}", 0,
     {"n": 3, "x": None}, ['--param', 'k=4']),
    ("schema S extends BaseSale { price: int }\n" + PIPE + "aggregate count(*) as n }", 2, None, []),
    ("schema A extends S { }\nschema S extends A { }\n" + PIPE + "aggregate count(*) as n }", 1, None, []),
    ("schema S extends BaseSale { r: float = price * z\n z: float = 1.0 }\n" + PIPE +
     "aggregate count(*) as n }", 1, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "params { k: int }\naggregate count(*) as n }", 1, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "params { k: int }\naggregate count(*) as n }", 2, None,
     ['--param', 'k=1.5']),
    ("schema S extends BaseSale { }\n" + PIPE + "calc x = n + 1 : int @stage(pre)\n"
     "aggregate count(*) as n }", 1, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "calc x = lag(price, 1) : float @stage(pre)\n"
     "aggregate count(*) as n }", 1, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "window(1h)\naggregate count(*) as n\n"
     "calc d = day(timestamp) : int @stage(post_agg) }", 2, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "calc x = price > 1 : float @stage(pre)\n"
     "aggregate count(*) as n }", 2, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "calc x = price / quantity : float @stage(pre)\n"
     "aggregate sum(x) as s }", 4, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "calc x = 1 : int @stage(pre)\n"
     "calc x = 2 : int @stage(pre)\naggregate count(*) as n }", 1, None, []),
    ("schema S extends BaseSale { }\n" + PIPE + "aggregate count(*) as n\n"
     "calc x = lag(n, 0) : int @stage(post_agg) }", 1, None, []),
    ("schema S extends BaseSale { foo: string }\n" + PIPE + "aggregate count(*) as n }", 3, None, []),
]


def run(dsl, args, csv=S):
    p = subprocess.run([PY, os.path.join(ROOT, 'mtl.py'), '--csv', csv, '--dsl', '-'] + args,
                       input=(V + dsl).encode(), capture_output=True)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


def main():
    bad = 0
    for dsl, code, exp, args in CASES:
        rc, out, err = run(dsl, args)
        ok = rc == code
        if ok and exp is not None:
            got = json.loads(out)
            ok = got == exp and json.dumps(got) == json.dumps(exp)
        if ok and code:
            ok = err.startswith('ERROR:') and err.count('\n') == 1 and out == ''
        if not ok:
            bad += 1
            print('FAIL', repr(dsl), rc, out, err)
    for dsl, code, exp, args in CASES2:
        rc, out, err = run(BASE + dsl, args, csv=P)
        ok = rc == code
        if ok and exp is not None:
            got = json.loads(out)
            ok = got == exp and json.dumps(got) == json.dumps(exp)
        if ok and code:
            ok = err.startswith('ERROR:') and err.count('\n') == 1 and out == ''
        if not ok:
            bad += 1
            print('FAIL', repr(dsl), rc, out, err)
    rc, out, err = run('aggregate count(*) as n', [], csv='/nonexistent.csv')
    if rc != 3:
        bad += 1
        print('FAIL missing csv', rc, err)
    total = len(CASES) + len(CASES2) + 1
    b3, t3 = part3()
    bad += b3
    total += t3
    b4, t4 = part4()
    bad += b4
    total += t4
    b5, t5 = part5()
    bad += b5
    total += t5
    print(f'{total - bad}/{total} passed')
    sys.exit(1 if bad else 0)


# Part 3: multiple inputs, formats, nulls and bad records (uses --input)
P3_DSL = BASE + """schema W extends BaseSale { revenue: float = price * quantity }
pipeline M using W {
  calc ok = price >= 0.0 : bool @stage(pre)
  filter(ok)
  window(1h)
  group_by(['location', 'category'])
  aggregate sum(revenue) as total_rev, count(*) as n, count(price) as np
}"""


def part3():
    import gzip, tempfile
    import pyarrow as pa, pyarrow.parquet as pq
    from datetime import datetime, timezone
    d = tempfile.mkdtemp()
    H = 'timestamp,location,item,price,quantity,unit,category\n'
    with open(os.path.join(d, 'a.csv'), 'w') as f:
        f.write(H + '2025-09-14T08:05:00Z,NYC,apple,1.25,10,kg,fruit\n'
                '2025-09-14T08:35:00Z,NYC,banana,NaN,20,kg,fruit\n'
                'bad-ts,SF,steak,12.99,2,lb,meat\n'
                '2025-09-14T09:10:00Z,SF,apple,abc,5,kg,fruit\n')
    with gzip.open(os.path.join(d, 'b.tsv.gz'), 'wt') as f:
        f.write(H.replace(',', '\t') + '2025-09-14T08:15:00Z\tNYC\tpear\t2.5\t\tkg\tfruit\n')
    os.makedirs(os.path.join(d, 'sub'))
    pq.write_table(pa.table({
        'timestamp': pa.array([datetime(2025, 9, 14, 8, 50, tzinfo=timezone.utc)] * 2, pa.timestamp('ms', tz='UTC')),
        'location': ['NYC', 'NYC'], 'item': ['kiwi', 'fig'], 'price': ['4.0', None],
        'quantity': pa.array([1, 2]), 'unit': ['kg', 'kg'], 'category': ['fruit', 'fruit']}),
        os.path.join(d, 'sub', 'p.parquet'))
    bad_out = os.path.join(d, 'bad.jsonl')
    expect = [{"window_start": "2025-09-14T08:00:00Z", "window_end": "2025-09-14T09:00:00Z",
               "location": "NYC", "category": "fruit", "n": 2, "np": 2, "total_rev": 12.5}]
    cases = [  # (args, code, expected_json, expected bad-record classes)
        (['--input', d, '--recursive', '--bad-records-out', bad_out], 0, expect,
         ['TIMESTAMP_PARSE_ERROR', 'PARSE_TYPE_MISMATCH', 'PARQUET_TYPE_MISMATCH']),
        (['--input', os.path.join(d, 'sub'), '--input', os.path.join(d, '*.*')], 0, expect, None),
        (['--input', d, '--recursive', '--strict'], 2, None, None),
        (['--input', os.path.join(d, 'none', '*.csv')], 3, None, None),
    ]
    bad = 0
    for args, code, exp, classes in cases:
        if os.path.exists(bad_out):
            os.remove(bad_out)
        p = subprocess.run([PY, os.path.join(ROOT, 'mtl.py'), '--dsl', '-'] + args,
                           input=(V + P3_DSL).encode(), capture_output=True)
        ok = p.returncode == code
        if ok and exp is not None:
            ok = json.loads(p.stdout) == exp
        if ok and classes is not None:
            with open(bad_out) as f:
                recs = [json.loads(line) for line in f]
            ok = [r['error'] for r in recs] == classes and recs[0]['line'] == 4
        if not ok:
            bad += 1
            print('FAIL part3', args, p.returncode, p.stdout.decode(), p.stderr.decode())
    return bad, len(cases)


# Part 4: ingest config with named sources, alias pre-stages and joins
P4_CFG = """sources:
  - name: web
    inputs: ["web/**/*.parquet"]
    recursive: true
    schema: WebSale
    precedence: 10
    nulls: ["", "NULL"]
    mapping:
      rename: { qty: quantity }
      cast: { price: float }
      defaults: { unit: "ea" }
      drop: ["debug_col"]
    required: ["timestamp", "price", "quantity"]
  - name: pos
    inputs: ["pos/*.csv.gz"]
    schema: BaseSale
    precedence: 20
"""
P4_DSL = BASE + """schema WebSale extends BaseSale { }
pipeline CrossStream using WebSale {
  sources { web as W, pos as P }
  with W { calc w_is_promo = starts_with(item, 'PROMO') : bool @stage(pre)
           filter(w_is_promo) }
  with P { filter(price > 0) }
  join W with P
    on (W.item == P.item & W.location == P.location)
    within 30m
    type inner
    project {
      W.timestamp as timestamp,
      W.location  as location,
      W.item      as item,
      P.quantity  as pos_qty,
      W.price     as web_price
    }
  window(1h)
  group_by(['location','item'])
  aggregate sum(web_price) as web_rev,
            sum(pos_qty)   as qty
}"""


def part4():
    import gzip, tempfile
    import pyarrow as pa, pyarrow.parquet as pq
    from datetime import datetime, timezone
    U = timezone.utc
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, 'web', '2025'))
    os.makedirs(os.path.join(d, 'pos'))
    ts = [datetime(2025, 9, 14, 8, 5, tzinfo=U), datetime(2025, 9, 14, 8, 20, tzinfo=U),
          datetime(2025, 9, 14, 9, 10, tzinfo=U), datetime(2025, 9, 14, 9, 40, tzinfo=U)]
    pq.write_table(pa.table({
        'timestamp': pa.array(ts, pa.timestamp('ms', tz='UTC')),
        'location': ['NYC', 'NYC', 'SF', 'SF'], 'item': ['PROMO-apple', 'banana', 'PROMO-steak', 'PROMO-kiwi'],
        'price': ['1.25', '0.5', '12.99', '2.0'], 'qty': [10.0, 20.0, 2.0, 3.0],
        'unit': ['kg', None, 'lb', 'kg'], 'category': ['fruit', 'fruit', 'meat', 'fruit'],
        'debug_col': ['x', 'y', 'z', 'w']}), os.path.join(d, 'web', '2025', 'a.parquet'))
    with gzip.open(os.path.join(d, 'pos', 'p1.csv.gz'), 'wt') as f:
        f.write('timestamp,location,item,price,quantity,unit,category\n'
                '2025-09-14T08:10:00Z,NYC,PROMO-apple,1.20,4,kg,fruit\n'
                '2025-09-14T08:30:00Z,NYC,PROMO-apple,1.20,6,kg,fruit\n'
                '2025-09-14T09:15:00Z,SF,PROMO-steak,13.5,1,lb,meat\n'
                '2025-09-14T09:20:00Z,SF,PROMO-steak,0,1,lb,meat\n'
                '2025-09-14T12:00:00Z,LA,milk,3.0,1,l,dairy\n')

    def cfg(text, name='ingest.yaml'):
        path = os.path.join(d, name)
        with open(path, 'w') as f:
            f.write(text)
        return path

    good = cfg(P4_CFG)
    inner = [{"window_start": "2025-09-14T08:00:00Z", "window_end": "2025-09-14T09:00:00Z",
              "location": "NYC", "item": "PROMO-apple", "qty": 10.0, "web_rev": 2.5},
             {"window_start": "2025-09-14T09:00:00Z", "window_end": "2025-09-14T10:00:00Z",
              "location": "SF", "item": "PROMO-steak", "qty": 1.0, "web_rev": 12.99}]
    full = inner[:1] + [{"window_start": "2025-09-14T09:00:00Z", "window_end": "2025-09-14T10:00:00Z",
                         "location": "SF", "item": "PROMO-kiwi", "qty": None, "web_rev": 2.0}] + inner[1:]

    def sub(a, b):
        assert a in P4_DSL, a
        return P4_DSL.replace(a, b)

    proj = "W.timestamp as timestamp,"
    cases = [  # (dsl, config, code, expected)
        (P4_DSL, good, 0, inner),
        (sub('type inner', 'type full').replace('within 30m', ''), good, 0, full),
        (P4_DSL, cfg(P4_CFG.replace('precedence: 20', 'precedence: 10').replace('pos/*.csv.gz', '**/*.*'),
                     'tie.yaml'), 5, None),
        (P4_DSL, cfg(P4_CFG.replace('schema: BaseSale', 'schema: Nope'), 'schema.yaml'), 5, None),
        (P4_DSL, cfg(P4_CFG.replace('price: float', 'price: decimal'), 'cast.yaml'), 5, None),
        (P4_DSL, cfg('sources: [', 'broken.yaml'), 5, None),
        (sub('pos as P', 'pos2 as P'), good, 5, None),
        (P4_DSL, os.path.join(d, 'missing.yaml'), 3, None),
        (sub('W.item == P.item', 'W.item == P.price'), good, 2, None),
        (sub('W.item == P.item', 'W.item == cast(P.price as string)'), good, 0, []),
        (sub(proj, ''), good, 2, None),
        (sub('W.price     as web_price', 'W.price as pos_qty'), good, 1, None),
        (sub('W.item      as item', 'item as item'), good, 1, None),
        (sub('with P { filter(price > 0) }', 'with P { calc z = 1 : int @stage(post_agg) }'), good, 2, None),
        (sub('with P { filter(price > 0) }', 'with P { window(1h) }'), good, 1, None),
        (sub('    project {', '    zz {'), good, 1, None),
    ]
    bad = 0
    for dsl, config, code, exp in cases:
        p = subprocess.run([PY, os.path.join(ROOT, 'mtl.py'), '--dsl', '-', '--ingest-config', config],
                           input=(V + dsl).encode(), capture_output=True, cwd=d)
        ok = p.returncode == code
        if ok and exp is not None:
            ok = json.loads(p.stdout) == exp
        if ok and code:
            err = p.stderr.decode()
            ok = err.startswith('ERROR:') and err.count('\n') == 1 and not p.stdout
        if not ok:
            bad += 1
            print('FAIL part4', code, p.returncode, p.stdout.decode(), p.stderr.decode())
    # sources {} without --ingest-config
    p = subprocess.run([PY, os.path.join(ROOT, 'mtl.py'), '--dsl', '-'], input=(V + P4_DSL).encode(),
                       capture_output=True, cwd=d)
    if p.returncode != 5:
        bad += 1
        print('FAIL part4 no config', p.returncode, p.stderr.decode())
    return bad, len(cases) + 1




# Part 5: version header gating, resumable state and run metadata
P5_DSL = """# kpis
mtl_version 1.5
""" + BASE + """pipeline KPIs using BaseSale {
  window(1d)
  group_by(location)
  aggregate count(*) as n, median(price) as md, sum(quantity) as q
  calc d = n - coalesce(lag(n, 1), 0) : int @stage(post_agg)
}"""
META_KEYS = ['run', 'versions', 'inputs', 'pipeline', 'udfs', 'quality', 'output']


def part5():
    import shutil, tempfile
    d = tempfile.mkdtemp()
    inp = os.path.join(d, 'in')
    os.makedirs(inp)
    shutil.copy(S, os.path.join(inp, 'a.csv'))
    shutil.copy(P, os.path.join(inp, 'b.csv'))
    dsl = os.path.join(d, 'k.mtl')
    with open(dsl, 'w') as f:
        f.write(P5_DSL)
    state = os.path.join(d, 'state')
    udf = os.path.join(d, 'u.py')
    with open(udf, 'w') as f:
        f.write('@udf(args=["float", "float"], returns="float")\ndef score(a, b):\n    return a * b\n')

    def mtl(args, dsl_text=None):
        p = subprocess.run([PY, os.path.join(ROOT, 'mtl.py')] + args, capture_output=True,
                           input=None if dsl_text is None else dsl_text.encode())
        return p.returncode, p.stdout.decode(), p.stderr.decode()

    def read(name):
        with open(os.path.join(d, name)) as f:
            return f.read()

    def strip_run(m):
        m = json.loads(m)
        for k in ('run_id', 'started_at', 'completed_at', 'duration_ms', 'resume'):
            m['run'].pop(k)
        return m

    base = ['--dsl', dsl, '--input', inp, '--state-dir', state]
    out = lambda n: ['--out', os.path.join(d, n), '--meta-out', os.path.join(d, n + '.meta')]
    checks = []
    rc, _, _ = mtl(base + out('o1'))
    checks.append(('fresh run', rc == 0))
    st = json.loads(read('state/KPIs.state.json'))
    paths = [f['path'] for f in st['last_run']['files']]
    checks.append(('state files', paths == sorted(paths) and len(paths) == 2 and
                   all(f['status'] == 'done' and f['fingerprint']['scheme'] == 'mtime_size'
                       for f in st['last_run']['files'])))
    meta = json.loads(read('o1.meta'))
    checks.append(('meta keys', list(meta) == META_KEYS and meta['run']['resume'] is False and
                   meta['pipeline']['window'] == {'duration': '1d', 'aligned_to_epoch': True} and
                   meta['output']['row_count'] == len(json.loads(read('o1')))))
    rc, _, _ = mtl(base + out('o2') + ['--resume'])
    checks.append(('resume identical', rc == 0 and read('o1') == read('o2') and
                   strip_run(read('o1.meta')) == strip_run(read('o2.meta'))))
    # same size, mtime restored: the file is skipped (replayed from its snapshot)
    a = os.path.join(inp, 'a.csv')
    sa = os.stat(a)
    with open(a) as f:
        text = f.read()
    with open(a, 'w') as f:
        f.write(text.replace('NYC', 'LAX'))
    os.utime(a, ns=(sa.st_atime_ns, sa.st_mtime_ns))
    rc, _, _ = mtl(base + out('o3') + ['--resume'])
    checks.append(('unchanged fingerprint skipped', rc == 0 and read('o3') == read('o1')))
    rc, _, _ = mtl(base + out('o4') + ['--resume', '--fingerprint', 'xxhash64'])
    checks.append(('changed hash reprocessed', rc == 0 and 'LAX' in read('o4')))
    rc, _, err = mtl(['--dsl', dsl, '--input', inp, '--out', os.path.join(d, 'x'), '--resume'])
    checks.append(('resume without state dir', rc == 6 and err.count('\n') == 1))
    rc, _, _ = mtl(base[:-1] + [os.path.join(d, 'none'), '--out', os.path.join(d, 'x'), '--resume'])
    checks.append(('missing state', rc == 6))
    rc, _, err = mtl(['--dsl', '-', '--input', inp, '--state-dir', state, '--resume'],
                     P5_DSL.replace('1d', '1h'))
    checks.append(('dsl changed', rc == 6 and 'breaking' in err))
    for text, code, what in [
            ('aggregate count(*) as n', 6, 'missing header'),
            ('mtl_version 2.0\naggregate count(*) as n', 6, 'major'),
            ('mtl_version 1.x\naggregate count(*) as n', 1, 'malformed header'),
            ('mtl_version 1.2\naggregate count(price) as n', 1, 'count(col) gate'),
            ('mtl_version 1.3\naggregate count(price) as n', 0, 'count(col) ok'),
            ('mtl_version 1.1\naggregate count(*) as n\ncalc x = n : int @stage(post_agg)', 1, 'calc gate'),
            ('mtl_version 1.7\naggregate count(*) as n', 0, 'newer minor'),
            ('mtl_version 1.3\napply(score(price, quantity), s)\naggregate sum(s) as n', 1, 'udf gate'),
            ('mtl_version 1.4\napply(score(price, quantity), s)\naggregate sum(s) as n', 0, 'udf')]:
        rc, o, err = mtl(['--dsl', '-', '--csv', S, '--udf', udf], text)
        checks.append((what, rc == code and (code == 0 or err.count('\n') == 1)))
    rc, o, err = mtl(['--dsl', '-', '--csv', S, '--meta-out', os.path.join(d, 'm')],
                     'mtl_version 1.4\naggregate count(*) as n')
    checks.append(('older minor warns', rc == 0 and err.startswith('WARNING') and err.count('\n') == 1))
    bad = 0
    for what, ok in checks:
        if not ok:
            bad += 1
            print('FAIL part5', what)
    return bad, len(checks)


main()
