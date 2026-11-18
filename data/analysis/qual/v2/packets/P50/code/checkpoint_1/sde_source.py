"""Raw access to the EVE Static Data Export.

Secret: the on-disk layout of the SDE -- file names, BZ2 compression, CSV
dialect, column names, the textual encoding of nulls/booleans, and the YAML
format of the ship volume file.

Every function yields plain tuples of Python primitives (int, str, float,
bool, None), so callers never learn how the export is stored.
"""

import bz2
import csv
import io
import os

import yaml

_NULLS = {"", "None", "none", "NULL", "null"}


def _rows(sde_dir, filename):
    path = os.path.join(sde_dir, filename)
    with bz2.open(path, "rb") as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            yield from csv.DictReader(text)


def _int(value):
    if value is None or value.strip() in _NULLS:
        return None
    return int(float(value))


def _text(value):
    if value is None or value in _NULLS:
        return None
    return value


def _flag(value):
    return _int(value) == 1


def types(sde_dir):
    """Yield (type_id, name, group_id, volume_text, published, market_group_id).

    volume_text is the exact decimal string from the export (or None).
    """
    for row in _rows(sde_dir, "invTypes.csv.bz2"):
        yield (
            _int(row["typeID"]),
            row["typeName"],
            _int(row["groupID"]),
            _text(row["volume"]),
            _flag(row["published"]),
            _int(row["marketGroupID"]),
        )


def groups(sde_dir):
    """Yield (group_id, category_id, name, published)."""
    for row in _rows(sde_dir, "invGroups.csv.bz2"):
        yield (
            _int(row["groupID"]),
            _int(row["categoryID"]),
            row["groupName"],
            _flag(row["published"]),
        )


def categories(sde_dir):
    """Yield (category_id, name, published)."""
    for row in _rows(sde_dir, "invCategories.csv.bz2"):
        yield (_int(row["categoryID"]), row["categoryName"], _flag(row["published"]))


def market_groups(sde_dir):
    """Yield (market_group_id, parent_id_or_None, name)."""
    for row in _rows(sde_dir, "invMarketGroups.csv.bz2"):
        yield (
            _int(row["marketGroupID"]),
            _int(row["parentGroupID"]),
            row["marketGroupName"],
        )


def meta_types(sde_dir):
    """Yield (type_id, meta_group_id)."""
    for row in _rows(sde_dir, "invMetaTypes.csv.bz2"):
        yield (_int(row["typeID"]), _int(row["metaGroupID"]))


def meta_groups(sde_dir):
    """Yield (meta_group_id, name)."""
    for row in _rows(sde_dir, "invMetaGroups.csv.bz2"):
        yield (_int(row["metaGroupID"]), row["metaGroupName"])


def activities(sde_dir):
    """Yield (activity_id, name)."""
    for row in _rows(sde_dir, "ramActivities.csv.bz2"):
        yield (_int(row["activityID"]), row["activityName"])


def activity_times(sde_dir):
    """Yield (blueprint_type_id, activity_id, seconds)."""
    for row in _rows(sde_dir, "industryActivity.csv.bz2"):
        yield (_int(row["typeID"]), _int(row["activityID"]), _int(row["time"]))


def activity_products(sde_dir):
    """Yield (blueprint_type_id, activity_id, product_type_id, quantity)."""
    for row in _rows(sde_dir, "industryActivityProducts.csv.bz2"):
        yield (
            _int(row["typeID"]),
            _int(row["activityID"]),
            _int(row["productTypeID"]),
            _int(row["quantity"]),
        )


def activity_materials(sde_dir):
    """Yield (blueprint_type_id, activity_id, material_type_id, quantity)."""
    for row in _rows(sde_dir, "industryActivityMaterials.csv.bz2"):
        yield (
            _int(row["typeID"]),
            _int(row["activityID"]),
            _int(row["materialTypeID"]),
            _int(row["quantity"]),
        )


def ship_packaged_volumes(sde_dir):
    """Yield (ship_group_name, packaged_volume)."""
    path = os.path.join(sde_dir, "ship_volumes.yaml")
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    for name, volume in data.items():
        if volume is not None:
            yield (str(name), float(volume))
