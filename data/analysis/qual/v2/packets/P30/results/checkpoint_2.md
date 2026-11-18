# Checkpoint 2 hidden-test results

Outcomes: {'passed': 32, 'failed': 1}

Tests listed below did not pass. FIRST = first checkpoint where this test fails in this cell. REGRESSION = the test passed at an earlier checkpoint of this cell.

## .evaluation_tests/test_checkpoint_2.py::test_invention_functionality[jackdaw-5]  [FIRST]
```
     | Probability | Runs | ME | TE |\n|---------------------------------|-------------|...tor               | 41.71       | 20   | 5  | 10 |\n| Symmetry Decryptor              | 37.92       | 22   | 3  | 12 |'
is_t3 = True

    def parse_markdown_table(text: str, is_t3: bool = False) -> dict | list[dict]:
        """Parse markdown table into structured data.
    
        Args:
            text: The markdown table text
            is_t3: If True, keys are "Invented From|Decryptor" for invention tables
    
        Returns:
            For invention tables (is_t3=False with Decryptor column): dict keyed by decryptor
            For invention tables (is_t3=True): dict keyed by "relic|decryptor"
            For recipe tables: list of dicts with Item as a field
        """
        lines = [
            line.strip()
            for line in text.strip().splitlines()
            if line.strip().startswith("|")
        ]
        if len(lines) < 2:
            return {} if is_t3 else []
    
        header = [cell.strip() for cell in lines[0].strip().strip("|").split("|")]
        data_lines = lines[2:]
    
        # Check if this is an invention table (has Decryptor column)
        is_invention_table = "Decryptor" in header
    
        if is_invention_table:
            result = {}
            for line in data_lines:
                if line.strip():
                    cells = [
                        cell.strip() for cell in line.strip().strip("|").split("|")
                    ]
                    if any(cells):
                        row = dict(zip(header, cells))
                        # Convert numeric columns to proper types
                        if "Probability" in row:
                            row["Probability"] = float(row["Probability"])
                        if "Runs" in row:
                            row["Runs"] = int(row["Runs"])
                        if "ME" in row:
                            row["ME"] = int(row["ME"])
                        if "TE" in row:
                            row["TE"] = int(row["TE"])
    
                        # Build the key and remove key columns from value dict
                        if is_t3:
                            key = (
>                               f"{row.pop('Invented From')}|{row.pop('Decryptor')}"
                                   ^^^^^^^^^^^^^^^^^^^^^^^^
                            )
E                           KeyError: 'Invented From'

.evaluation_tests/conftest.py:127: KeyError
```
