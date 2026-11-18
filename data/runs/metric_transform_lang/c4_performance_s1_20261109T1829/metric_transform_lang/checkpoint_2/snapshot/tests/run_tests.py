"""Regression checks: python tests/run_tests.py (uses the venv interpreter)."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
S = os.path.join(HERE, 's.csv')
P = os.path.join(HERE, 'p.csv')
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
                       input=dsl.encode(), capture_output=True)
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
    print(f'{total - bad}/{total} passed')
    sys.exit(1 if bad else 0)


main()
