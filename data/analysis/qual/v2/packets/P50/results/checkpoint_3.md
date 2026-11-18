# Checkpoint 3 hidden-test results

Outcomes: {'passed': 44, 'failed': 6}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[dual_giga-1]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[dual_giga-5]  [still failing since ck2]

## .evaluation_tests/test_checkpoint_2.py::test_probability_clamps_to_one  [still failing since ck2]

## .evaluation_tests/test_checkpoint_3.py::test_proteus_me5_waste  [FIRST]
```
unctionality: Proteus Tech III ship with ME=5 and waste display."""
        data = load_json_case(3, "proteus")
        case = next(c for c in data["cases"] if c["case_id"] == "me5_waste")
    
        result = run_command(
            entrypoint_argv,
            "recipe",
            data["item_name"],
            "-me",
            "5",
            "-waste",
            "--sde",
            str(sde_dir),
        )
        assert result.returncode == 0, f"Command failed: {result.stderr}"
        actual = parse_item_output(result.stdout)
>       assert_dict_equal(actual, case["expected"])

.evaluation_tests/test_checkpoint_3.py:97: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

actual = {'item': 'Proteus (29988)', 'group': 'Ship > Strategic Cruiser', 'market_group': 'Ships > Cruisers > Advanced Cruisers > Strategic Cruisers > Gallente', 'tech_level': 'Tech III', ...}
expected = {'item': 'Proteus (29988)', 'group': 'Ship > Strategic Cruiser', 'market_group': 'Ships > Cruisers > Advanced Cruisers > Strategic Cruisers > Gallente', 'tech_level': 'Tech III', ...}
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
E         Diff: {'values_changed': {"root['materials']['Metallofullerene Plating']['Waste']": {'new_value': 1, 'old_value': 0}, "root['materials']['R.A.M.- Starship Tech']['Waste']": {'new_value': 1, 'old_value': 0}, "root['materials']['Superconducting Magnetometric Amplifier']['Waste']": {'new_value': 1, 'old_value': 0}}}
E       assert not {'values_changed': {"root['materials']['Metallofullerene Plating']['Waste']": {'new_value': 1, 'old_value': 0}, "root['materials']['R.A.M.- Starship Tech']['Waste']": {'new_value': 1, 'old_value': 0}, "root['materials']['Superconducting Magnetometric Amplifier']['Waste']": {'new_value': 1, 'old_value': 0}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::test_ark_me5_waste  [FIRST]
```
..}
expected = {'item': 'Ark (28850)', 'group': 'Ship > Jump Freighter', 'market_group': 'Ships > Capital Ships > Jump Freighters > Amarr', 'tech_level': 'Tech II', ...}
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
E         Diff: {'values_changed': {"root['materials']['Capital Antimatter Reactor Unit']['Waste']": {'new_value': 39, 'old_value': 38}, "root['materials']['Capital Fusion Thruster']['Waste']": {'new_value': 32, 'old_value': 31}, "root['materials']['Capital Jump Drive']['Waste']": {'new_value': 2, 'old_value': 1}, "root['materials']['Capital Linear Shield Emitter']['Waste']": {'new_value': 34, 'old_value': 33}, "root['materials']['Capital Nanoelectrical Microprocessor']['Waste']": {'new_value': 53, 'old_value': 52}, "root['materials']['Capital Tesseract Capacitor Unit']['Waste']": {'new_value': 53, 'old_value': 52}, "root['materials']['Construction Blocks']['Waste']": {'new_value': 113, 'old_value': 112}, "root['materials']['Morphite']['Waste']": {'new_value': 188, 'old_value': 187}}}
E       assert not {'values_changed': {"root['materials']['Capital Antimatter Reactor Unit']['Waste']": {'new_value': 39, 'old_value': 38}, "root['materials']['Capital Fusion Thruster']['Waste']": {'new_value': 32, 'old_value': 31}, "root['materials']['Capital Jump Drive']['Waste']": {'new_value': 2, 'old_value': 1}, "root['materials']['Capital Linear Shield Emitter']['Waste']": {'new_value': 34, 'old_value': 33}, "root['materials']['Capital Nanoelectrical Microprocessor']['Waste']": {'new_value': 53, 'old_value': 52}, "root['materials']['Capital Tesseract Capacitor Unit']['Waste']": {'new_value': 53, 'old_value': 52}, "root['materials']['Construction Blocks']['Waste']": {'new_value': 113, 'old_value': 112}, "root['materials']['Morphite']['Waste']": {'new_value': 188, 'old_value': 187}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_3.py::test_me10_with_display_waste  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'industry.py']
sde_dir = PosixPath('/workspace/.evaluation_tests/assets/sde_dir')

    @pytest.mark.functionality
    def test_me10_with_display_waste(entrypoint_argv, sde_dir):
        """Functionality: ME=10 with --display-waste should show all zeros."""
        result = run_command(
            entrypoint_argv,
            "recipe",
            "Naga",
            "-me",
            "10",
            "--display-waste",
            "--sde",
            str(sde_dir),
        )
        assert result.returncode == 0, f"Command failed: {result.stderr}"
        actual = parse_item_output(result.stdout)
        # All waste values should be 0 at ME=10
        for material_name, material_data in actual["materials"].items():
            assert "Waste" in material_data, f"Missing Waste column for {material_name}"
>           assert material_data["Waste"] == 0, f"Expected waste=0 for {material_name} at ME=10"
E           AssertionError: Expected waste=0 for Isogen at ME=10
E           assert 2600 == 0

.evaluation_tests/test_checkpoint_3.py:178: AssertionError
```
