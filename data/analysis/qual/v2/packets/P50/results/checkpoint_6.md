# Checkpoint 6 hidden-test results

Outcomes: {'passed': 68, 'failed': 12}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[dual_giga-1]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[dual_giga-5]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_probability_clamps_to_one  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_proteus_me5_waste  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::test_ark_me5_waste  [still failing since ck3]

## .evaluation_tests/test_checkpoint_3.py::test_me10_with_display_waste  [still failing since ck3]

## .evaluation_tests/test_checkpoint_5.py::test_build_all_functionality[kronos_invent]  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::test_build_all_functionality[revelation_10_3d]  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::test_build_all_functionality[loki_l1_1d]  [still failing since ck5]

## .evaluation_tests/test_checkpoint_5.py::test_split_days_over_thirty_fails  [still failing since ck5]

## .evaluation_tests/test_checkpoint_6.py::test_build_all_with_stocks_functionality[kronos]  [FIRST]
```
rgs.extend(["--targets", str(stock_target_path)])
    
        result = run_command(
            entrypoint_argv,
            *args,
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

.evaluation_tests/test_checkpoint_6.py:183: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = {'Auto-Integrity Preservation Seal Blueprint': {855: {'days': 11.4, 'count': 1}}, 'Caesarium Cadmide Reaction Formula'...unt': 1}}, 'Carbon Polymers Reaction Formula': {279: {'days': 27.9, 'count': 6}, 280: {'days': 28.0, 'count': 7}}, ...}
expected = {'Auto-Integrity Preservation Seal Blueprint': {855: {'days': 11.4, 'count': 1}}, 'Caesarium Cadmide Reaction Formula'...unt': 1}}, 'Carbon Polymers Reaction Formula': {279: {'days': 27.9, 'count': 6}, 280: {'days': 28.0, 'count': 7}}, ...}
msg = 'Jobs mismatch for kronos', tolerance = 0.02

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
E       AssertionError: Jobs mismatch for kronos
E         Diff: {'values_changed': {"root['Photonic Metamaterials Reaction Formula']": {'new_value': {299: {'days': 29.9, 'count': 4}, 300: {'days': 30.0, 'count': 3}}, 'old_value': {262: {'days': 26.2, 'count': 8}}}}}
E       assert not {'values_changed': {"root['Photonic Metamaterials Reaction Formula']": {'new_value': {299: {'days': 29.9, 'count': 4}, 300: {'days': 30.0, 'count': 3}}, 'old_value': {262: {'days': 26.2, 'count': 8}}}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_6.py::test_build_all_with_stocks_functionality[ion_siege_real]  [FIRST]
```
de == 0, f"Command failed: {result.stderr}"
    
        # Parse and normalize actual output
        actual_jobs = normalize_csv_jobs(parse_csv_file(output_dir / "jobs.csv"))
        actual_materials = normalize_csv_materials(
            parse_csv_file(output_dir / "materials.csv")
        )
    
        # Compare normalized dicts
        assert_dict_equal(
            actual_jobs, expected_jobs, f"Jobs mismatch for {case_name}"
        )
>       assert_materials_equal(
            actual_materials,
            expected_materials,
            f"Materials mismatch for {case_name}",
        )

.evaluation_tests/test_checkpoint_6.py:186: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = {'Atmospheric Gases': {'to_buy': 0, 'buy_volume': 0.0, 'start_amount': 2484383, 'end_amount': 2412983}, 'Cadmium': {'t...16, 'end_amount': 67516}, 'Caesium': {'to_buy': 0, 'buy_volume': 0.0, 'start_amount': 26496, 'end_amount': 13996}, ...}
expected = {'Atmospheric Gases': {'to_buy': 0, 'buy_volume': 0.0, 'start_amount': 2484383, 'end_amount': 2412983}, 'Cadmium': {'t...16, 'end_amount': 67516}, 'Caesium': {'to_buy': 0, 'buy_volume': 0.0, 'start_amount': 26496, 'end_amount': 13996}, ...}
msg = 'Materials mismatch for ion_siege_real', int_tolerance = 1

    def assert_materials_equal(actual, expected, msg="", int_tolerance=1):
        """Assert materials dicts are equal with off-by-1 tolerance for integers.
    
        Args:
            actual: The actual materials dict
            expected: The expected materials dict
            msg: Optional message for assertion failure
            int_tolerance: Absolute tolerance for numeric comparisons (default 1)
        """
        diff = DeepDiff(
            actual,
            expected,
            ignore_order=True,
            math_epsilon=int_tolerance,
            ignore_numeric_type_changes=True,
        )
>       assert not diff, f"{msg}\nDiff: {diff}"
E       AssertionError: Materials mismatch for ion_siege_real
E         Diff: {'values_changed': {"root['Datacore - Plasma Physics']['end_amount']": {'new_value': 0, 'old_value': 1006}, "root['Datacore - Quantum Physics']['end_amount']": {'new_value': 0, 'old_value': 976}}}
E       assert not {'values_changed': {"root['Datacore - Plasma Physics']['end_amount']": {'new_value': 0, 'old_value': 1006}, "root['Datacore - Quantum Physics']['end_amount']": {'new_value': 0, 'old_value': 976}}}

.evaluation_tests/conftest.py:361: AssertionError
```
