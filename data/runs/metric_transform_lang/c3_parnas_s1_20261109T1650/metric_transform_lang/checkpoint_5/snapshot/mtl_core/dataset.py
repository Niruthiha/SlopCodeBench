"""Input table.

Secret: how the column schema and the stream of input rows are stored.
Callers see column names/types and an ordered stream of entries.
"""


class Dataset:
    """Column schema plus a re-iterable stream of entries, in canonical order.

    Each entry is one of
      ("absent", path, names)  -- a file starts; `names` are columns it lacks
      ("row", provenance, values)  -- values: name -> value (None is null)
      ("bad", BadRecord)       -- a row that could not be read
    """

    def __init__(self, names, types, entries):
        self._names = list(names)
        self._types = list(types)
        self._index = {n: i for i, n in enumerate(self._names)}
        self._entries = entries

    def has(self, name):
        return name in self._index

    def type_of(self, name):
        return self._types[self._index[name]]

    @property
    def names(self):
        return tuple(self._names)

    def entries(self):
        return self._entries()
