import os
import json
from collections.abc import Iterator, ItemsView, KeysView, ValuesView
from src.config import AppSettings



class CaseNotFoundException(Exception):
    pass



class CaseStore:
    """
    A case store bridges the gap between relative file paths stored in a central Document Store and the location of referenced files within a local file system.
    If a shared file system is used, paths may be similar for each member. 
    When a database is shared, but each member has a local copy of the referenced files, the case root directories may vary for each member.
    When creating new cases, the according root directories are stored in the working directory as a JSON file.
    """

    def __init__(self):
        self._case_to_path      = {}
        self._case_root_file    = AppSettings().case_root_file

        # Read existing case root directories (Note: they are not validated!)
        if os.path.exists(self._case_root_file):
            with open(self._case_root_file, 'r') as f:
                case_to_path = json.load(f)
                for (case, root_dir) in case_to_path.items():
                    self._case_to_path[case] = root_dir


    def __getitem__(self, case: str) -> str:
        try:
            return self._case_to_path[case]
        except KeyError:
            raise CaseNotFoundException("Case '{}' not found!".format(case))


    def __setitem__(self, case: str, root_dir: str):
        self._case_to_path[case] = root_dir
        self._write_case_file()


    def __contains__(self, case: str) -> bool:
        return case in self._case_to_path


    def __delitem__(self, case: str):
        del self._case_to_path[case]


    def __len__(self) -> int:
        return len(self._case_to_path)
    

    def _write_case_file(self):
        with open(self._case_root_file, 'w') as f:
            json.dump(self._case_to_path, f)


    def __iter__(self) -> Iterator[str]:
        return iter(self._case_to_path)


    def items(self) -> ItemsView[str, str]:
        return self._case_to_path.items()


    def clear(self):
        self._case_to_path.clear()
        self._write_case_file()


    def keys(self) -> KeysView[str]:
        return self._case_to_path.keys()


    def values(self) -> ValuesView[str]:
        return self._case_to_path.values()