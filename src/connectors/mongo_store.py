from .document_store import _NO_DOCTYPE, NO_DOCTYPE, CaseNotFoundException, DocumentStore, DuplicateException, EmptyUpdateException, IdentifierNotFoundException, InvalidIdentifierException, InvalidPageIntervalException, UniquePageToDocumentAssignmentException, InvalidPageNumberException

import datetime as dt
import pymongo as pm
from pymongo.errors import DuplicateKeyError
from src.config import DatabaseConfig
from typing import Any



class MongoStore(DocumentStore):

    def __init__(self, config: DatabaseConfig):
        super().__init__()
        client                      = pm.MongoClient(host = config.host, username = config.user, password = config.password, port = config.port)
        self._database              = client.get_database(config.name)
        self._collection            = self._database.get_collection('documents')
        self._counter_collection    = self._database.get_collection('counters')

        self._ensure_indices_array()


    def _ensure_indices_array(self):
        self._collection.create_index([("case", pm.ASCENDING), ("path", pm.ASCENDING), ("pages", pm.ASCENDING)], unique = True)


    def insert(self,
            case:       str,
            path:       str,
            pages:      int | list[int],
            identifier: int | None              = None,
            doctypes:   str | list[str] | None  = None,
            junk:       bool | None             = False
        ) -> int:

        # Ensure that automatically assigned _ids can always increment without duplication
        if identifier is None:
            identifier = self._increment_id()
        else:
            if not isinstance(identifier, (int, type(None))):
                raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))
            if identifier > self._highest_id():
                self._update_highest_id(identifier)

        if isinstance(pages, int):
            pages       = [pages]
        if pages is not None and (not len(pages) or min(pages) < 0):
            raise InvalidPageNumberException("Page number '{}' is invalid!".format(pages))

        if doctypes is None:
            doctypes    = []
        elif isinstance(doctypes, str):
            doctypes    = [doctypes]

        doc = {
            "case":         case,
            "path":         path,
            "pages":        sorted(pages),
            "doctypes":     sorted(doctypes),
            "junk":         junk,
            "created_at":   dt.datetime.now(),
            "updated_at":   dt.datetime.now()
        }
        if identifier is not None:
            doc["_id"] = identifier

        try:
            result = self._collection.insert_one(doc)
        except DuplicateKeyError as e:
            raise DuplicateException(str(e))

        return result.inserted_id


    def update(self,
            identifier: int,
            path:       str | None                              = None,
            pages:      int | list[int] | None                  = None,
            doctypes:   str | list[str] | _NO_DOCTYPE | None    = None,
            junk:       bool | None                             = None
        ) -> bool:

        if pages == path == doctypes == junk == None:
            raise EmptyUpdateException("One of pages, path, doctypes or junk must not be None")

        if not isinstance(identifier, int):
            raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))

        if isinstance(pages, int):
            pages       = sorted([pages])
        elif isinstance(pages, list):
            pages       = sorted(pages)

        if pages is not None and (not len(pages) or min(pages) < 0):
            raise InvalidPageNumberException("Page number '{}' is invalid!".format(pages))

        if doctypes == NO_DOCTYPE:
            doctypes    = []
        elif isinstance(doctypes, str):
            doctypes    = [doctypes]
        elif isinstance(doctypes, list):
            doctypes    = sorted(doctypes)

        try:
            query   = {"$set": {k:v for k, v in zip(['path', 'pages', 'doctypes', 'junk', 'updated_at'], [path, pages, doctypes, junk, dt.datetime.now()]) if v is not None}}
            result = self._collection.update_many({'_id': identifier}, query)
        except DuplicateKeyError:
            raise UniquePageToDocumentAssignmentException

        if result.matched_count == 0:
            raise IdentifierNotFoundException("ID not found!")

        return True


    def find(self,
            identifier:     int | None                                          = None,
            path:           str | None                                          = None,
            pages:          int | list[int] | None                              = None,
            cases:          str | list[str] | None                              = None,
            doctypes:       str | list[str | _NO_DOCTYPE] | _NO_DOCTYPE | None  = None,
            junk:           bool | None                                         = None,
            updated_since:  dt.datetime | None                                  = None
        ) -> list[dict[str, Any]]:

        if not isinstance(identifier, (int, type(None))):
            raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))

        query = {}

        if isinstance(identifier, int):
            query['_id']        = identifier

        if isinstance(path, str):
            query['path']       = path

        if isinstance(pages, list):
            query['pages']      = {'$all': pages}
        elif isinstance(pages, int):
            query['pages']      = pages

        if isinstance(cases, str):
            query['case']       = cases
        elif isinstance(cases, list):
            query['case']       = {'$in': cases}

        if isinstance(doctypes, str):
            query['doctypes']   = doctypes
        elif doctypes == NO_DOCTYPE:
            query['doctypes']   = {'$size': 0}
        elif isinstance(doctypes, list) and NO_DOCTYPE not in doctypes:
            query['doctypes']   = {'$in': doctypes}
        elif isinstance(doctypes, list) and NO_DOCTYPE in doctypes:
            query['$or']        = [{'doctypes': {'$in': list(set(doctypes) - set([NO_DOCTYPE]))}}, {'doctypes': {'$size': 0}}]

        if isinstance(junk, bool):
            query['junk']       = junk

        if isinstance(updated_since, dt.datetime):
            query['updated_at'] = {'$gt': updated_since}

        results = list(self._collection.find(query).sort(['case', 'path', 'pages']))

        for doc in results:
            doc['identifier'] = doc['_id']
            del doc['_id']

        return results


    def find_documents_in_page_range(self,
            case:       str,
            path:       str,
            page_min:   int,
            page_max:   int
        ) -> list[dict[str, Any]]:

        if page_min > page_max or min(page_min, page_max) < 0:
            raise InvalidPageIntervalException("[{}, {}] is an invalid Interval!".format(page_min, page_max))

        query = {
            "case": case,
            "path": path,
            "pages": {
                "$elemMatch": {"$gte": page_min, "$lte": page_max}
            }
        }
        results = list(self._collection.find(query).sort(['case', 'path', 'pages']))

        for doc in results:
            doc['identifier'] = doc['_id']
            del doc['_id']

        return results


    def delete(self,
            identifier: int | None  = None,
            case:       str | None  = None
        ) -> int:

        if not isinstance(identifier, (int, type(None))):
            raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))

        if identifier is not None and case is not None:
            raise ValueError("Cannot specify both `identifier` and `case`.")

        query   = {k:v for k, v in zip(['_id', 'case'], [identifier, case]) if v is not None}
        result  = self._collection.delete_many(query)

        if identifier is not None and result.deleted_count == 0:
            raise IdentifierNotFoundException("ID '{}' not found!".format(identifier))

        if case is not None and result.deleted_count == 0:
            raise CaseNotFoundException("Case '{}' not found!".format(case))

        return result.deleted_count


    def count(self) -> int:
        result = self._collection.count_documents({})
        if result is None:
            return 0
        return result


    def cases(self) -> list[str]:
        return sorted(self._collection.distinct('case'))


    def identifiers(self) -> list[int]:
        return self._collection.distinct('_id')


    def doctypes(self) -> list[str]:
        pipeline = [
            {"$unwind": "$doctypes"},
            {"$group": {"_id": "$doctypes"}},
            {"$sort": {"_id": 1}}
        ]
        return [doc["_id"] for doc in self._collection.aggregate(pipeline)]


    def _increment_id(self) -> int:
        """
        Increment the current ID counter by 1 and return it.

        Returns:
            The incremented ID
        """
        return self._counter_collection.find_one_and_update({}, {"$inc": {"max_id": 1}}, upsert = True, return_document = True)["max_id"]


    def _highest_id(self) -> int:
        """
        Returns the highest known ID, or -1 if no ID has been assigned yet.

        Returns:
            The highest ID
        """
        counter = self._counter_collection.find_one({})
        if counter is None:
            return -1
        return counter['max_id']


    def _update_highest_id(self, identifier: int):
        """
        Sets the highest ID.

        Args:
            identifier: The new highest ID
        """
        self._counter_collection.update_one({}, {'$set': {"max_id": identifier}}, upsert = True)
