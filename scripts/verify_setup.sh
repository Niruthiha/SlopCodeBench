#!/usr/bin/env bash
# Pre-run verifier for the Parnas pilot. Run AFTER building, BEFORE any cell. Exit 1 on any FAIL.
# Static checks need no Docker; dynamic checks (D*) need Docker Desktop + built images.
HERE=$(realpath "$(dirname "$0")"); H="$HERE/slop-code-bench"; P="$HERE/scb-problems"; FAILED=0
PROB=${PROB:-file_backup}
ok(){ printf '  PASS  %s\n' "$1"; }; bad(){ printf '  FAIL  %s\n' "$1"; FAILED=1; }; skip(){ printf '  SKIP  %s\n' "$1"; }
CREDS=/home/niruthi/.claude/.credentials.json
cd "$H"
echo "== S1 harness state =="
[ "$(git status --porcelain -- src configs | wc -l)" = 0 ] && ok "harness tree clean at $(git rev-parse --short HEAD) (branch $(git branch --show-current))" || bad "uncommitted harness changes"
grep -q "^version: 2.1.310" configs/agents/claude_code_parnas.yaml && ok "CLI pinned 2.1.310" || bad "CLI pin"
grep -q "step_limit: 300" configs/agents/claude_code_parnas.yaml && ok "step cap 300/checkpoint" || bad "step cap"
grep -A2 disallowed_tools configs/agents/claude_code_parnas.yaml | grep -q WebFetch && grep -A3 disallowed_tools configs/agents/claude_code_parnas.yaml | grep -q WebSearch && ok "WebFetch+WebSearch disallowed" || bad "web tools not disallowed"
uv run --quiet python - <<'PY' && ok "MCP isolation as FeatureBench/SWE-Pro: --strict-mcp-config + empty --mcp-config in built CLI args" || bad "MCP isolation flags missing"
import yaml,types
from slop_code.agent_runner.agents.claude_code.agent import ClaudeCodeAgent
c=yaml.safe_load(open("configs/agents/claude_code_parnas.yaml")); a=object.__new__(ClaudeCodeAgent)
for k,v in dict(binary="claude",append_system_prompt=None,model="m",cost_limits=types.SimpleNamespace(step_limit=1),allowed_tools=[],disallowed_tools=[],permission_mode=None,extra_args=c.get("extra_args",[])).items(): object.__setattr__(a,k,v)
s=" ".join(a._build_cli_args()); assert "--strict-mcp-config --mcp-config '{\"mcpServers\":{}}'" in s, s
PY
uv run --quiet python -c "import yaml;assert yaml.safe_load(open('configs/agents/claude_code_parnas.yaml'))['env']['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC']=='1'" && ok "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 in agent env (no account skill/plugin sync)" || bad "NONESSENTIAL_TRAFFIC not set"
grep -q "internal_name: claude-opus-5-5" configs/models/opus-5.5.yaml && ok "model claude-opus-5-5" || bad "model id"

grep -rq "include_os_env: *true" configs/environments/docker-python3.12-uv-parnas-*.yaml && bad "include_os_env true (host env would leak)" || ok "include_os_env false in both parnas envs (host env not copied)"
echo "== S2 credentials never read/injected on host =="
uv run --quiet python - "$CREDS" <<'PY' && ok "ro-mode: no auth env, no token in settings, creds mount is ro outside HOME, wrapper deletes copy on exit" || bad "credential handling"
import os,sys,json; os.environ["SCB_CLAUDE_CREDS"]=sys.argv[1]
from slop_code.agent_runner.agents.claude_code import agent as A
src=open(A.__file__).read()
assert "def _ro_creds_mode" in src and "return {}  # Parnas pilot P1" in src
w=A._wrap_creds("claude --print -- x"); assert "rm -f" in w and "trap" in w and "/creds/credentials.json" in w
assert A._CREDS_CONTAINER_PATH.startswith("/creds/")
PY
[ -z "$(find "$HERE/runs" -name '.credentials.json' 2>/dev/null)" ] && ok "no credentials file under runs/" || bad "credentials file copied under runs/"
n=$(grep -rlE "sk-ant-[A-Za-z0-9_-]{8}" "$HERE/runs" "$H/configs" 2>/dev/null | wc -l); [ "$n" = 0 ] && ok "no token-shaped string (sk-ant-…) in runs/ or configs/ (count only)" || bad "$n file(s) contain a token-shaped string (not printed)"

echo "== S3 the agent cannot see tests or solutions =="
uv run --quiet python - "$P" "$PROB" <<'PY' && ok "static_assets of $PROB contain no tests/solution paths" || bad "static assets include answer material"
import sys,yaml,pathlib; c=yaml.safe_load(open(pathlib.Path(sys.argv[1])/sys.argv[2]/"config.yaml"))
for k,v in c.get("static_assets",{}).items():
    assert not any(x in v["path"] for x in ("test","solution")), v
PY
grep -q "AGENT_PLANTED_EVALUATION_TESTS" src/slop_code/agent_runner/runner.py && ok "planted .evaluation_tests quarantined before eval (P4)" || bad "P4 missing"

echo "== S4 prompts: identical for checkpoint 2+ across conditions; ckpt-1: c1 = just-solve, others add exactly one design line, no DESIGN.md =="
uv run --quiet python - <<'PY' && ok "continuation prompts byte-identical across c1..c4; c1_default == just-solve; c2-c4 = +1 line; no DESIGN.md" || bad "prompt rendering"
import jinja2,glob,hashlib
T={f.split("/")[-1]:jinja2.Template(open(f).read()) for f in sorted(glob.glob("configs/prompts/parnas/c*.jinja"))}
cont={k:t.render(spec="SPEC",is_continuation=True) for k,t in T.items()}
assert len(set(cont.values()))==1, "continuation differs"
for bad in ("DESIGN","modular","information hiding","Parnas","speed","secret"):
    assert bad.lower() not in list(cont.values())[0].lower(), bad
first={k:t.render(spec="SPEC",is_continuation=False) for k,t in T.items()}
assert not any("DESIGN" in v for v in first.values()), "a first-checkpoint prompt still mentions DESIGN"
js=jinja2.Template(open("configs/prompts/just-solve.jinja").read()).render(spec="SPEC",is_continuation=False)
assert first["c1_default.jinja"]==js, "c1_default != just-solve"
base=js.splitlines()
for k,v in first.items():
    extra=[l for l in v.splitlines() if l not in base]; assert len(v.splitlines())==len(base)+(k!="c1_default.jinja") and len(extra)==(k!="c1_default.jinja"), (k,extra)
print("   continuation sha", hashlib.sha256(list(cont.values())[0].encode()).hexdigest()[:12])
PY

echo "== S5 reset (P3) on a scratch workspace =="
uv run --quiet python - <<'PY' && ok "reset deletes DESIGN/CLAUDE/AGENTS/.claude + every agent-written .md/.rst; task-provided .md kept; empties claude_home except settings.json; code kept; listing written" || bad "reset"
import tempfile,pathlib,json,types
from slop_code.agent_runner.runner import AgentRunner
d=pathlib.Path(tempfile.mkdtemp()); ws=d/"ws"; home=d/"home"; out=d/"out"
for p in ["main.py","DESIGN.md","CLAUDE.md","AGENTS.md","pkg/mod.py",".claude/settings.local.json","NOTES.md","README.md","docs/arch.rst","files/O.md"]: (ws/p).parent.mkdir(parents=True,exist_ok=True); (ws/p).write_text("x")
for p in ["settings.json","projects/-workspace/s.jsonl",".credentials.json","todos/a"]: (home/p).parent.mkdir(parents=True,exist_ok=True); (home/p).write_text("x")
out.mkdir(); r=AgentRunner.__new__(AgentRunner); r._parnas_initial_ws={"files/O.md"}; r._session=types.SimpleNamespace(working_dir=ws); r.agent=types.SimpleNamespace(_trace_dir=home); r.output_path=out
r._parnas_reset(types.SimpleNamespace(name="checkpoint_2"))
rec=json.load(open(out/"parnas_reset_checkpoint_2.json"))
assert sorted(rec["after"]["workspace"])==["files/O.md","main.py","pkg/mod.py"], rec["after"]
assert rec["after"]["claude_home"]==["settings.json"], rec["after"]
PY

if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then skip "D* dynamic checks: Docker not reachable"; echo; [ $FAILED = 0 ] && echo "STATIC: ALL PASS" || echo "STATIC: FAILURES"; exit $FAILED; fi

echo "== D0 reset P3b: agent container is replaced; /tmp, ~/.claude.json, ~/.cache do not survive =="
uv run --quiet --project "$HERE/slop-code-bench" python - <<'PY' && ok "container respawned; planted /tmp/t, ~/.claude.json, ~/.cache gone; nothing new" || bad "container respawn"
import docker, types
from slop_code.agent_runner.runner import AgentRunner
cl=docker.from_env(); IMG="slop-code:claude_code-2.1.310-python3.12"
class RT:
    def __init__(s): s._container=None; s._ensure_container_running()
    def _ensure_container_running(s):
        if s._container is None: s._container=cl.containers.run(IMG,"sleep infinity",detach=True,network_mode="none",environment={"HOME":"/tmp/agent_home"})
        return s._container
    def kill(s): s._container.remove(force=True); s._container=None
rt=RT()
try:
    rt._container.exec_run(["sh","-c","mkdir -p /tmp/t /tmp/agent_home/.cache/uv && echo x>/tmp/t/a && echo {}>/tmp/agent_home/.claude.json"])
    rec=AgentRunner._parnas_respawn_container(types.SimpleNamespace(agent=types.SimpleNamespace(_runtime=rt)))
    o=set(rec["old"]["listing"]); n=set(rec["new"]["listing"])
    assert rec["respawned"] and rec["old"]["id"]!=rec["new"]["id"]
    assert {"/tmp/t/a","/tmp/agent_home/.claude.json","/tmp/agent_home/.cache"} <= o-n, o-n
    assert not (n-o), n-o
finally:
    rt.kill()
PY

echo "== D1 egress (agent proxy: Anthropic+PyPI; eval proxy: PyPI only; direct: nothing) =="
"$HERE/net_up.sh" >/dev/null
probe(){ docker run --rm --network scb-cellnet -e HTTPS_PROXY="$1" curlimages/curl:8.10.1 -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$2/" 2>/dev/null; }
for h in api.anthropic.com pypi.org files.pythonhosted.org github.com raw.githubusercontent.com api.github.com huggingface.co www.google.com; do
  a=$(probe http://scb-egress-agent:8888 $h); e=$(probe http://scb-egress-eval:8888 $h); n=$(probe "" $h)
  want_a=0; want_e=0; case $h in api.anthropic.com) want_a=1;; pypi.org|files.pythonhosted.org) want_a=1; want_e=1;; esac
  ra=$([ "$a" != 000 ] && [ "$a" != 403 ] && echo 1 || echo 0); re=$([ "$e" != 000 ] && [ "$e" != 403 ] && echo 1 || echo 0); rn=$([ "$n" != 000 ] && echo 1 || echo 0)
  [ $ra = $want_a ] && [ $re = $want_e ] && [ $rn = 0 ] && ok "$h agent=$a eval=$e direct=$n" || bad "$h agent=$a(want reach=$want_a) eval=$e(want $want_e) direct=$n(want 000)"
done
echo "== D2 agent image: CLI version =="
img=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -i claude | grep 2.1.310 | head -1)
[ -n "$img" ] && v=$(docker run --rm "$img" claude --version 2>/dev/null) && echo "$v" | grep -q 2.1.310 && ok "image $img -> $v" || bad "no agent image with CLI 2.1.310 (build first)"
# slop-code:python3.12 is re-tagged by the harness on every run (base-image hash differs per env yaml), so a baked
# proxy there is expected; requirement = only our proxies, and every runtime env overrides all 6 proxy keys.
b=$(docker image inspect slop-code:python3.12 -f '{{json .Config.Env}}' 2>/dev/null | tr ',' '\n' | grep -i proxy | grep -viE "scb-egress-(agent|eval):8888|no_proxy|localhost")
[ -z "$b" ] && ok "slop-code:python3.12: any baked proxy is one of ours (harness re-tags it per run)" || bad "slop-code:python3.12 baked foreign proxy: $b"
for f in "$H"/configs/environments/docker-python3.12-uv-parnas-{agent,eval}.yaml; do
  n=$(grep -cE "^ +(HTTPS_PROXY|HTTP_PROXY|https_proxy|http_proxy|NO_PROXY|no_proxy):" "$f"); [ "$n" = 6 ] && ok "$(basename $f): all 6 proxy keys set at runtime (override anything baked)" || bad "$(basename $f): only $n/6 proxy keys"
done
for i in "$img"; do
  [ -n "$i" ] && { docker image inspect "$i" -f '{{json .Config.Env}}' | grep -qi proxy && bad "$i has proxy ENV baked in" || ok "$i: no proxy/creds ENV baked"; }
  [ -n "$i" ] && { docker image inspect "$i" -f '{{json .Config.Env}}' | grep -qiE "ANTHROPIC|OAUTH|TOKEN" && bad "$i has auth ENV baked in" || true; }
done
echo "== D3 agent container end-to-end: auth via ro mount + proxy, nothing else reachable =="
if [ -n "$img" ]; then
  out=$(docker run --rm --network scb-cellnet -u "$(id -u):$(id -g)" -e HOME=/tmp/agent_home \
     -e HTTPS_PROXY=http://scb-egress-agent:8888 -e HTTP_PROXY=http://scb-egress-agent:8888 \
     -v "$CREDS:/creds/credentials.json:ro" "$img" /bin/sh -c '
     mkdir -p $HOME/.claude; cp /creds/credentials.json $HOME/.claude/.credentials.json && chmod 600 $HOME/.claude/.credentials.json
     echo "W:$(touch /creds/credentials.json 2>/dev/null && echo writable || echo readonly)"
     echo "ENV:$(env | grep -ciE "ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN")"
     echo "GH:$(python3 -c "import urllib.request as u
try: print(u.urlopen(\"https://github.com\",timeout=10).status)
except Exception as e: print(\"BLOCKED\",type(e).__name__)")"
     r=$(claude --print --model claude-opus-5-5 --max-turns 1 "Reply with exactly: PONG" 2>&1 | tail -1); echo "CLI:$r"' 2>&1)
  echo "$out" | grep -q "^W:readonly" && ok "creds mount read-only inside container" || bad "creds mount writable"
  echo "$out" | grep -q "^ENV:0" && ok "no auth token env vars in container" || bad "auth env present"
  echo "$out" | grep -q "^GH:BLOCKED" && ok "github.com unreachable from agent container ($(echo "$out"|grep ^GH:))" || bad "github reachable: $(echo "$out"|grep ^GH:)"
  echo "$out" | grep -q "^CLI:.*PONG" && ok "claude-opus-5-5 answered through proxy with mounted creds" || bad "CLI call failed: $(echo "$out"|grep ^CLI: | cut -c1-150)"
fi
echo; [ $FAILED = 0 ] && echo "ALL PASS" || echo "FAILURES"; exit $FAILED
