# Checkpoint 5 hidden-test results

Outcomes: {'passed': 66, 'failed': 7}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[jackdaw-5]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_fernite_carbide_te10  [still failing since ck3]

## .evaluation_tests/test_checkpoint_4.py::test_functionality[svipul_l1-1]  [still failing since ck4]

## .evaluation_tests/test_checkpoint_5.py::test_build_all_functionality[kronos_invent]  [FIRST]
```
build-all",
            "--config",
            str(config_path),
            "--output",
            str(output_dir),
            timeout=timeout,
        )
        assert result.returncode == 0, f"Command failed: {result.stderr}"
    
        # Parse and normalize actual output
        actual_jobs = normalize_csv_jobs(parse_csv_file(output_dir / "jobs.csv"))
        actual_materials = normalize_csv_materials(
            parse_csv_file(output_dir / "materials.csv")
        )
    
        # Compare normalized dicts
>       assert_dict_equal(
            actual_jobs, expected_jobs, f"Jobs mismatch for {case_name}"
        )

.evaluation_tests/test_checkpoint_5.py:158: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = {'Auto-Integrity Preservation Seal Blueprint': {1800: {'days': 24.0, 'count': 1}}, 'Caesarium Cadmide Reaction Formula...nt': 1}}, 'Carbon Polymers Reaction Formula': {283: {'days': 28.3, 'count': 11}, 284: {'days': 28.4, 'count': 2}}, ...}
expected = {'Auto-Integrity Preservation Seal Blueprint': {1800: {'days': 24.0, 'count': 1}}, 'Caesarium Cadmide Reaction Formula...nt': 1}}, 'Carbon Polymers Reaction Formula': {283: {'days': 28.3, 'count': 11}, 284: {'days': 28.4, 'count': 2}}, ...}
msg = 'Jobs mismatch for kronos_invent', tolerance = 0.02

    def assert_dict_equal(actual, expected, msg="", tolerance=0.02):
        """Assert dicts are equal using deepdiff for better error messages.
    
        Args:
            actual: The actual result dict
            expected: The expected result dict
            msg: Optional message for assertion failure
            tolerance: Tolerance for numeric comparisons (default 0.02)
        """
        diff = DeepDiff(
            actual,
            expected,
            ignore_order=True,
            math_epsilon=tolerance,
            ignore_numeric_type_changes=True,
        )
>       assert not diff, f"{msg}\nDiff: {diff}"
E       AssertionError: Jobs mismatch for kronos_invent
E         Diff: {'values_changed': {"root['Photonic Metamaterials Reaction Formula']": {'new_value': {299: {'days': 29.9, 'count': 4}, 300: {'days': 30.0, 'count': 3}}, 'old_value': {262: {'days': 26.2, 'count': 8}}}}}
E       assert not {'values_changed': {"root['Photonic Metamaterials Reaction Formula']": {'new_value': {299: {'days': 29.9, 'count': 4}, 300: {'days': 30.0, 'count': 3}}, 'old_value': {262: {'days': 26.2, 'count': 8}}}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_5.py::test_build_all_functionality[revelation_10_3d]  [FIRST]
```
   
        Args:
            actual: The actual result dict
            expected: The expected result dict
            msg: Optional message for assertion failure
            tolerance: Tolerance for numeric comparisons (default 0.02)
        """
        diff = DeepDiff(
            actual,
            expected,
            ignore_order=True,
            math_epsilon=tolerance,
            ignore_numeric_type_changes=True,
        )
>       assert not diff, f"{msg}\nDiff: {diff}"
E       AssertionError: Jobs mismatch for revelation_10_3d
E         Diff: {'dictionary_item_added': ["root['Carbon Polymers Reaction Formula'][29]", "root['Pressurized Oxidizers Reaction Formula'][29]", "root['Sulfuric Acid Reaction Formula'][29]"], 'dictionary_item_removed': ["root['Carbon Polymers Reaction Formula'][27]", "root['Pressurized Oxidizers Reaction Formula'][27]", "root['Sulfuric Acid Reaction Formula'][27]"], 'values_changed': {"root['Carbon Polymers Reaction Formula']['number:28.000000000000']['count']": {'new_value': 9, 'old_value': 14}, "root['Fullerene Intercalated Graphite Reaction Formula']": {'new_value': {29: {'days': 2.9, 'count': 1}, 30: {'days': 3.0, 'count': 1}}, 'old_value': {19: {'days': 1.9, 'count': 1}, 20: {'days': 2.0, 'count': 2}}}, "root['Pressurized Oxidizers Reaction Formula']['number:28.000000000000']['count']": {'new_value': 9, 'old_value': 14}, "root['Sulfuric Acid Reaction Formula']['number:28.000000000000']['count']": {'new_value': 9, 'old_value': 14}}}
E       assert not {'dictionary_item_added': ["root['Carbon Polymers Reaction Formula'][29]", "root['Pressurized Oxidizers Reaction Formula'][29]", "root['Sulfuric Acid Reaction Formula'][29]"], 'dictionary_item_removed': ["root['Carbon Polymers Reaction Formula'][27]", "root['Pressurized Oxidizers Reaction Formula'][27]", "root['Sulfuric Acid Reaction Formula'][27]"], 'values_changed': {"root['Carbon Polymers Reaction Formula']['number:28.000000000000']['count']": {'new_value': 9, 'old_value': 14}, "root['Fullerene Intercalated Graphite Reaction Formula']": {'new_value': {29: {'days': 2.9, 'count': 1}, 30: {'days': 3.0, 'count': 1}}, 'old_value': {19: {'days': 1.9, 'count': 1}, 20: {'days': 2.0, 'count': 2}}}, "root['Pressurized Oxidizers Reaction Formula']['number:28.000000000000']['count']": {'new_value': 9, 'old_value': 14}, "root['Sulfuric Acid Reaction Formula']['number:28.000000000000']['count']": {'new_value': 9, 'old_value': 14}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_5.py::test_build_all_functionality[loki_l1_1d]  [FIRST]
```
Intercalated Graphite Reaction Formula']['number:9.000000000000']['count']": {'new_value': 8, 'old_value': 16}, "root['Fulleroferrocene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 8, 'old_value': 16}, "root['Lanthanum Metallofullerene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 3, 'old_value': 13}, "root['Methanofullerene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 8, 'old_value': 6}, "root['PPD Fullerene Fibers Reaction Formula']['number:9.000000000000']['count']": {'new_value': 3, 'old_value': 11}, "root['Scandium Metallofullerene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 1, 'old_value': 27}}}
E       assert not {'dictionary_item_added': ["root['C3-FTM Acid Reaction Formula'][10]", "root['Fullerene Intercalated Graphite Reaction Formula'][10]", "root['Fulleroferrocene Reaction Formula'][10]", "root['Lanthanum Metallofullerene Reaction Formula'][10]", "root['Methanofullerene Reaction Formula'][10]", "root['PPD Fullerene Fibers Reaction Formula'][10]", "root['Scandium Metallofullerene Reaction Formula'][10]"], 'dictionary_item_removed': ["root['Fullerene Intercalated Graphite Reaction Formula'][8]", "root['Fulleroferrocene Reaction Formula'][8]", "root['Methanofullerene Reaction Formula'][8]", "root['PPD Fullerene Fibers Reaction Formula'][8]", "root['Scandium Metallofullerene Reaction Formula'][8]"], 'values_changed': {"root['C3-FTM Acid Reaction Formula']['number:9.000000000000']['count']": {'new_value': 2, 'old_value': 62}, "root['Carbon-86 Epoxy Resin Reaction Formula']": {'new_value': {10: {'days': 1.0, 'count': 25}}, 'old_value': {8: {'days': 0.8, 'count': 2}, 9: {'days': 0.9, 'count': 26}}}, "root['Fullerene Intercalated Graphite Reaction Formula']['number:9.000000000000']['count']": {'new_value': 8, 'old_value': 16}, "root['Fulleroferrocene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 8, 'old_value': 16}, "root['Lanthanum Metallofullerene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 3, 'old_value': 13}, "root['Methanofullerene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 8, 'old_value': 6}, "root['PPD Fullerene Fibers Reaction Formula']['number:9.000000000000']['count']": {'new_value': 3, 'old_value': 11}, "root['Scandium Metallofullerene Reaction Formula']['number:9.000000000000']['count']": {'new_value': 1, 'old_value': 27}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_5.py::test_split_days_over_thirty_fails  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'industry.py']
sde_dir = PosixPath('/workspace/.evaluation_tests/assets/sde_dir')
tmp_path = PosixPath('/tmp/pytest-of-agent/pytest-0/test_split_days_over_thirty_fa0')

    @pytest.mark.error
    def test_split_days_over_thirty_fails(entrypoint_argv, sde_dir, tmp_path):
        """Error: split_days=31 should fail with clear error."""
        config_path = create_config_file(
            checkpoint=5,
            path=tmp_path,
            te_bonus=20,
            invention_skill=3,
            split_days=31,
        )
        output_dir = tmp_path / "outputs"
        output_dir.mkdir()
    
        result = run_command(
            entrypoint_argv,
            "plan",
            "Barrage L 10 None x10",
            "--sde",
            str(sde_dir),
            "--build-all",
            "--config",
            str(config_path),
            "--output",
            str(output_dir),
        )
>       assert result.returncode != 0, "Expected error for split_days=31"
E       AssertionError: Expected error for split_days=31
E       assert 0 != 0
E        +  where 0 = CompletedProcess(args=['uv', 'run', 'industry.py', 'plan', 'Barrage L 10 None x10', '--sde', '/workspace/.evaluation_tests/assets/sde_dir', '--build-all', '--config', '/tmp/pytest-of-agent/pytest-0/test_split_days_over_thirty_fa0/build.yaml', '--output', '/tmp/pytest-of-agent/pytest-0/test_split_days_over_thirty_fa0/outputs'], returncode=0, stdout='', stderr='').returncode

.evaluation_tests/test_checkpoint_5.py:284: AssertionError
```
