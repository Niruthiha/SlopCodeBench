"""Regression checks: python tests/run_tests.py (uses the venv interpreter)."""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
S = os.path.join(HERE, 's.csv')

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
    rc, out, err = run('aggregate count(*) as n', [], csv='/nonexistent.csv')
    if rc != 3:
        bad += 1
        print('FAIL missing csv', rc, err)
    print(f'{len(CASES) + 1 - bad}/{len(CASES) + 1} passed')
    sys.exit(1 if bad else 0)


main()
