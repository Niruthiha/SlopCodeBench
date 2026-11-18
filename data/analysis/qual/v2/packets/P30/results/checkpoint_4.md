# Checkpoint 4 hidden-test results

Outcomes: {'passed': 56, 'failed': 3}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[jackdaw-5]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_fernite_carbide_te10  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::test_functionality[svipul_l1-1]  [FIRST]
```
case_name = 'svipul_l1', invention_skill = 1
entrypoint_argv = ['uv', 'run', 'industry.py']
sde_dir = PosixPath('/workspace/.evaluation_tests/assets/sde_dir')
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_functionality_svipul_l1_10')

    @pytest.mark.functionality
    @pytest.mark.parametrize(
        "case_name,invention_skill",
        FUNCTIONALITY_CASES,
    )
    def test_functionality(
        case_name, invention_skill, entrypoint_argv, sde_dir, tmp_path
    ):
        """Functionality: Extended functionality tests."""
        expected_materials = load_csv_materials(4, case_name)
        expected_jobs = load_csv_jobs(4, case_name)
    
        config_path = create_config_file(
            checkpoint=4,
            path=tmp_path,
            te_bonus=20,
            invention_skill=invention_skill,
        )
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()
    
        result = run_command(
            entrypoint_argv,
            "plan",
            load_build_string(4, case_name).strip(),
            "--sde",
            str(sde_dir),
            "--config",
            str(config_path),
            "--output",
            str(output_dir),
        )
>       assert result.returncode == 0, f"Command failed: {result.stderr}"
E       AssertionError: Command failed: Error: No published item named 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section' found in SDE
E         
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['uv', 'run', 'industry.py', 'plan', 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section x1', '--sde', '/workspace/.evaluation_tests/assets/sde_dir', '--config', '/tmp/pytest-of-agent/pytest-0/test_functionality_svipul_l1_10/build.yaml', '--output', '/tmp/pytest-of-agent/pytest-0/test_functionality_svipul_l1_10/outputs'], returncode=1, stdout='', stderr="Error: No published item named 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section' found in SDE\n").returncode

.evaluation_tests/test_checkpoint_4.py:127: AssertionError
```
