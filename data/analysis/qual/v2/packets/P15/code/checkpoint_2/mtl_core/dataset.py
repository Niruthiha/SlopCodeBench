"""In-memory table.

Secret: how rows and the column schema are stored.  Callers see only
column names/types and read-only records.
"""


class Record:
    """Read-only view of one row."""

    __slots__ = ("_index", "_values")

    def __init__(self, index, values):
        self._index = index
        self._values = values

    def get(self, name):
        return self._values[self._index[name]]


class Dataset:
    def __init__(self, names, types, rows):
        self._names = list(names)
        self._types = list(types)
        self._index = {n: i for i, n in enumerate(self._names)}
        self._rows = rows

    @classmethod
    def from_rows(cls, names, types, rows):
        """Build from column names, their types and value sequences in that order."""
        return cls(names, types, [list(r) for r in rows])

    def has(self, name):
        return name in self._index

    def type_of(self, name):
        return self._types[self._index[name]]

    def __len__(self):
        return len(self._rows)

    def records(self):
        index = self._index
        for row in self._rows:
            yield Record(index, row)

    def filter(self, predicate):
        """New dataset holding the rows for which predicate(record) is True."""
        index = self._index
        kept = [row for row in self._rows if predicate(Record(index, row))]
        return Dataset(self._names, self._types, kept)

    def derive(self, name, value_type, compute):
        """New dataset with column `name` (added or replaced) = compute(record)."""
        index = self._index
        values = [compute(Record(index, row)) for row in self._rows]
        names = list(self._names)
        types = list(self._types)
        if name in index:
            pos = index[name]
            types[pos] = value_type
            rows = []
            for row, value in zip(self._rows, values):
                row = list(row)
                row[pos] = value
                rows.append(row)
        else:
            names.append(name)
            types.append(value_type)
            rows = [row + [value] for row, value in zip(self._rows, values)]
        return Dataset(names, types, rows)
