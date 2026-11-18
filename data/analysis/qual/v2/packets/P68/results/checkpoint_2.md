# Checkpoint 2 hidden-test results

Outcomes: {'passed': 30, 'failed': 3}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[dual_giga-1]  [FIRST]
```
actual result dict
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
E         Diff: {'values_changed': {"root['probabilities']['None']['Probability']": {'new_value': 38.25, 'old_value': 37.12}, "root['probabilities']['Accelerant Decryptor']['Probability']": {'new_value': 45.9, 'old_value': 44.54}, "root['probabilities']['Attainment Decryptor']['Probability']": {'new_value': 68.85, 'old_value': 66.81}, "root['probabilities']['Augmentation Decryptor']['Probability']": {'new_value': 22.95, 'old_value': 22.27}, "root['probabilities']['Optimized Attainment Decryptor']['Probability']": {'new_value': 72.68, 'old_value': 70.52}, "root['probabilities']['Optimized Augmentation Decryptor']['Probability']": {'new_value': 34.43, 'old_value': 33.41}, "root['probabilities']['Parity Decryptor']['Probability']": {'new_value': 57.38, 'old_value': 55.68}, "root['probabilities']['Process Decryptor']['Probability']": {'new_value': 42.08, 'old_value': 40.83}, "root['probabilities']['Symmetry Decryptor']['Probability']": {'new_value': 38.25, 'old_value': 37.12}}}
E       assert not {'values_changed': {"root['probabilities']['None']['Probability']": {'new_value': 38.25, 'old_value': 37.12}, "root['probabilities']['Accelerant Decryptor']['Probability']": {'new_value': 45.9, 'old_value': 44.54}, "root['probabilities']['Attainment Decryptor']['Probability']": {'new_value': 68.85, 'old_value': 66.81}, "root['probabilities']['Augmentation Decryptor']['Probability']": {'new_value': 22.95, 'old_value': 22.27}, "root['probabilities']['Optimized Attainment Decryptor']['Probability']": {'new_value': 72.68, 'old_value': 70.52}, "root['probabilities']['Optimized Augmentation Decryptor']['Probability']": {'new_value': 34.43, 'old_value': 33.41}, "root['probabilities']['Parity Decryptor']['Probability']": {'new_value': 57.38, 'old_value': 55.68}, "root['probabilities']['Process Decryptor']['Probability']": {'new_value': 42.08, 'old_value': 40.83}, "root['probabilities']['Symmetry Decryptor']['Probability']": {'new_value': 38.25, 'old_value': 37.12}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[dual_giga-5]  [FIRST]
```
e actual result dict
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
E         Diff: {'values_changed': {"root['probabilities']['None']['Probability']": {'new_value': 55.25, 'old_value': 49.58}, "root['probabilities']['Accelerant Decryptor']['Probability']": {'new_value': 66.3, 'old_value': 59.5}, "root['probabilities']['Attainment Decryptor']['Probability']": {'new_value': 99.45, 'old_value': 89.25}, "root['probabilities']['Augmentation Decryptor']['Probability']": {'new_value': 33.15, 'old_value': 29.75}, "root['probabilities']['Optimized Attainment Decryptor']['Probability']": {'new_value': 100.0, 'old_value': 94.21}, "root['probabilities']['Optimized Augmentation Decryptor']['Probability']": {'new_value': 49.73, 'old_value': 44.63}, "root['probabilities']['Parity Decryptor']['Probability']": {'new_value': 82.88, 'old_value': 74.38}, "root['probabilities']['Process Decryptor']['Probability']": {'new_value': 60.78, 'old_value': 54.54}, "root['probabilities']['Symmetry Decryptor']['Probability']": {'new_value': 55.25, 'old_value': 49.58}}}
E       assert not {'values_changed': {"root['probabilities']['None']['Probability']": {'new_value': 55.25, 'old_value': 49.58}, "root['probabilities']['Accelerant Decryptor']['Probability']": {'new_value': 66.3, 'old_value': 59.5}, "root['probabilities']['Attainment Decryptor']['Probability']": {'new_value': 99.45, 'old_value': 89.25}, "root['probabilities']['Augmentation Decryptor']['Probability']": {'new_value': 33.15, 'old_value': 29.75}, "root['probabilities']['Optimized Attainment Decryptor']['Probability']": {'new_value': 100.0, 'old_value': 94.21}, "root['probabilities']['Optimized Augmentation Decryptor']['Probability']": {'new_value': 49.73, 'old_value': 44.63}, "root['probabilities']['Parity Decryptor']['Probability']": {'new_value': 82.88, 'old_value': 74.38}, "root['probabilities']['Process Decryptor']['Probability']": {'new_value': 60.78, 'old_value': 54.54}, "root['probabilities']['Symmetry Decryptor']['Probability']": {'new_value': 55.25, 'old_value': 49.58}}}

.evaluation_tests/conftest.py:342: AssertionError
```

## .evaluation_tests/test_checkpoint_2.py::test_probability_clamps_to_one  [FIRST]
```
entrypoint_argv = ['uv', 'run', 'industry.py']
sde_dir = PosixPath('/workspace/.evaluation_tests/assets/sde_dir')

    @pytest.mark.functionality
    def test_probability_clamps_to_one(entrypoint_argv, sde_dir):
        """Functionality: Probabilities clamp to 100%."""
        result = run_command(
            entrypoint_argv,
            "invention",
            "Dual Giga Beam Laser II Blueprint",
            "--sde",
            str(sde_dir),
            "--skill",
            "5",
        )
        assert result.returncode == 0, f"Command failed: {result.stderr}"
        actual = parse_invention_output(result.stdout)
        assert actual["item"] == "Dual Giga Beam Laser II (37299)"
        assert actual["tech_level"] == "Tech II"
        # Probabilities dict is keyed by decryptor name
        decryptor_row = actual["probabilities"]["Optimized Attainment Decryptor"]
>       assert decryptor_row["Probability"] == 100.00
E       assert 94.21 == 100.0

.evaluation_tests/test_checkpoint_2.py:179: AssertionError
```
