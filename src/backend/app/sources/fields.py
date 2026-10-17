"""Conservative structural field identities; no mapping expressions are executed."""
import json
from collections import Counter, defaultdict

from .metadata import stable_id


def field_metadata(collection, records, batch_id):
    observed = defaultdict(set)
    # A string segment is an exact object key; None represents any array element.
    for header in collection.headers:
        observed[(header.key,)]
    for record in records:
        stack = [((), record)]
        while stack:
            path, value = stack.pop()
            if value is None:
                kind = None
            elif isinstance(value, bool):
                kind = 'boolean'
            elif isinstance(value, (int, float)):
                kind = 'number'
            elif isinstance(value, str):
                kind = 'string'
            elif isinstance(value, dict):
                kind = 'object'
                stack.extend((path + (key,), child) for key, child in value.items())
            else:
                kind = 'array'
                stack.extend((path + (None,), child) for child in value)
            if path:
                kinds = observed[path]
                if kind is not None:
                    kinds.add(kind)
    originals = Counter(header.original.strip() for header in collection.headers)
    roots = {h.key: h.original.strip() for h in collection.headers}
    result = []
    for path, kinds in observed.items():
        root = roots.get(path[0], path[0])
        matchable = not collection.headers or bool(root) and originals[root] == 1
        # Unique headings use their original spelling, not a generated collision suffix.
        identity_path = (root,) + path[1:]
        identity = json.dumps(identity_path, ensure_ascii=True)
        result.append(dict(field_id=stable_id('fld', collection.collection_id, identity,
                                             '' if matchable else batch_id, '' if matchable else str(path[0])),
                           path=list(path), kinds=sorted(kinds), matchable=matchable))
    return result
