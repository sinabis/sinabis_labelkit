import datetime as dt
import json
import os
import tqdm
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from .case_store import CaseStore



class _NO_DOCTYPE:
    pass

NO_DOCTYPE = _NO_DOCTYPE()



class CaseNotFoundException(Exception):
    pass



class DuplicateException(Exception):
    pass



class EmptyUpdateException(Exception):
    pass



class IdentifierNotFoundException(Exception):
    pass



class InvalidIdentifierException(Exception):
    pass



class InvalidPageIntervalException(Exception):
    pass



class InvalidPageNumberException(Exception):
    pass



class UniquePageToDocumentAssignmentException(Exception):
    pass



class ExportException(Exception):
    pass



class ImportException(Exception):
    pass



class DocumentStore(ABC):

    def __init__(self):
        self._case_store = CaseStore()


    @abstractmethod
    def insert(self,
            case:       str,
            path:       str,
            pages:      int | list[int],
            identifier: int | None              = None,
            doctypes:   str | list[str] | None  = None,
            junk:       bool | None             = False
        ) -> int:
        """Insert a new document, optionally with a specific identifier. Returns the new document identifier."""
        raise NotImplementedError


    @abstractmethod
    def update(self,
            identifier: int,
            path:       str | None                              = None,
            pages:      int | list[int] | None                  = None,
            doctypes:   str | list[str] | _NO_DOCTYPE | None    = None,
            junk:       bool | None                             = None
        ) -> bool:
        """Insert or update a document. Returns if successfull."""
        raise NotImplementedError


    @abstractmethod
    def find(self,
            identifier:     int | None                                          = None,
            path:           str | None                                          = None,
            pages:          int | list[int] | None                              = None,
            cases:          str | list[str] | None                              = None,
            doctypes:       str | list[str | _NO_DOCTYPE] | _NO_DOCTYPE | None  = None,
            junk:           bool | None                                         = None,
            updated_since:  dt.datetime | None                                  = None
        ) -> list[dict[str, Any]]:
        """
        Find documents and - if not None - filter by identifier, path, pages, cases, doctype or if it has been updated since a given time.
        When providing multiple cases or doctypes they are accumulated with a logical OR.
        """
        raise NotImplementedError


    @abstractmethod
    def find_documents_in_page_range(self,
            case:       str,
            path:       str,
            page_min:   int,
            page_max:   int
        ) -> list[dict[str, Any]]:
        """Find docs where ANY page is in [page_min, page_max] (overlapping)"""
        raise NotImplementedError


    @abstractmethod
    def delete(self,
            identifier: int | None  = None,
            case:       str | None  = None
        ) -> int:
        """Delete all docs (no arguments), a doc with a specific identifier, or a whole case. Returns count deleted."""
        raise NotImplementedError


    @abstractmethod
    def count(self) -> int:
        """Counts the total number of documents"""
        raise NotImplementedError


    @abstractmethod
    def identifiers(self) -> list[int]:
        """Returns a list of all document identifiers"""
        raise NotImplementedError


    @abstractmethod
    def cases(self) -> list[str]:
        """Returns a sorted list of all case names"""
        raise NotImplementedError


    @abstractmethod
    def doctypes(self) -> list[str]:
        """Returns a sorted list of all doctypes"""
        raise NotImplementedError


    @property
    def case_store(self) -> CaseStore:
        return self._case_store


    def missing_case_paths(self) -> list[str]:
        """
        Checks the existence of case root directories and returns a list of cases where they are missing.
        Note: The existence of files within is NOT checked. Use missing_file_paths() for this purpose.

        Returns:
            A list of cases with missing paths
        """
        invalid = []
        for case in self.cases():
           if not case in self._case_store or not os.path.exists(self._case_store[case]):
               invalid.append(case)
        return invalid


    def missing_file_paths(self) -> dict[str, set]:
        """
        Checks the existence of all files and returns a dictionary of missing files, where cases are keys and sets of paths are values.
        """
        invalid = defaultdict(set)
        for doc in self.find():
            if doc['case'] in self._case_store:
                if os.path.exists(os.path.join(self._case_store[doc['case']], doc['path'])):
                    continue
            invalid[doc['case']].add(doc['path'])
        return dict(invalid)


    def export_documents(self, file_path: str):
        """
        Writes the store to a json file. Note that IDs are not part of the export data.

        Args:
            file_path:  A .json file path which is overriden when it already exists
        """

        if not isinstance(file_path, str) or not file_path.endswith('json'):
            raise ExportException("File path '{}' is not a JSON file!".format(file_path))

        base_dir, file_name = os.path.split(file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
        elif base_dir and not os.path.exists(base_dir):
            os.makedirs(base_dir)

        doc_data = self.find()
        for doc in doc_data:
            del doc['created_at']
            del doc['updated_at']
            del doc['identifier']

        case_data = {k: v for (k, v) in self._case_store.items()}

        export_data = {'documents':  doc_data, 'cases': case_data}
        with open(file_path, 'w', encoding = 'utf-8') as f:
            json.dump(export_data, f, default = str, indent = 2)


    def import_documents(self, file_path: str):
        """
        Loads a document store from a json file. Note that IDs are not part of the import data.

        Args:
            file_path:  A .json file containing the documents to load
        """
        if not os.path.exists(file_path):
            raise ImportException("File '{}' does not exist!".format(file_path))

        with open(file_path, 'r', encoding = 'utf-8') as f:
            import_data = json.load(f)

        for record in tqdm.tqdm(import_data['documents']):
            self.insert(**record)

        # Update existing case roots and add new ones
        for (k, v) in import_data['cases'].items():
            self._case_store[k] = v