"""Item metadata: names, classification, market location and tech level.

Secret: how type, group, category, market-group and meta-group records are
indexed and joined, which records count as valid (published), and how a
meta group is translated into a tech level label.
"""

import re

import sde_source

_TECH_LABEL = re.compile(r"\bTech (I{1,3})$")
_DEFAULT_TECH = "Tech I"


class Catalog:
    def __init__(self, sde_dir):
        self._types = {}
        self._ids_by_name = {}
        for type_id, name, group_id, volume, published, market_id in sde_source.types(sde_dir):
            if not published:
                continue
            self._types[type_id] = (name, group_id, volume, market_id)
            self._ids_by_name.setdefault(name, []).append(type_id)

        self._groups = {gid: (cid, name) for gid, cid, name, _ in sde_source.groups(sde_dir)}
        self._categories = {cid: name for cid, name, _ in sde_source.categories(sde_dir)}
        self._markets = {mid: (parent, name) for mid, parent, name in sde_source.market_groups(sde_dir)}

        meta_names = dict(sde_source.meta_groups(sde_dir))
        self._tech = {}
        for type_id, meta_id in sde_source.meta_types(sde_dir):
            match = _TECH_LABEL.search(meta_names.get(meta_id) or "")
            if match:
                self._tech[type_id] = "Tech " + match.group(1)

    def ids_named(self, name):
        """Published type IDs whose name matches exactly, ascending."""
        return sorted(self._ids_by_name.get(name, []))

    def is_valid(self, type_id):
        return type_id in self._types

    def name(self, type_id):
        return self._types[type_id][0]

    def group_name(self, type_id):
        group = self._groups.get(self._types[type_id][1])
        return group[1] if group else ""

    def category_name(self, type_id):
        group = self._groups.get(self._types[type_id][1])
        return self._categories.get(group[0], "") if group else ""

    def base_volume(self, type_id):
        """Volume as recorded on the type, as an exact decimal string."""
        return self._types[type_id][2] or "0"

    def market_path(self, type_id):
        """Market group names from root to leaf; empty if not on the market."""
        path = []
        seen = set()
        current = self._types[type_id][3]
        while current is not None and current in self._markets and current not in seen:
            seen.add(current)
            parent, name = self._markets[current]
            path.append(name)
            current = parent
        return list(reversed(path))

    def tech_level(self, type_id):
        return self._tech.get(type_id, _DEFAULT_TECH)
