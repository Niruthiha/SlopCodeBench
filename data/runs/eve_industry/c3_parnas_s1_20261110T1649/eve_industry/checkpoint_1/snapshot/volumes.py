"""Volume an item occupies as an industry output.

Secret: the packaged-volume rule -- which items count as ships, where their
packaged volumes come from, and how current ship group names are reconciled
with the (older) group names used as keys in the packaged-volume table.
"""

import sde_source

_SHIP_CATEGORY = "Ship"

# Current SDE group name -> equivalent key(s) in the packaged-volume table,
# tried in order.  Covers groups that CCP renamed or added after the table's
# naming was fixed; the fallback is a hull of the same packaged size.
_GROUP_ALIASES = {
    "Hauler": ["Industrial"],
    "Deep Space Transport": ["Transport Ship"],
    "Combat Battlecruiser": ["Battlecruiser"],
    "Heavy Assault Cruiser": ["Heavy Assault Ship"],
    "Heavy Interdiction Cruiser": ["Heavy Interdictors"],
    "Electronic Attack Ship": ["Electronic Attack Ships"],
    "Corvette": ["Rookieship"],
    "Logistics Frigate": ["Frigate"],
    "Command Destroyer": ["Destroyer"],
    "Force Auxiliary": ["Carrier"],
    "Flag Cruiser": ["Cruiser"],
}


class VolumeResolver:
    def __init__(self, sde_dir, catalog):
        self._catalog = catalog
        self._packaged = dict(sde_source.ship_packaged_volumes(sde_dir))

    def _packaged_volume(self, type_id):
        if self._catalog.category_name(type_id) != _SHIP_CATEGORY:
            return None
        group = self._catalog.group_name(type_id)
        for key in [group] + _GROUP_ALIASES.get(group, []):
            if key in self._packaged:
                return self._packaged[key]
        return None

    def volume(self, type_id):
        """Return (volume_m3, is_packaged) for the item as produced by industry."""
        packaged = self._packaged_volume(type_id)
        if packaged is not None:
            return packaged, True
        return float(self._catalog.base_volume(type_id)), False
