from collections.abc import Callable
from typing import Any, TypeVar

K = TypeVar('K')
V = TypeVar('V')


def sort_dict(
    dictionary: dict[K, V],
    key: Callable[[K], Any] | None = None,
    reverse: bool = False,
) -> dict[K, V]:
    """
    Sort a dictionary by keys and return a new sorted dictionary.
    """

    # FIXME: Typing the following line requires a full type hint for `key`.
    return {k: dictionary[k] for k in sorted(dictionary, key=key, reverse=reverse)}  # type: ignore


def sort_dict_by_key_order(dictionary: dict[K, V], key_order: list[K]) -> dict[K, V]:
    """
    Sort a dictionary based on a custom key order. Keys not in the key order go at the end in their
    original order.
    """

    order_indexes = {k: i for i, k in enumerate(key_order)}
    default_index = len(key_order)
    dict_keys = list(dictionary.keys())

    return sort_dict(dictionary, key=lambda k: (order_indexes.get(k, default_index), dict_keys.index(k)))
