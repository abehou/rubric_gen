"""Strict YAML loading for current configuration files."""

from __future__ import annotations

import yaml


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Load safe YAML without silently overwriting mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("YAML mapping keys must be scalar") from exc
        if duplicate:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def load_yaml_strict(value: str) -> object:
    """Load safe YAML and reject duplicate mapping keys at every depth."""

    if type(value) is not str:
        raise TypeError("YAML input must be a string")
    return yaml.load(value, Loader=_UniqueKeySafeLoader)
