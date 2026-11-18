"""Invention and reverse engineering plans: what a Tech II/III blueprint is
invented from, what the job consumes, and the odds and outcome per decryptor.

Secret: how the industry activity tables link a product to the blueprint it
is built from and that blueprint to its invention inputs; which source is
used when several can invent the same blueprint; which skills count as
"science" and "encryption" skills; how relics are recognised and ranked;
the decryptor and relic modifier tables; and the success chance formula.
"""

from dataclasses import dataclass

import sde_source

_MANUFACTURING = "Manufacturing"
_MANUFACTURING_FALLBACK_ID = 1
_INVENTION_ACTIVITIES = (8, 7)  # Invention, Reverse Engineering

_SCIENCE_GROUP = "Science"
_ENCRYPTION_SUFFIX = "Encryption Methods"

_BASE_ME = 2
_BASE_TE = 4

# name -> (probability multiplier in % from 100%, runs, ME, TE); None first.
_DECRYPTORS = (
    ("None", 0, 0, 0, 0),
    ("Accelerant Decryptor", 20, 1, 2, 10),
    ("Attainment Decryptor", 80, 4, -1, 4),
    ("Augmentation Decryptor", -40, 9, -2, 2),
    ("Optimized Attainment Decryptor", 90, 2, 1, -2),
    ("Optimized Augmentation Decryptor", -10, 7, 2, 0),
    ("Parity Decryptor", 50, 3, 1, -2),
    ("Process Decryptor", 10, 0, 3, 6),
    ("Symmetry Decryptor", 0, 2, 1, 8),
)

# Relic quality word, in display order -> (base chance, base runs).
_RELICS = (
    ("Intact", 0.26, 20),
    ("Malfunctioning", 0.21, 10),
    ("Wrecked", 0.14, 3),
)


@dataclass(frozen=True)
class Outcome:
    invented_from: str  # relic name; None for Tech II
    decryptor: str
    probability: float  # percent, 0-100, unrounded
    runs: int
    me: int
    te: int


@dataclass(frozen=True)
class Plan:
    product_id: int
    from_relics: bool
    base_blueprint: tuple  # (name, type_id) for Tech II; None for relics
    datacores: tuple  # of names
    quantity_per_run: int
    skills: tuple  # of names
    seconds: int
    outcomes: tuple  # of Outcome, in display order


def _relic_rank(name):
    words = name.split()
    for rank, (quality, _, _) in enumerate(_RELICS):
        if quality in words:
            return rank
    return None


def _decryptor_order(row):
    name = row[0]
    return (name != "None", name.lower(), name)


def _chance_percent(base, science_levels, encryption_levels, multiplier):
    skill_factor = 1 + science_levels / 30 + encryption_levels / 40
    percent = (1 + multiplier / 100) * 100 * base * skill_factor
    return min(100.0, max(0.0, percent))


class Invention:
    def __init__(self, sde_dir, catalog):
        self._catalog = catalog
        manufacturing = {
            aid for aid, name in sde_source.activities(sde_dir) if name == _MANUFACTURING
        } or {_MANUFACTURING_FALLBACK_ID}

        # blueprint -> product it manufactures; product -> [blueprints]
        self._builds = {}
        self._built_by = {}
        # invented blueprint -> [(source, activity, runs)]
        self._sources = {}
        for bp, act, product, qty in sde_source.activity_products(sde_dir):
            if not (catalog.is_valid(bp) and catalog.is_valid(product)):
                continue
            if act in manufacturing and bp not in self._builds:
                self._builds[bp] = product
                self._built_by.setdefault(product, []).append(bp)
            elif act in _INVENTION_ACTIVITIES:
                self._sources.setdefault(product, []).append((bp, act, qty or 0))

        jobs = {(src, act) for found in self._sources.values() for src, act, _ in found}
        self._times = {}
        for bp, act, seconds in sde_source.activity_times(sde_dir):
            if (bp, act) in jobs:
                self._times[(bp, act)] = seconds or 0
        self._materials = {}
        for bp, act, material, qty in sde_source.activity_materials(sde_dir):
            if (bp, act) in jobs:
                self._materials.setdefault((bp, act), []).append((material, qty or 0))
        self._skills = {}
        for bp, act, skill, _ in sde_source.activity_skills(sde_dir):
            if (bp, act) in jobs and catalog.is_valid(skill):
                self._skills.setdefault((bp, act), set()).add(skill)
        self._chances = {}
        for bp, act, product, chance in sde_source.activity_probabilities(sde_dir):
            if (bp, act) in jobs and chance is not None:
                self._chances.setdefault((bp, act, product), chance)

    def _invented_blueprint(self, type_id):
        """(product, invented blueprint) for a product or its blueprint, or None."""
        if type_id in self._builds and type_id in self._sources:
            return self._builds[type_id], type_id
        for bp in sorted(self._built_by.get(type_id, [])):
            if bp in self._sources:
                return type_id, bp
        return None

    def _material_name(self, type_id):
        return self._catalog.name(type_id) if self._catalog.is_valid(type_id) else str(type_id)

    def _is_encryption(self, skill):
        return self._catalog.name(skill).endswith(_ENCRYPTION_SUFFIX)

    def _is_science(self, skill):
        return self._catalog.group_name(skill) == _SCIENCE_GROUP and not self._is_encryption(skill)

    def plan(self, type_id, skill_level):
        """Invention plan for a product or its blueprint; None if not inventable."""
        found = self._invented_blueprint(type_id)
        if found is None:
            return None
        product, target = found
        sources = self._sources[target]
        relics = [s for s in sources if _relic_rank(self._catalog.name(s[0])) is not None]

        if relics:
            jobs = sorted(
                relics,
                key=lambda s: (
                    _relic_rank(self._catalog.name(s[0])),
                    self._catalog.name(s[0]).lower(),
                    s[0],
                ),
            )
        else:
            jobs = [min(sources, key=lambda s: ((s[0], s[1], target) not in self._chances, s[0]))]

        keys = [(src, act) for src, act, _ in jobs]
        materials = [m for key in keys for m in self._materials.get(key, ())]
        skills = set().union(*(self._skills.get(key, set()) for key in keys))
        science = sum(skill_level for s in skills if self._is_science(s))
        encryption = sum(skill_level for s in skills if self._is_encryption(s))

        outcomes = []
        for src, act, runs in jobs:
            if relics:
                _, base, base_runs = _RELICS[_relic_rank(self._catalog.name(src))]
                invented_from = self._catalog.name(src)
            else:
                base = self._chances.get((src, act, target), 0.0)
                base_runs = runs
                invented_from = None
            for name, multiplier, d_runs, d_me, d_te in sorted(_DECRYPTORS, key=_decryptor_order):
                outcomes.append(
                    Outcome(
                        invented_from=invented_from,
                        decryptor=name,
                        probability=_chance_percent(base, science, encryption, multiplier),
                        runs=base_runs + d_runs,
                        me=_BASE_ME + d_me,
                        te=_BASE_TE + d_te,
                    )
                )

        base_bp = None
        if not relics:
            base_bp = (self._catalog.name(jobs[0][0]), jobs[0][0])
        return Plan(
            product_id=product,
            from_relics=bool(relics),
            base_blueprint=base_bp,
            datacores=tuple(sorted({self._material_name(m) for m, _ in materials}, key=lambda n: (n.lower(), n))),
            quantity_per_run=max((q for _, q in materials), default=0),
            skills=tuple(sorted({self._catalog.name(s) for s in skills}, key=lambda n: (n.lower(), n))),
            seconds=self._times.get(keys[0], 0),
            outcomes=tuple(outcomes),
        )
