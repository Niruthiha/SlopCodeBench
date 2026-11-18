# Checkpoint 3 hidden-test results

Outcomes: {'passed': 48, 'failed': 2}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[jackdaw-5]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_fernite_carbide_te10  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'industry.py']
sde_dir = PosixPath('/workspace/.evaluation_tests/assets/sde_dir')

    @pytest.mark.functionality
    def test_fernite_carbide_te10(entrypoint_argv, sde_dir):
        """Functionality: Fernite Carbide reaction with TE=10 (ME doesn't apply to reactions)."""
        data = load_json_case(3, "fernite_carbide")
        case = next(c for c in data["cases"] if c["case_id"] == "te10")
    
        result = run_command(
            entrypoint_argv,
            "recipe",
            data["item_name"],
            "--time-efficiency",
            "10",
            "--sde",
            str(sde_dir),
        )
        assert result.returncode == 0, f"Command failed: {result.stderr}"
        actual = parse_item_output(result.stdout)
>       assert_dict_equal(actual, case["expected"])

.evaluation_tests/test_checkpoint_3.py:76: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = {'item': 'Fernite Carbide (16673)', 'group': 'Material > Composite', 'market_group': 'Manufacture & Research > Materials > Reaction Materials > Advanced Moon Materials', 'tech_level': 'Tech I', ...}
expected = {'item': 'Fernite Carbide (16673)', 'group': 'Material > Composite', 'market_group': 'Manufacture & Research > Materials > Reaction Materials > Advanced Moon Materials', 'tech_level': 'Tech I', ...}
msg = '', tolerance = 0.02

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
E       AssertionError: 
E         Diff: {'values_changed': {"root['run_time']": {'new_value': 162, 'old_value': 180}}}
E       assert not {'values_changed': {"root['run_time']": {'new_value': 162, 'old_value': 180}}}

.evaluation_tests/conftest.py:342: AssertionError
```
