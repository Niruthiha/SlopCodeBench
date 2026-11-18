# Checkpoint 6 hidden-test results

Outcomes: {'passed': 211, 'failed': 17}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_infer_is_not_none_narrowing_excludes_none  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_circular_import_hides_name_not_yet_defined  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::test_goto_prefers_py_source_when_stub_exists  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::test_goto_uses_stub_when_definition_only_in_stub  [still failing since ck4]

## .evaluation_tests/test_checkpoint_4.py::test_references_unresolved_name_returns_empty  [still failing since ck4]

## .evaluation_tests/test_checkpoint_5.py::test_extract_variable_inserts_assignment_and_replaces_expression  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::test_extract_variable_diff_output_is_unified_diff  [still failing since ck5]

## .evaluation_tests/test_checkpoint_6.py::test_env_list_includes_fake_envs  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_includes_fake_en0')

    def test_env_list_includes_fake_envs(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        py311 = bin_dir / "python3.11"
        py312 = bin_dir / "python3.12"
        _make_fake_python(py311, version="3.11.6", is_virtualenv=False, prefix="/sys/311", sys_path=["/sys/311/lib"])
        _make_fake_python(py312, version="3.12.1", is_virtualenv=True, prefix="/venv/312", sys_path=["/venv/312/lib"])
    
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = run_cmd(entrypoint_argv, ["env", "list"], cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr
        payload = parse_json_result(result)
        entries = payload.get("environments", [])
        assert isinstance(entries, list)
    
        fake_entries = [e for e in entries if str(e.get("executable", "")).startswith(str(tmp_path))]
>       assert len(fake_entries) >= 2
E       assert 0 >= 2
E        +  where 0 = len([])

.evaluation_tests/test_checkpoint_6.py:172: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_env_info_with_explicit_executable  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_info_with_explicit_ex0')

    def test_env_info_with_explicit_executable(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        fake = tmp_path / "venv" / "bin" / "python"
        _make_fake_python(
            fake,
            version="3.12.9",
            is_virtualenv=True,
            prefix="/tmp/fakevenv",
            sys_path=["/tmp/fakevenv/lib"],
        )
    
        result = run_cmd(entrypoint_argv, ["env", "info", str(fake)], cwd=tmp_path)
>       assert result.returncode == 0, result.stderr
E       AssertionError: error: not a usable Python executable: /tmp/pytest-of-agent/pytest-0/test_env_info_with_explicit_ex0/venv/bin/python
E         
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['uv', 'run', '--project', '/workspace', '/workspace/sith.py', 'env', 'info', '/tmp/pytest-of-agent/pytest-0/test_env_info_with_explicit_ex0/venv/bin/python'], returncode=1, stdout='', stderr='error: not a usable Python executable: /tmp/pytest-of-agent/pytest-0/test_env_info_with_explicit_ex0/venv/bin/python\n').returncode

.evaluation_tests/test_checkpoint_6.py:192: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_env_find_virtualenvs_with_path_finds_immediate_subdirs  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_find_virtualenvs_with0')

    def test_env_find_virtualenvs_with_path_finds_immediate_subdirs(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        scan_root = tmp_path / "envs"
        fake = scan_root / "a_env" / "bin" / "python"
        _make_fake_python(
            fake,
            version="3.11.5",
            is_virtualenv=True,
            prefix="/tmp/a_env",
            sys_path=["/tmp/a_env/lib"],
        )
        result = run_cmd(
            entrypoint_argv,
            ["env", "find-virtualenvs", "--path", str(scan_root)],
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        envs = parse_json_result(result)["environments"]
>       assert any(item["executable"] == str(fake) for item in envs)
E       assert False
E        +  where False = any(<generator object test_env_find_virtualenvs_with_path_finds_immediate_subdirs.<locals>.<genexpr> at 0x76274824f760>)

.evaluation_tests/test_checkpoint_6.py:276: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_runtime_attribute_completion_from_namespaces  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_runtime_attribute_complet0')

    def test_runtime_attribute_completion_from_namespaces(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        ns_path = tmp_path / "namespaces.json"
        ns_path.write_text(
            json.dumps(
                [
                    {
                        "df": {
                            "type": "DataFrame",
                            "module": "pandas",
                            "attributes": ["groupby", "merge", "head"],
                        }
                    }
                ]
            )
        )
        result = run_complete(
            entrypoint_argv,
            tmp_path,
            "main.py",
            "result = df.gr|\n",
            extra_args=["--interpreter", "--namespaces", str(ns_path)],
        )
        assert result.returncode == 0, result.stderr
        payload = parse_json_result(result)
        names = completion_names(payload)
        assert "groupby" in names
        groupby_item = find_completion(payload, "groupby")
>       assert groupby_item["type"] == "DataFrame"
E       AssertionError: assert 'statement' == 'DataFrame'
E         
E         - DataFrame
E         + statement

.evaluation_tests/test_checkpoint_6.py:410: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_env_list_sort_order_descending_version  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_sort_order_desce0')

    def test_env_list_sort_order_descending_version(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        """Entries from env list are sorted by version descending."""
        bin_dir = tmp_path / "bin"
        py310 = bin_dir / "python3.10"
        py311 = bin_dir / "python3.11"
        py312 = bin_dir / "python3.12"
        _make_fake_python(py310, version="3.10.4", is_virtualenv=False, prefix="/sys/310", sys_path=["/sys/310/lib"])
        _make_fake_python(py311, version="3.11.6", is_virtualenv=False, prefix="/sys/311", sys_path=["/sys/311/lib"])
        _make_fake_python(py312, version="3.12.1", is_virtualenv=False, prefix="/sys/312", sys_path=["/sys/312/lib"])
    
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = run_cmd(entrypoint_argv, ["env", "list"], cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr
        payload = parse_json_result(result)
        entries = payload.get("environments", [])
    
        fake_entries = [e for e in entries if str(e.get("executable", "")).startswith(str(tmp_path))]
>       assert len(fake_entries) >= 3
E       assert 0 >= 3
E        +  where 0 = len([])

.evaluation_tests/test_checkpoint_6.py:553: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_env_list_dedupes_symlinked_fake_executables  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_dedupes_symlinke0')

    @pytest.mark.functionality
    def test_env_list_dedupes_symlinked_fake_executables(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        target = bin_dir / "python3.11"
        link = bin_dir / "python"
        _make_fake_python(
            target,
            version="3.11.0",
            is_virtualenv=False,
            prefix="/tmp/sys311",
            sys_path=["/tmp/sys311/lib"],
        )
        link.symlink_to(target)
    
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = run_cmd(entrypoint_argv, ["env", "list"], cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr
        entries = parse_json_result(result)["environments"]
    
        resolved = [
            str(Path(item["executable"]).resolve())
            for item in entries
            if str(item["executable"]).startswith(str(tmp_path))
        ]
>       assert resolved.count(str(target.resolve())) == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = <built-in method count of list object at 0x762747ed5c40>('/tmp/pytest-of-agent/pytest-0/test_env_list_dedupes_symlinke0/bin/python3.11')
E        +    where <built-in method count of list object at 0x762747ed5c40> = [].count
E        +    and   '/tmp/pytest-of-agent/pytest-0/test_env_list_dedupes_symlinke0/bin/python3.11' = str(PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_dedupes_symlinke0/bin/python3.11'))
E        +      where PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_dedupes_symlinke0/bin/python3.11') = resolve()
E        +        where resolve = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_dedupes_symlinke0/bin/python3.11').resolve

.evaluation_tests/test_checkpoint_6.py:739: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_env_list_equal_versions_sort_by_executable_path  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_list_equal_versions_s0')

    @pytest.mark.functionality
    def test_env_list_equal_versions_sort_by_executable_path(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        left = tmp_path / "a-bin" / "python3.11"
        right = tmp_path / "z-bin" / "python3.11"
        _make_fake_python(
            left,
            version="3.11.6",
            is_virtualenv=False,
            prefix="/tmp/a311",
            sys_path=["/tmp/a311/lib"],
        )
        _make_fake_python(
            right,
            version="3.11.6",
            is_virtualenv=False,
            prefix="/tmp/z311",
            sys_path=["/tmp/z311/lib"],
        )
    
        env = {
            "PATH": (
                f"{left.parent}{os.pathsep}{right.parent}"
                f"{os.pathsep}{os.environ.get('PATH', '')}"
            )
        }
        result = run_cmd(entrypoint_argv, ["env", "list"], cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr
        entries = parse_json_result(result)["environments"]
    
        fake_entries = [
            item
            for item in entries
            if item["version"] == "3.11.6"
            and str(item["executable"]).startswith(str(tmp_path))
        ]
>       assert len(fake_entries) >= 2
E       assert 0 >= 2
E        +  where 0 = len([])

.evaluation_tests/test_checkpoint_6.py:779: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_interpreter_goto_uses_first_namespace_match_wins  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_interpreter_goto_uses_fir0')

    @pytest.mark.functionality
    def test_interpreter_goto_uses_first_namespace_match_wins(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        ns_path = tmp_path / "namespaces.json"
        ns_path.write_text(
            json.dumps(
                [
                    {"dup": {"type": "module", "module": "first_mod"}},
                    {"dup": {"type": "class", "module": "second_mod"}},
                ]
            )
        )
        source, line, col = locate_cursor("dup|\n")
        write_files(tmp_path, {"main.py": source})
        result = run_cmd(
            entrypoint_argv,
            [
                "goto",
                str(tmp_path / "main.py"),
                str(line),
                str(col),
                "--interpreter",
                "--namespaces",
                str(ns_path),
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        definitions = parse_json_result(result)["definitions"]
>       assert any(
            d["name"] == "dup"
            and d["type"] == "module"
            and d.get("full_name") == "first_mod.dup"
            for d in definitions
        )
E       assert False
E        +  where False = any(<generator object test_interpreter_goto_uses_first_namespace_match_wins.<locals>.<genexpr> at 0x762747dd2e90>)

.evaluation_tests/test_checkpoint_6.py:898: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_env_find_virtualenvs_scans_default_locations  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_env_find_virtualenvs_scan0')

    def test_env_find_virtualenvs_scans_default_locations(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        fake = tmp_path / ".venv" / "bin" / "python"
        _make_fake_python(
            fake,
            version="3.12.0",
            is_virtualenv=True,
            prefix="/tmp/.venv",
            sys_path=["/tmp/.venv/lib"],
        )
        result = run_cmd(entrypoint_argv, ["env", "find-virtualenvs"], cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        envs = parse_json_result(result)["environments"]
>       assert any(item["executable"] == str(fake) for item in envs)
E       assert False
E        +  where False = any(<generator object test_env_find_virtualenvs_scans_default_locations.<locals>.<genexpr> at 0x76274824d700>)

.evaluation_tests/test_checkpoint_6.py:952: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_setting_smart_sys_path_changes_resolution  [FIRST]
```
entrypoint_argv = ['uv', 'run', '--project', '/workspace', '/workspace/sith.py']
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_setting_smart_sys_path_ch0')

    @pytest.mark.functionality
    def test_setting_smart_sys_path_changes_resolution(
        entrypoint_argv: list[str], tmp_path: Path
    ) -> None:
        write_files(
            tmp_path,
            {
                "extras/__init__.py": "",
                "extras/helper.py": "VALUE = 1\n",
                "main2.py": "import helper\nhelper.VA|\n",
            },
        )
        without_smart = run_complete(
            entrypoint_argv,
            tmp_path,
            "main2.py",
            "import helper\nhelper.VA|\n",
            extra_args=["--setting", "smart_sys_path=false"],
        )
        with_smart = run_complete(
            entrypoint_argv,
            tmp_path,
            "main2.py",
            "import helper\nhelper.VA|\n",
            extra_args=["--setting", "smart_sys_path=true"],
        )
        assert without_smart.returncode == 0, without_smart.stderr
        assert with_smart.returncode == 0, with_smart.stderr
        assert "VALUE" not in completion_names(parse_json_result(without_smart))
>       assert "VALUE" in completion_names(parse_json_result(with_smart))
E       assert 'VALUE' in []
E        +  where [] = completion_names({'completions': []})
E        +    where {'completions': []} = parse_json_result(CompletedProcess(args=['uv', 'run', '--project', '/workspace', '/workspace/sith.py', 'complete', '/tmp/pytest-of-agent/pytest-0/test_setting_smart_sys_path_ch0/main2.py', '2', '9', '--setting', 'smart_sys_path=true'], returncode=0, stdout='{"completions":[]}\n', stderr=''))

.evaluation_tests/test_checkpoint_6.py:1095: AssertionError
```
