import time
from typing import Any
from collections.abc import KeysView


class NotInCacheException(Exception):
    pass



class PriorityCache:

    def __init__(self, size):
        """
        A class to store key - value assignments. For each key, a priority can be assigned, so values are only stored, when a higher priority is given.
        This can i.e. be used to store pixmaps, where the priority is the DPI scale, and buffered items must have at least a requestes DPI.
        When the buffer size is exceeded, the assignemnts with the oldest access timestamps are dropped.

        Args:
            size: int   The maximum buffer size
        """
        self._size          = size
        self._data          = {}
        self._priorities    = {}
        self._last_access   = {}


    @property
    def size(self) -> int:
        return self._size


    @size.setter
    def size(self, size: int):
        self._size = size
        self._enforce_buffer_size()


    def add(self, key: Any, value: Any, priority: Any) -> bool:
        """
        Add a key - value pair and assign a priority to the key.

        Args:
            key:        Any serializable object
            value:      Any serializable object
            priority:   Any sortable object, where for two objects (x, y), y has a higher priority iff x < y
        
        Returns:
            A bool indicating if a new entry was added to the buffer
        """
        if self.contains(key, priority):
            return False

        self._data[key]         = value
        self._priorities[key]   = priority
        self._last_access[key]  = time.time()
        self._enforce_buffer_size()
        return True


    def get(self, key: Any, min_priority: Any = None) -> Any:
        """
        Returns a value to a given key with an optional minimum priority

        Args:
            key:            Any serializable object
            min_priority:   Only return the value if it has at least this priority (optional, default: None)

        Returns:
            A serializable object assigned to the key
        """
        if key in self._data:
            if min_priority is None or self._priorities[key] >= min_priority:
                self._last_access[key] = time.time()
                return self._data[key]
        raise NotInCacheException("Key '{}' not found in cache!".format(key))
        

    def contains(self, key: Any, min_priority: Any = None) -> bool:
        """
        Tests if the buffer contains a key, optionally with a minimum priority

        Args:
            key:            Any serializable object
            min_priority:   Only return the value if it has at least this priority (optional, default: None)

        Returns:
            A bool indicating if the entry was found
        """
        return key in self._priorities and (min_priority is None or self._priorities[key] >= min_priority)
    
    
    def keys(self) -> KeysView[Any]:
        """
        Returns a set of all keys currently stored inside the cache.
        """
        return self._data.keys()


    def _enforce_buffer_size(self):
        if len(self._data) > self._size:
            keys_to_remove = sorted(self._last_access.keys(), key = lambda x: self._last_access[x])[:-self._size]
            for key in keys_to_remove:
                del self._data[key]
                del self._priorities[key]
                del self._last_access[key]