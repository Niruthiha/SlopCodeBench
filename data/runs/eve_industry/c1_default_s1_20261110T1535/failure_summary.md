# Failure summary: runs/eve_industry/c1_default_s1_20261110T1535

## checkpoint_1
pass {'Core': 3, 'Functionality': 6, 'Regression': 0, 'Error': 3} / total {'Core': 3, 'Functionality': 6, 'Regression': 0, 'Error': 3}

**Agent final message:** I've written `industry.py` in `/workspace`. It reproduces all three spec examples (Naga, Barrage L Blueprint, Fernite Carbide) exactly — same item lines, recipe values, materials and Yes/No buildable flags. A venv (`.venv/`) and `requirements.txt` (`PyYAML>=6.0`) are set up.

```
.venv/bin/python industry.py recipe "Barrage L Blueprint" --sde sde
```

**How it works:**
- **Finding the recipe:** you can give a product or a blueprint name; matching is exact and case-sensitive, and only published items count. A blueprint name uses its own recipe. A product name looks up the blueprint (Manufacturing) or reaction formula (Reactions) that makes it.
- **Buildable:** `Yes` only if a published blueprint or formula makes that material. About 200 published items, such as Taipan and Echo, are only made by unpublished blueprints, so they show as `No`.
- **Tech level** comes from `invMetaTypes`, and anything else defaults to `Tech I`. Loki comes out as `Tech III` and Barrage L as `Tech II`.
- **Volume** always has at least two decimals, with any further trailing zeros dropped. This was the one rule that fits all three examples: `15000.00`, `0.025`, `0.01`. A 5 m³ item therefore prints as `5.00`.
- **Table:** materials are sorted case-insensitively. The table uses the `|:-:|:---:|---:|` alignment row from the spec template; the examples' padded columns differ from row to row, so I didn't copy them.
- **Errors:** an unknown name, or an item with no recipe (e.g. `Tritanium`), prints an error 

## checkpoint_2
pass {'Core': 7, 'Functionality': 10, 'Regression': 12, 'Error': 3} / total {'Core': 7, 'Functionality': 11, 'Regression': 12, 'Error': 3}

**checkpoint_2-Functionality** (1 failed)
- `test_invention_functionality[jackdaw-5]`: E                           KeyError: 'Invented From'

**Agent final message:** I've added `python industry.py invention <name> --sde <dir> [--skill 1-5]` to `industry.py`. For all three examples in the spec (`Barrage L` at skill 5 and 3, and `Proteus` at skill 5), the output matches the expected block exactly when diffed. `Barrage L Blueprint` also resolves to the same report as `Barrage L`.

I also ran it on all 1,092 inventable products in the SDE. None crashed: 1,036 came out as Tech II and 56 as Tech III. The existing `recipe` command still works. No new dependencies were needed, so `requirements.txt` is unchanged.

Things you might not expect:

- **Exact order of the probability calculation:** the expected output only matched for one way of adding up the formula. I start at 1, add `level/30` once for each science skill, then add `encryption/40`, and round with Python's `round(p*100, 2)`. Other orders and other rounding methods gave numbers that differed by 0.01 in a few rows. For example, the spec wants `55.12` for Malfunctioning + Attainment but `34.13` for Intact + Optimized Augmentation, even though both sit exactly halfway between two values.
- **Tech III uses activity 8 in this SDE:** the Proteus relics are listed under Invention (8), not Reverse Engineering (7). The code accepts either.
- **Tactical destroyers:** Confessor, Hecate, Jackdaw and Svipul are Tech III, but they're invented from Tech I blueprints rather than relics. For these four I print `Tech Level: Tech III` with the Tech II-style table (including the `Base:` line), since there 

## checkpoint_3
pass {'Core': 5, 'Functionality': 6, 'Regression': 32, 'Error': 5} / total {'Core': 5, 'Functionality': 7, 'Regression': 33, 'Error': 5}

**checkpoint_2-Regression** (1 failed)
- `test_invention_functionality[jackdaw-5]`: E                           KeyError: 'Invented From'

**checkpoint_3-Functionality** (1 failed)
- `test_fernite_carbide_te10`: E       AssertionError:

**Agent final message:** The `recipe` command now takes the three new optional flags, and its output matches every Naga example in the spec. I checked ME=10, ME=5 with the waste column, TE=20 alone, and ME=10 with TE=20 together.

- **`--material-efficiency`/`-me`** accepts an integer from 0 to 10 (default 0). Each quantity is calculated with your formula, `ceil(max(1, qty × (1 − ME/100) × runs))`, with one run per recipe. I used exact fractions instead of floating point, so a result like 100 × 0.9 can't round up to 91 by mistake.
- **`--time-efficiency`/`-te`** accepts an even integer from 0 to 20 (default 0). It reduces the job's seconds before they're converted to minutes, so Naga goes from 250 to 200 at TE=20.
- **`--display-waste`/`-waste`** adds a `Waste` column. Waste is the amount needed at your ME minus the amount needed at ME=10.
- **Bad values** (an ME over 10, or an odd or out-of-range TE) are rejected with a usage message and exit code 2.
- **Reactions** keep their base quantities and time, and show 0 waste.

**Decision for you:** the spec only says ME skips reactions; it doesn't say whether TE does. I assumed TE also skips them, since it's described as similar to ME and that's how the game works. If reactions should get the time reduction, it's a one-line change in `render` in `industry.py`.

The tables use the same compact markdown as the existing output, not the padded columns in your examples; the cell values are the same. `requirements.txt` is unchanged because nothing new was neede

## checkpoint_4
pass {'Core': 2, 'Functionality': 4, 'Regression': 48, 'Error': 2} / total {'Core': 2, 'Functionality': 5, 'Regression': 50, 'Error': 2}

**checkpoint_2-Regression** (1 failed)
- `test_invention_functionality[jackdaw-5]`: E                           KeyError: 'Invented From'

**checkpoint_3-Regression** (1 failed)
- `test_fernite_carbide_te10`: E       AssertionError:

**checkpoint_4-Functionality** (1 failed)
- `test_functionality[svipul_l1-1]`: E       AssertionError: Command failed: Error: No published item named 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section' found in SDE

**Agent final message:** I added the `plan` command to `industry.py`, and both examples from the spec now produce exactly the expected `materials.csv` and `jobs.csv`. I also ran it on a few other cases (shown below), but there are no expected outputs for those to compare against. `requirements.txt` didn't need changes because PyYAML was already listed.

**What it does:**
- **Build strings:** all four forms are recognised, including multi-word decryptor and relic names (e.g. `Legion 5 Parity Decryptor Malfunctioning Hull Section x3`). `x{N}` defaults to 1, and runs default to 1 in the plain item form.
- **Materials:** each job needs `max(runs, ceil(qty × runs × (1 − ME/100)))` of each input. That is why R.A.M. comes out at 100 rather than 90 in the ME 10 example. Only the target item is built; everything else is listed as bought, as in the examples.
- **Invention:** an invented blueprint starts at ME 2 / TE 4 plus the decryptor's modifiers, and its maximum runs are the base runs plus the decryptor's runs. One invented blueprint covers several jobs when they fit within its runs. The number of attempts is `ceil(blueprints needed / success chance)`, using the config's `invention_skill`. Datacores are multiplied by the attempts.
- **Job time:** `days = BP time × runs × (1 − TE) × (1 − te_bonus) / 86400`, rounded to 2 decimals.
- **Errors:** an invalid config, an unknown item or an ME/TE out of range gives a message and exit code 1.
- **Refactor:** I moved the code that picks the invention source into a he

## checkpoint_5
pass {'Core': 3, 'Functionality': 5, 'Regression': 56, 'Error': 2} / total {'Core': 3, 'Functionality': 8, 'Regression': 59, 'Error': 3}

**checkpoint_2-Regression** (1 failed)
- `test_invention_functionality[jackdaw-5]`: E                           KeyError: 'Invented From'

**checkpoint_3-Regression** (1 failed)
- `test_fernite_carbide_te10`: E       AssertionError:

**checkpoint_4-Regression** (1 failed)
- `test_functionality[svipul_l1-1]`: E       AssertionError: Command failed: Error: No published item named 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section' found in SDE

**checkpoint_5-Functionality** (3 failed)
- `test_build_all_functionality[kronos_invent]`: E       AssertionError: Jobs mismatch for kronos_invent
- `test_build_all_functionality[loki_l1_1d]`: E       AssertionError: Jobs mismatch for loki_l1_1d
- `test_build_all_functionality[revelation_10_3d]`: E       AssertionError: Jobs mismatch for revelation_10_3d

**checkpoint_5-Error** (1 failed)
- `test_split_days_over_thirty_fails`: E       AssertionError: Expected error for split_days=31

**Agent final message:** `plan --build-all` is implemented in `industry.py`, job splitting is in place, and all six expected outputs from your examples (`jobs.csv` and `materials.csv` for both Barrage L runs and the Megathron run) match exactly.

**What it does**
- **`--build-all`:** builds every buildable item in the tree instead of buying it. Each component is built in one go for its total demand across the whole tree, then that job is split if it's too long. Built items appear in `materials.csv` only when there's leftover output (shown in `end_amount`); the final product is never listed there.
- **Component ME/TE:** components use `component_bpo_defaults`, reactions use 0/0, and T1 capital ships use 0/0. A ship counts as a T1 capital if it is a Tech I ship whose market path starts with "Ships > Capital Ships" (or whose group is a capital group).
- **Splitting:** this applies to every job, including the top-level item and runs without `--build-all`. The top-level item is split one job at a time, then multiplied by the job count.
- **New config fields:** `split_days` (default 3) and `component_bpo_defaults` (default ME 10 / TE 20), both validated.

**Where I went beyond or against the spec**
- **Jobs exactly at the limit are split.** The spec says split when a job takes *more than* `split_days`, but your 3-day example splits Fernite Carbide, which takes exactly 3.0 days. So a job may only run up to *strictly less than* the limit; with that rule all three examples match.
- **The duration includes `te

## checkpoint_6
pass {'Core': 2, 'Functionality': 1, 'Regression': 66, 'Error': 2} / total {'Core': 2, 'Functionality': 3, 'Regression': 73, 'Error': 2}

**checkpoint_2-Regression** (1 failed)
- `test_invention_functionality[jackdaw-5]`: E                           KeyError: 'Invented From'

**checkpoint_3-Regression** (1 failed)
- `test_fernite_carbide_te10`: E       AssertionError:

**checkpoint_4-Regression** (1 failed)
- `test_functionality[svipul_l1-1]`: E       AssertionError: Command failed: Error: No published item named 'Svipul 1 Accelerant Decryptor Small Malfunctioning Hull Section' found in SDE

**checkpoint_5-Regression** (4 failed)
- `test_build_all_functionality[kronos_invent]`: E       AssertionError: Jobs mismatch for kronos_invent
- `test_build_all_functionality[loki_l1_1d]`: E       AssertionError: Jobs mismatch for loki_l1_1d
- `test_build_all_functionality[revelation_10_3d]`: E       AssertionError: Jobs mismatch for revelation_10_3d
- `test_split_days_over_thirty_fails`: E       AssertionError: Expected error for split_days=31

**checkpoint_6-Functionality** (2 failed)
- `test_build_all_with_stocks_functionality[ion_siege_real]`: E       AssertionError: Materials mismatch for ion_siege_real
- `test_build_all_with_stocks_functionality[kronos]`: E       AssertionError: Jobs mismatch for kronos

**Agent final message:** I've added `--stocks` and `--targets` to the `plan` command. With `--build-all`, the spec example's `jobs.csv` matches exactly, and `materials.csv` matches on every row except one: **Nitrogen Fuel Block** ends at **35**, but the example says **34**.

**The mismatch:** we build 2 runs of 40 blocks (80 total). The jobs that use them are Fulleride (6 runs × 5 = 30) and Platinum Technite (3 runs × 5 = 15), which comes to 45, leaving 35. Every other row in the example follows the same rule I used, so I think the 34 is an error in the example. If that number is checked exactly, this row will fail.

**What the planner does now:**
- **For each item:** it needs `amount consumed + target − stock`. If that's more than zero, it builds the item if it's buildable and either `--build-all` is on or the item is a target. Otherwise it buys it. Stock is always used first.
- **Building targets:**
  - Items that can be built normally use the component ME/TE from the config.
  - T2/T3 items are invented with no decryptor and the config's `invention_skill`. Their builds are split into jobs no larger than the invented blueprint's run limit.
- **Without `--build-all`:** target items are still built, but their inputs are bought.
- **`materials.csv`:**
  - `start_amount` is the stock and `end_amount` is what's left at the end.
  - Stock that's never used and isn't topped up (like the Rifters in the example) isn't listed.
  - Intermediate items that are fully used up and had no stock stay hidden, as bef
