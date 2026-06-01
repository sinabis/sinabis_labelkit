import src.connectors as connectors
from datetime import datetime as dt
import json
import os
import pytest
import time
from typing import Any
from .helpers import normalize_doc



SLEEP_TIME      = 0.001

KEYS_TO_RETURN  = set(['case', 'path', 'pages', 'doctypes', 'updated_at', 'created_at', 'identifier', 'junk'])
KEYS_TO_COMPARE = set(['case', 'path', 'pages', 'doctypes', 'junk'])

RAW_TEST_DOCS   = [
    {'case': 'caseA', 'path': 'files/file_1.pdf', 'pages': [5, 6, 4], 'doctypes': 'vermerk', 'junk': False},
    {'case': 'caseA', 'path': 'files/file_1.pdf', 'pages': [0, 1, 2, 3], 'doctypes': 'anfrage'},
    {'case': 'caseA', 'path': 'files/file_1.pdf', 'pages': 7, 'doctypes': None},
    {'case': 'caseA', 'path': 'files/file_2.pdf', 'pages': [0, 1, 2, 4], 'doctypes': 'chat'},
    {'case': 'caseA', 'path': 'files/file_2.pdf', 'pages': [6, 7, 8], 'doctypes': 'verfügung'},
    {'case': 'caseA', 'path': 'files/file_2.pdf', 'pages': [9, 10], 'doctypes': ['regelwerk', 'fax']},
    {'case': 'caseA', 'path': 'files/file_2.pdf', 'pages': [11, 12, 13, 14], 'doctypes': ['urteil', 'verfügung'], 'junk': True},
    {'case': 'caseB', 'path': 'files/file_1.pdf', 'pages': [0], 'doctypes': 'fax'},
    {'case': 'caseB', 'path': 'files/file_1.pdf', 'pages': [1, 2], 'doctypes': ['fax', 'verfügung', 'chat'], 'junk': True},
    {'case': 'caseB', 'path': 'files/file_1.pdf', 'pages': [3, 4, 5, 7], 'doctypes': None},
    {'case': 'caseC', 'path': 'strange_path with blank.pdf', 'pages': [0, 1, 2, 3, 4, 5], 'doctypes': 'beschluss'},
    {'case': 'caseC', 'path': 'strange_path with blank 2.pdf', 'pages': [0, 1, 2], 'doctypes': 'beschluss'},
    {'case': 'caseC', 'path': 'strange_path with blank 2.pdf', 'pages': [3, 4, 5], 'doctypes': None},
    {'case': 'caseC', 'path': 'strange_path with blank 2.pdf', 'pages': [6, 7, 9], 'doctypes': 'fax'},
]



@pytest.fixture(scope = "module")
def normalized_test_docs() -> list[dict[str, Any]]:
    docs_normalized = [normalize_doc(d) for d in RAW_TEST_DOCS]
    return list(sorted(docs_normalized, key = lambda x: (x['case'], x['path'], min(x['pages']))))


@pytest.fixture
def initial_test_docs() -> list[dict[str, Any]]:
    return RAW_TEST_DOCS



class TestInsert:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_insert_normal(self, store, normalized_test_docs):
        assert store.count() == len(normalized_test_docs)


    def test_insert_with_id(self, store):
        special_id      = 1234
        special_id_doc  = {'case': 'caseY', 'path': 'special_path.pdf', 'pages': [1, 2, 3], 'doctypes': None}
        special_doc_n   = normalize_doc(special_id_doc)
        result          = store.insert(identifier = special_id, **special_id_doc)
        assert result == special_id
        docs_ret        = store.find(identifier = special_id)
        assert len(docs_ret) == 1
        for key in KEYS_TO_COMPARE:
            assert special_doc_n[key] == docs_ret[0][key]


    def test_insert_with_unavailable_id(self, store):
        first_id_doc    = store.find()[0]['identifier']
        fantasy_doc     = {'case': 'caseZ', 'path': 'fantasy_path.pdf', 'pages': 0}
        with pytest.raises(connectors.DuplicateException):
            store.insert(identifier = first_id_doc, **fantasy_doc)


    def test_insert_with_invalid_id(self, store):
        forbidden_doc  = {'case': 'caseO', 'path': 'special_path.pdf', 'pages': [1, 2, 3], 'doctypes': None}
        for new_id in ['1002', 'test', 12.2]:
            with pytest.raises(connectors.InvalidIdentifierException):
                store.insert(identifier = new_id, **forbidden_doc)


    def test_insert_invalid_page_numbers(self, store):
        for invalid_numbers in [[-2, -1], [], -1]:
            invalid_doc = {'case': 'caseA', 'path': 'files/file_1.pdf', 'pages': invalid_numbers, 'doctypes': 'vermerk'}
            with pytest.raises(connectors.InvalidPageNumberException):
                store.insert(**invalid_doc)


    def test_double_insert(self, store, normalized_test_docs):
        with pytest.raises(connectors.DuplicateException):
            store.insert(**normalized_test_docs[0])



class TestFind:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_find_all(self, store, normalized_test_docs):
        """
        # 1) all documents are returned
        # 2) contain all necessary keys
        # 3) keys have correct values
        # 4) are in the correct order
        # 5) pages and doctypes are sorted lists
        """
        results = store.find()
        assert len(results) == len(normalized_test_docs)
        for (doc_ret, doc_gt) in zip(results, normalized_test_docs):
            assert doc_ret.keys() == KEYS_TO_RETURN
            for key in KEYS_TO_COMPARE:
                assert doc_ret[key] == doc_gt[key]


    def test_find_by_invalid_id(self, store):
        for id_ in [3.5, "2"]:
            with pytest.raises(connectors.InvalidIdentifierException):
                store.find(identifier = id_)


    def test_find_by_id(self, store):
        search_id   = store.find()[1]['identifier']
        results     = store.find(identifier = search_id)
        assert len(results) == 1
        assert results[0]['identifier'] == search_id
        assert results[0].keys() == KEYS_TO_RETURN


    def test_find_junk(self, store, normalized_test_docs):
        results = store.find(junk = True)
        filtered_docs = list(filter(lambda x: x['junk'], normalized_test_docs))
        assert len(results) == len(filtered_docs)
        for (doc_ret, doc_gt) in zip(results, filtered_docs):
            for key in KEYS_TO_COMPARE:
                assert doc_ret[key] == doc_gt[key]


    def find_not_junk(self, store):
        results = store.find(junk = False)
        filtered_docs = list(filter(lambda x: not x['junk'], normalized_test_docs))
        assert len(results) == len(filtered_docs)
        for (doc_ret, doc_gt) in zip(results, filtered_docs):
            for key in KEYS_TO_COMPARE:
                assert doc_ret[key] == doc_gt[key]


    def test_find_by_case(self, store, normalized_test_docs):
        for search_case in ["caseA", ["caseA"], ["caseB", "caseC"]]:
            results     = store.find(cases = search_case)
            if isinstance(search_case, str):
                docs_gt = list(filter(lambda x: x['case'] == search_case, normalized_test_docs))
            else:
                docs_gt = list(filter(lambda x: x['case'] in set(search_case), normalized_test_docs))
            assert len(results) == len(docs_gt)
            for (doc_ret, doc_gt) in zip(results, docs_gt):
                for key in KEYS_TO_COMPARE:
                    assert doc_ret[key] == doc_gt[key]


    def test_find_by_path(self, store, normalized_test_docs):
        search_path = "files/file_1.pdf"
        results     = store.find(path = search_path)
        docs_gt     = list(filter(lambda x: x['path'] == search_path, normalized_test_docs))
        assert len(results) == len(docs_gt)
        for (doc_ret, doc_gt) in zip(results, docs_gt):
            for key in KEYS_TO_COMPARE:
                assert doc_ret[key] == doc_gt[key]


    def test_find_by_page(self, store, normalized_test_docs):
        for search_page in [0, [0], [4, 1]]:
            results     = store.find(pages = search_page)
            if isinstance(search_page, int):
                docs_gt = list(filter(lambda x: search_page in x['pages'], normalized_test_docs))
            else:
                docs_gt = list(filter(lambda x: set(search_page).issubset(set(x['pages'])), normalized_test_docs))
            assert len(results) == len(docs_gt)
            for (doc_ret, doc_gt) in zip(results, docs_gt):
                for key in KEYS_TO_COMPARE:
                    assert doc_ret[key] == doc_gt[key]


    def test_find_by_path_and_page(self, store, normalized_test_docs):
        search_path = "files/file_1.pdf"
        for search_page in [0, [0], [3, 2]]:
            results     = store.find(pages = search_page, path = search_path)
            if isinstance(search_page, int):
                docs_gt = list(filter(lambda x: search_path == x['path'] and search_page in x['pages'], normalized_test_docs))
            else:
                docs_gt = list(filter(lambda x: search_path == x['path'] and set(search_page).issubset(set(x['pages'])), normalized_test_docs))
            assert len(results) == len(docs_gt)
            for (doc_ret, doc_gt) in zip(results, docs_gt):
                for key in KEYS_TO_COMPARE:
                    assert doc_ret[key] == doc_gt[key]


    def test_find_by_doctype(self, store, normalized_test_docs):
        for search_doctype in ['chat', ['fax'], ['fax', 'chat'], connectors.NO_DOCTYPE, [connectors.NO_DOCTYPE, 'fax']]:
            results = store.find(doctypes = search_doctype)
            if isinstance(search_doctype, str):
                docs_gt = list(filter(lambda x: search_doctype in x['doctypes'], normalized_test_docs))
            elif search_doctype == connectors.NO_DOCTYPE:
                docs_gt = list(filter(lambda x: [] == x['doctypes'], normalized_test_docs))
            else:
                docs_gt = []
                for doc in normalized_test_docs:
                    if (set(search_doctype) - set([connectors.NO_DOCTYPE])) & set(doc['doctypes']):
                        docs_gt.append(doc)
                    elif connectors.NO_DOCTYPE in search_doctype and doc['doctypes'] == []:
                        docs_gt.append(doc)
            assert len(results) == len(docs_gt)
            for (doc_ret, doc_gt) in zip(results, docs_gt):
                for key in KEYS_TO_COMPARE:
                    assert doc_ret[key] == doc_gt[key]


    def test_find_by_doctype_and_case(self, store, normalized_test_docs):
        search_case = "caseB"
        for search_doctype in ['chat', ['fax'], ['fax', 'chat']]:
            results = store.find(doctypes = search_doctype, cases = search_case)
            if isinstance(search_doctype, str):
                docs_gt = list(filter(lambda x: x['case'] == search_case and search_doctype in x['doctypes'], normalized_test_docs))
            else:
                docs_gt = list(filter(lambda x: x['case'] == search_case and set(search_doctype) & set(x['doctypes']), normalized_test_docs))
            assert len(results) == len(docs_gt)
            for (doc_ret, doc_gt) in zip(results, docs_gt):
                for key in KEYS_TO_COMPARE:
                    assert doc_ret[key] == doc_gt[key]


    def test_find_updated_after(self, store):
        time_before = dt.now()
        time.sleep(SLEEP_TIME)
        new_doc     = {'case': 'caseY', 'path': 'special_path.pdf', 'pages': [1, 2, 3], 'doctypes': None}
        store.insert(**new_doc)
        new_doc_n   = normalize_doc(new_doc)
        results     = store.find(updated_since = time_before)
        assert len(results) == 1
        for key in KEYS_TO_COMPARE:
            assert results[0][key] == new_doc_n[key]


    def test_find_range(self, store, normalized_test_docs):
        search_case = 'caseA'
        search_path = 'files/file_1.pdf'
        for (page_min, page_max) in [(2, 7), (1, 3), (0, 0), (0, 6), (3, 4), (1000, 2000)]:
            results = store.find_documents_in_page_range(case = search_case, path = search_path, page_min = page_min, page_max = page_max)
            docs_gt = list(filter( \
                lambda x: x['path'] == search_path \
                    and x['case'] == search_case \
                    and (page_min <= max(x['pages']) <= page_max or page_min <= min(x['pages']) <= page_max) \
                        , normalized_test_docs \
            ))
            assert len(results) == len(docs_gt)
            for (doc_ret, doc_gt) in zip(results, docs_gt):
                for key in KEYS_TO_COMPARE:
                    assert doc_ret[key] == doc_gt[key]


    def test_find_invalid_range(self, store):
        search_case = 'caseA'
        search_path = "files/file_1.pdf"
        for (page_min, page_max) in [(3, 1), (-4, -2)]:
            with pytest.raises(connectors.InvalidPageIntervalException):
                store.find_documents_in_page_range(case = search_case, path = search_path, page_min = page_min, page_max = page_max)



class TestUpdate:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_update_junk(self, store):
        doc_before  = store.find(junk = False)[0]
        success     = store.update(doc_before['identifier'], junk = True)
        assert success
        doc_after   = store.find(doc_before['identifier'])[0]
        for key in KEYS_TO_COMPARE - set(['junk']):
            assert doc_before[key] == doc_after[key]
        assert doc_after['junk'] != doc_before['junk']


    def test_update_not_junk(self, store):
        doc_before  = store.find(junk = True)[0]
        success     = store.update(doc_before['identifier'], junk = False)
        assert success
        doc_after   = store.find(doc_before['identifier'])[0]
        for key in KEYS_TO_COMPARE - set(['junk']):
            assert doc_before[key] == doc_after[key]
        assert doc_after['junk'] != doc_before['junk']


    def test_update_doctype(self, store):
        time_before = dt.now()
        time.sleep(SLEEP_TIME)
        doc_id_to_change    = store.find()[0]['identifier']
        for new_doctype in ['verfügung', ['fax', 'chat', 'bewerbung'], connectors.NO_DOCTYPE]:
            success         = store.update(doc_id_to_change, doctypes = new_doctype)
            assert success
            doctype_after   = store.find(identifier = doc_id_to_change)[0]['doctypes']
            assert doctype_after == sorted(new_doctype) if isinstance(new_doctype, list) else [new_doctype]
        assert len(store.find(updated_since = time_before)) == 1


    def test_update_path(self, store):
        new_path            = 'files/replaced-path.pdf'
        doc_id_to_change    = store.find()[0]['identifier']
        success             = store.update(doc_id_to_change, path = new_path)
        assert success
        set_path            = store.find(identifier = doc_id_to_change)[0]['path']
        assert set_path == new_path


    def test_update_pages(self, store):
        new_pages           = [100000, 100001, 100003]
        doc_id_to_change    = store.find()[0]['identifier']
        for new_pages in [100000, [100000], [200000, 200001, 200004]]:
            success         = store.update(doc_id_to_change, pages = new_pages)
            assert success
            set_doc         = store.find(identifier = doc_id_to_change)[0]
            assert set_doc['pages'] == new_pages if isinstance(new_pages, list) else [new_pages]


    def test_update_to_known_path_and_free_pages(self, store):
        new_path            = 'files/file_2.pdf'
        new_pages           = [100000, 100001, 100003]
        doc_id_to_change    = store.find()[0]['identifier']
        success             = store.update(doc_id_to_change, path = new_path, pages = new_pages)
        assert success
        set_doc             = store.find(identifier = doc_id_to_change)[0]
        assert set_doc['path'] == new_path and set_doc['pages'] == new_pages


    def test_update_path_invalid(self, store):
        new_path            = 'files/file_2.pdf'
        doc_id_to_change    = store.find()[0]['identifier']
        with pytest.raises(connectors.UniquePageToDocumentAssignmentException):
            store.update(doc_id_to_change, path = new_path)


    def test_update_to_known_path_and_used_pages(self, store):
        doc_id_to_change    = store.find(cases = 'caseB')[0]['identifier']
        for new_pages in ([1, [6, 7, 8]]):
            with pytest.raises(connectors.UniquePageToDocumentAssignmentException):
                store.update(doc_id_to_change, pages = new_pages)


    def test_update_invalid_page_numbers(self, store):
        doc_id_to_change    = store.find()[0]['identifier']
        for invalid_pages in [[-2, -1], [], -1]:
            with pytest.raises(connectors.InvalidPageNumberException):
                store.update(doc_id_to_change, pages = invalid_pages)


    def test_update_empty(self, store):
        with pytest.raises(connectors.EmptyUpdateException):
            store.update(store.find()[0]['identifier'])


    def test_update_invalid_id_type(self, store):
        for id_ in [None, "NOT Valid!", 3.621]:
            with pytest.raises(connectors.InvalidIdentifierException):
                store.update(id_, doctypes = 'vertrag')


    def test_update_unavailable_id(self, store):
        unavailable_id = 999999
        with pytest.raises(connectors.IdentifierNotFoundException):
            store.update(unavailable_id, doctypes = 'vertrag')



class TestDelete:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_delete_by_id(self, store, normalized_test_docs):
        docs                = store.find()
        doc_id_to_delete    = docs[0]['identifier']
        result              = store.delete(identifier = doc_id_to_delete)
        assert result == 1
        ids_after           = store.identifiers()
        assert doc_id_to_delete not in ids_after
        assert len(ids_after) == len(normalized_test_docs) - 1
        id_doctypes         = set(docs[0]['doctypes'])
        non_id_doctypes     = set.union(*[set(x['doctypes']) for x in docs[1:]])
        all_doctypes        = set.union(*[set(x['doctypes']) for x in normalized_test_docs])
        deleted_doctypes    = id_doctypes - non_id_doctypes
        assert set(store.doctypes()) == all_doctypes - deleted_doctypes


    def test_delete_by_case(self, store, normalized_test_docs):
        case_to_delete      = 'caseC'
        result              = store.delete(case = case_to_delete)
        matching_docs       = list(filter(lambda x: x['case'] == case_to_delete, normalized_test_docs))
        non_matching_docs   = list(filter(lambda x: x['case'] != case_to_delete, normalized_test_docs))
        current_docs        = store.find()
        assert len(matching_docs) == result
        assert len(matching_docs) == len(normalized_test_docs) - len(current_docs)
        case_doctypes       = set.union(*[set(x['doctypes']) for x in matching_docs])
        non_case_doctypes   = set.union(*[set(x['doctypes']) for x in non_matching_docs])
        all_doctypes        = set.union(*[set(x['doctypes']) for x in normalized_test_docs])
        deleted_doctypes    = case_doctypes - non_case_doctypes
        assert set(store.doctypes()) == all_doctypes - deleted_doctypes


    def test_delete_all(self, store, normalized_test_docs):
        result  = store.delete()
        assert result == len(normalized_test_docs)
        assert not store.identifiers()
        assert not store.cases()
        assert not store.doctypes()
        assert not store.count()


    def test_by_unavailable_case(self, store):
        unavailable_case = "non-existing-case"
        with pytest.raises(connectors.CaseNotFoundException):
            store.delete(case = unavailable_case)


    def test_delete_by_id_invalid_format(self, store):
        for id_ in ["123", 3.621, ['mööp']]:
            with pytest.raises(connectors.InvalidIdentifierException):
                store.delete(identifier = id_)


    def test_delete_by_unavailable_id(self, store):
        unavailable_id = 918765267
        with pytest.raises(connectors.IdentifierNotFoundException):
            store.delete(identifier = unavailable_id)



class TestIdentifiers:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_identifiers(self, store):
        identifiers         = store.identifiers()
        find_identifiers    = store.find()
        assert set(identifiers) == set([x['identifier'] for x in find_identifiers])



class TestCases:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_cases(self, store, normalized_test_docs):
        cases_ret   = store.cases()
        cases_gt    = set(map(lambda x: x['case'], normalized_test_docs))
        assert set(cases_ret) == set(cases_gt)



class TestDoctypes:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_doctypes(self, store, normalized_test_docs):
        doctypes_ret    = store.doctypes()
        doctypes_gt     = set([doctype for x in normalized_test_docs for doctype in x['doctypes']])
        assert set(doctypes_ret) == set(doctypes_gt)



class TestExport:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_export(self, store, normalized_test_docs):
        dump_file   = "tmp/dump-temp.json"
        store.export_documents(dump_file)
        assert os.path.exists(dump_file)
        assert os.path.getsize(dump_file)

        with open(dump_file, 'r') as f:
            data = json.load(f)
            assert 'documents' in data and 'cases' in data
            docs    = data['documents']
            for doc_res, doc_gt in zip(docs, normalized_test_docs):
                assert doc_res.keys() == doc_gt.keys() == KEYS_TO_COMPARE
                for key in KEYS_TO_COMPARE:
                    assert doc_res[key] == doc_gt[key]
        os.remove(dump_file)


    def test_export_invalid_path(self, store):
        for invalid_export_name in ['dump_file', None, 152]:
            with pytest.raises(connectors.ExportException):
                store.export_documents(invalid_export_name)



class TestImport:

    @pytest.fixture(autouse = True)
    def setup(self):
        pass


    def test_import(self, store, normalized_test_docs):
        dump_file   = "tmp/dump-temp.json"
        with open(dump_file, 'w') as f:
            dump_data = {'documents': normalized_test_docs, 'cases': {}}
            json.dump(dump_data, f)
        store.import_documents(dump_file)
        docs_res = store.find()
        for doc_res, doc_gt in zip(docs_res, normalized_test_docs):
            for key in KEYS_TO_COMPARE:
                assert doc_res[key] == doc_gt[key]
        os.remove(dump_file)


    def test_double_import(self, store, normalized_test_docs):
        dump_file   = "tmp/dump-temp.json"
        with open(dump_file, 'w') as f:
            dump_data = {'documents': normalized_test_docs, 'cases': {}}
            json.dump(dump_data, f)
        store.import_documents(dump_file)
        with pytest.raises(connectors.DuplicateException):
            store.import_documents(dump_file)
        os.remove(dump_file)


    def test_import_invalid_path(self, store):
        invalid_path = "/path/that/does/not/exist.json"
        with pytest.raises(connectors.ImportException):
            store.import_documents(invalid_path)