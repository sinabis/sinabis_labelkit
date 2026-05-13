from typing import Any
import src.actions as actions
import src.connectors as connectors
import pytest
from .helpers import normalize_doc



KEYS_TO_COMPARE = set(['case', 'path', 'pages', 'doctypes', 'junk'])

RAW_TEST_DOCS   = [
    {'identifier': 1, 'case': 'A', 'path': 'f1.pdf', 'pages': [0, 1, 2, 3], 'doctypes': ['fax']},
    {'identifier': 2, 'case': 'A', 'path': 'f1.pdf', 'pages': [4, 5, 6, 7], 'doctypes': ['fax']},
    {'identifier': 3, 'case': 'A', 'path': 'f1.pdf', 'pages': [8, 9, 10, 11], 'doctypes': ['fax']},
    {'identifier': 4, 'case': 'A', 'path': 'f2.pdf', 'pages': [0], 'doctypes': ['chat']},
    {'identifier': 5, 'case': 'A', 'path': 'f2.pdf', 'pages': [1, 2, 3], 'doctypes': ['email']},
    {'identifier': 6, 'case': 'A', 'path': 'f2.pdf', 'pages': [4, 5, 6, 7], 'doctypes': ['regelwerk', 'fax']},
    {'identifier': 7, 'case': 'B', 'path': 'f1.pdf', 'pages': [0, 1, 2, 3, 4], 'doctypes': ['urteil', 'verfügung']},
    {'identifier': 8, 'case': 'B', 'path': 'f1.pdf', 'pages': [5, 6], 'doctypes': ['fax']},
    {'identifier': 9, 'case': 'B', 'path': 'f1.pdf', 'pages': [7, 8], 'doctypes': ['fax', 'verfügung', 'chat']},
    {'identifier': 10, 'case': 'B', 'path': 'f2.pdf', 'pages': [0, 1, 2, 3], 'doctypes': ['email']},
    {'identifier': 11, 'case': 'B', 'path': 'f2.pdf', 'pages': [4, 5, 6, 7], 'doctypes': ['beschluss'], 'junk': True},
    {'identifier': 12, 'case': 'B', 'path': 'f2.pdf', 'pages': [8, 9, 10], 'doctypes': ['beschluss'], 'junk': True},
    {'identifier': 13, 'case': 'B', 'path': 'f2.pdf', 'pages': [11, 12, 13, 14], 'doctypes': ['beschluss'], 'junk': False},
    {'identifier': 14, 'case': 'B', 'path': 'f2.pdf', 'pages': [15, 16, 17], 'doctypes': [], 'junk': False},
]



@pytest.fixture(scope = "module")
def normalized_test_docs() -> list[dict[str, Any]]:
    docs_normalized = [normalize_doc(d) for d in RAW_TEST_DOCS]
    return list(sorted(docs_normalized, key = lambda x: (x['case'], x['path'], min(x['pages']))))


@pytest.fixture(scope = "module")
def id_to_doc(normalized_test_docs) -> dict[int, dict[str, Any]]:
    return {doc['identifier']: doc for doc in normalized_test_docs}


@pytest.fixture
def initial_test_docs() -> list[dict[str, Any]]:
    return RAW_TEST_DOCS


@pytest.fixture
def action_manager() -> actions.ActionManager:
    return actions.ActionManager()



class TestMerge:
    
    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_merge(self, store, action_manager, id_to_doc):
        docs_to_merge   = (1, 2)
        doc_1           = id_to_doc[docs_to_merge[0]]
        doc_2           = id_to_doc[docs_to_merge[1]]
        action_manager.do(actions.MergeAction(store, *docs_to_merge))
        all_ids         = set(store.identifiers())
        new_docs        = [store.find(identifier = id_)[0] for id_ in all_ids - id_to_doc.keys()]
        assert len(new_docs)        == 1
        for key in KEYS_TO_COMPARE - set(['pages']):
            assert new_docs[0][key] == doc_1[key]
        assert new_docs[0]['pages'] == sorted(set(doc_1['pages']).union(set(doc_2['pages'])))
        assert new_docs[0]['identifier'] not in id_to_doc
        assert not set(docs_to_merge).intersection(all_ids)


    def test_merge_undo(self, store, action_manager, normalized_test_docs):
        docs_to_merge   = (1, 2)
        action_manager.do(actions.MergeAction(store, *docs_to_merge))
        action_manager.undo()
        result_docs     = store.find()
        assert len(normalized_test_docs) == len(result_docs)
        for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
            for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                assert doc_bef[key] == doc_after[key]


    def test_merge_undo_redo(self, store, action_manager, id_to_doc):
        docs_to_merge   = (1, 2)
        doc_1           = id_to_doc[docs_to_merge[0]]
        doc_2           = id_to_doc[docs_to_merge[1]]
        action_manager.do(actions.MergeAction(store, *docs_to_merge))
        action_manager.undo()
        action_manager.redo()
        all_ids         = set(store.identifiers())
        new_docs        = [store.find(identifier = id_)[0] for id_ in all_ids - id_to_doc.keys()]
        assert len(new_docs)        == 1
        for key in KEYS_TO_COMPARE - set(['pages']):
            assert new_docs[0][key] == doc_1[key]
        assert new_docs[0]['pages'] == sorted(set(doc_1['pages']).union(set(doc_2['pages'])))
        assert new_docs[0]['identifier'] not in id_to_doc
        assert not set(docs_to_merge).intersection(all_ids)


    def test_merge_different_cases(self, store, action_manager):
        with pytest.raises(actions.MergeException):
            action_manager.do(actions.MergeAction(store, 10, 2))


    def test_merge_different_paths(self, store, action_manager):
        with pytest.raises(actions.MergeException):
            action_manager.do(actions.MergeAction(store, 5, 2))


    def test_merge_different_doctypes(self, store, action_manager):
        with pytest.raises(actions.MergeException):
            action_manager.do(actions.MergeAction(store, 10, 11))


    def test_merge_different_junk_values(self, store, action_manager):
        with pytest.raises(actions.MergeException):
            action_manager.do(actions.MergeAction(store, 12, 13))


    def test_merge_invalid_id(self, store, action_manager):
        for id_ in [None, 3.5]:
            with pytest.raises(connectors.InvalidIdentifierException):
                action_manager.do(actions.MergeAction(store, 10, id_))


    def test_merge_unavailable_id(self, store, action_manager):
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager.do(actions.MergeAction(store, 10, 999))



class TestCluster:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)

    def test_cluster(self, store, action_manager, id_to_doc):
        doc_id_to_cluster   = 7
        org_doc             = id_to_doc[doc_id_to_cluster] 
        for cluster_pages in [[0, 1, 2], [2, 3], [2, 3, 4], [0, 1, 2, 3, 4], [4, 2, 3], [1]]:
            action_manager.do(actions.ClusterAction(store, doc_id_to_cluster, cluster_pages))
            all_ids             = set(store.identifiers())
            new_docs            = list(filter(lambda x: x['identifier'] not in id_to_doc, store.find()))
            exp_before_range    = sorted(filter(lambda x: x < min(cluster_pages), org_doc['pages']))
            exp_cluster_range   = sorted(cluster_pages)
            exp_after_range     = sorted(filter(lambda x: x > max(cluster_pages), org_doc['pages']))
            exp_no_new_docs     = bool(exp_before_range) + bool(exp_cluster_range) + bool(exp_after_range)
            assert len(new_docs) == exp_no_new_docs
            for doc in new_docs:
                assert doc['identifier'] not in id_to_doc
                for key in KEYS_TO_COMPARE - set(['pages']):
                    assert doc[key] == org_doc[key]
            assert not doc_id_to_cluster in all_ids
            i = 0
            for expected in [exp_before_range, exp_cluster_range, exp_after_range]:
                if expected:
                    assert new_docs[i]['pages'] == expected
                    i += 1
            action_manager.undo()


    def test_cluster_undo(self, store, action_manager, normalized_test_docs):
        doc_id_to_cluster   = 7
        for cluster_pages in [[0, 1, 2], [2, 3], [2, 3, 4], [0, 1, 2, 3, 4], [4, 2, 3], [1]]:
            action_manager.do(actions.ClusterAction(store, doc_id_to_cluster, cluster_pages))
            action_manager.undo()
            result_docs     = store.find()
            assert len(normalized_test_docs) == len(result_docs)
            for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
                for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                    assert doc_bef[key] == doc_after[key]


    def test_cluster_undo_redo(self, store, action_manager, id_to_doc):
        doc_id_to_cluster   = 7
        org_doc             = id_to_doc[doc_id_to_cluster] 
        for cluster_pages in [[0, 1, 2], [2, 3], [2, 3, 4], [0, 1, 2, 3, 4], [4, 2, 3], [1]]:
            action_manager.do(actions.ClusterAction(store, doc_id_to_cluster, cluster_pages))
            action_manager.undo()
            action_manager.redo()
            all_ids             = set(store.identifiers())
            new_docs            = list(filter(lambda x: x['identifier'] not in id_to_doc, store.find()))
            exp_before_range    = sorted(filter(lambda x: x < min(cluster_pages), org_doc['pages']))
            exp_cluster_range   = sorted(cluster_pages)
            exp_after_range     = sorted(filter(lambda x: x > max(cluster_pages), org_doc['pages']))
            exp_no_new_docs     = bool(exp_before_range) + bool(exp_cluster_range) + bool(exp_after_range)
            assert len(new_docs) == exp_no_new_docs
            for doc in new_docs:
                assert doc['identifier'] not in id_to_doc
                for key in KEYS_TO_COMPARE - set(['pages']):
                    assert doc[key] == org_doc[key]
            assert not doc_id_to_cluster in all_ids
            i = 0
            for expected in [exp_before_range, exp_cluster_range, exp_after_range]:
                if expected:
                    assert new_docs[i]['pages'] == expected
                    i += 1
            action_manager.undo()


    def test_cluster_with_gaps(self, store, action_manager):
        with pytest.raises(actions.ClusterException):
            action_manager.do(actions.ClusterAction(store, 10, [1, 3]))


    def test_cluster_empty_split_pages(self, store, action_manager):
        with pytest.raises(actions.ClusterException):
            action_manager.do(actions.ClusterAction(store, 10, []))


    def test_cluster_invalid_id(self, store, action_manager):
        for id_ in [None, 3.5]:
            with pytest.raises(connectors.InvalidIdentifierException):
                action_manager.do(actions.ClusterAction(store, id_, [1, 2, 3]))


    def test_cluster_unavailable_id(self, store, action_manager):
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager.do(actions.ClusterAction(store, 99, [1, 2, 3]))



class TestSplit:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_split(self, store, action_manager, id_to_doc):
        doc_id_to_split = 1
        doc_to_split    = id_to_doc[doc_id_to_split]
        split_after     = 1
        action_manager.do(actions.SplitAction(store, doc_id_to_split, split_after))
        all_ids         = set(store.identifiers())
        new_docs        = list(filter(lambda x: x['identifier'] not in id_to_doc, store.find()))
        assert len(new_docs)        == 2
        for doc in new_docs:
            for key in KEYS_TO_COMPARE - set(['pages']):
                assert doc[key] == doc_to_split[key]
        assert new_docs[0]['pages'] == sorted(filter(lambda x: x <= split_after, doc_to_split['pages']))
        assert new_docs[1]['pages'] == sorted(filter(lambda x: x > split_after, doc_to_split['pages']))
        assert new_docs[0]['identifier'] not in id_to_doc
        assert new_docs[1]['identifier'] not in id_to_doc
        assert not doc_id_to_split in all_ids


    def test_split_undo(self, store, action_manager, normalized_test_docs):
        doc_id_to_split = 1
        split_after     = 1
        action_manager.do(actions.SplitAction(store, doc_id_to_split, split_after))
        action_manager.undo()
        result_docs     = store.find()
        assert len(normalized_test_docs) == len(result_docs)
        for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
            for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                assert doc_bef[key] == doc_after[key]


    def test_split_undo_redo(self, store, action_manager, id_to_doc):
        doc_id_to_split = 1
        doc_to_split    = id_to_doc[doc_id_to_split]
        split_after     = 1
        action_manager.do(actions.SplitAction(store, doc_id_to_split, split_after))
        action_manager.undo()
        action_manager.redo()
        all_ids         = set(store.identifiers())
        new_docs        = list(filter(lambda x: x['identifier'] not in id_to_doc, store.find()))
        assert len(new_docs)        == 2
        for doc in new_docs:
            for key in KEYS_TO_COMPARE - set(['pages']):
                assert doc[key] == doc_to_split[key]
        assert new_docs[0]['pages'] == sorted(filter(lambda x: x <= split_after, doc_to_split['pages']))
        assert new_docs[1]['pages'] == sorted(filter(lambda x: x > split_after, doc_to_split['pages']))
        assert new_docs[0]['identifier'] not in id_to_doc
        assert new_docs[1]['identifier'] not in id_to_doc
        assert not doc_id_to_split in all_ids


    def test_split_invalid_index(self, store, action_manager):
        doc_id_to_split = 1
        for split_after in [-1, 3]:
            with pytest.raises(actions.SplitException):
                action_manager.do(actions.SplitAction(store, doc_id_to_split, split_after))
            

    def test_split_invalid_id(self, store, action_manager):
        for id_ in [None, 3.5]:
            with pytest.raises(connectors.InvalidIdentifierException):
                action_manager.do(actions.SplitAction(store, id_, 0))


    def test_split_unavailable_id(self, store, action_manager):
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager.do(actions.SplitAction(store, 99, 0))



class TestDoctypeAssign:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_doctype_assign(self, store, action_manager, id_to_doc):
        ids             = [1, 3, 5, 14]
        new_doctypes    = [['fax'], ['email', 'vermerk'], [], connectors.NO_DOCTYPE]
        for id_ in ids:
            org_doc = id_to_doc[id_]
            for new_doctype in new_doctypes:
                action_manager.do(actions.AssignDoctypeAction(store, id_, new_doctype))
                changed_doc = store.find(identifier = id_)
                assert len(changed_doc) and changed_doc[0]['doctypes'] == (new_doctype if new_doctype != connectors.NO_DOCTYPE else [])
                for key in KEYS_TO_COMPARE - set(['doctypes']):
                    assert changed_doc[0][key] == org_doc[key]
                action_manager.undo()


    def test_doctype_assign_undo(self, store, action_manager, normalized_test_docs):
        ids             = [1, 3, 5, 14]
        new_doctypes    = [['fax'], ['email', 'vermerk'], [], connectors.NO_DOCTYPE]
        for id_ in ids:
            for new_doctype in new_doctypes:
                action_manager.do(actions.AssignDoctypeAction(store, id_, new_doctype))
                action_manager.undo()
                result_docs     = store.find()
                assert len(normalized_test_docs) == len(result_docs)
                for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
                    for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                        assert doc_bef[key] == doc_after[key]


    def test_doctype_assign_undo_redo(self, store, action_manager, id_to_doc):
        ids             = [1, 3, 5, 14]
        new_doctypes    = [['fax'], ['email', 'vermerk'], [], connectors.NO_DOCTYPE]
        for id_ in ids:
            org_doc = id_to_doc[id_]
            for new_doctype in new_doctypes:
                action_manager.do(actions.AssignDoctypeAction(store, id_, new_doctype))
                action_manager.undo()
                action_manager.redo()
                changed_doc = store.find(identifier = id_)
                assert len(changed_doc) and changed_doc[0]['doctypes'] == (new_doctype if new_doctype != connectors.NO_DOCTYPE else [])
                for key in KEYS_TO_COMPARE - set(['doctypes']):
                    assert changed_doc[0][key] == org_doc[key]
                action_manager.undo()



    def test_doctype_assign_invalid_id(self, store, action_manager):
        for id_ in [None, 3.5]:
            with pytest.raises(connectors.InvalidIdentifierException):
                action_manager.do(actions.AssignDoctypeAction(store, id_, 'fax'))


    def test_doctype_assign_unavailable_id(self, store, action_manager):
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager.do(actions.AssignDoctypeAction(store, 99, 'fax'))



class TestJunkAssign:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_junk_assign(self, store, action_manager, id_to_doc):
        id_to_change    = 13
        org_doc         = id_to_doc[id_to_change]
        action_manager.do(actions.AssignJunkAction(store, id_to_change, True))
        changed_doc = store.find(identifier = id_to_change)
        assert len(changed_doc) and changed_doc[0]['junk'] == True
        for key in KEYS_TO_COMPARE - set(['junk']):
            assert changed_doc[0][key] == org_doc[key]
        assert changed_doc[0]['junk'] != org_doc['junk']

    def test_junk_assign_undo(self, store, action_manager, normalized_test_docs):
        id_to_change    = 13
        action_manager.do(actions.AssignJunkAction(store, id_to_change, True))
        action_manager.undo()
        result_docs     = store.find()
        assert len(normalized_test_docs) == len(result_docs)
        for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
            for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                assert doc_bef[key] == doc_after[key]


    def test_junk_assign_undo_redo(self, store, action_manager, id_to_doc):
        id_to_change    = 13
        org_doc         = id_to_doc[id_to_change]
        action_manager.do(actions.AssignJunkAction(store, id_to_change, True))
        action_manager.undo()
        action_manager.redo()
        changed_doc = store.find(identifier = id_to_change)
        assert len(changed_doc) and changed_doc[0]['junk'] == True
        for key in KEYS_TO_COMPARE - set(['junk']):
            assert changed_doc[0][key] == org_doc[key]
        assert changed_doc[0]['junk'] != org_doc['junk']



    def test_junk_assign_invalid_id(self, store, action_manager):
        for id_ in [None, 3.5]:
            with pytest.raises(connectors.InvalidIdentifierException):
                action_manager.do(actions.AssignDoctypeAction(store, id_, 'fax'))


    def test_junk_assign_unavailable_id(self, store, action_manager):
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager.do(actions.AssignDoctypeAction(store, 99, 'fax'))



class TestDelete:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_delete(self, store, action_manager):
        doc_id_to_delete    = 8
        action_manager.do(actions.DeleteAction(store, doc_id_to_delete))
        assert doc_id_to_delete not in store.identifiers()


    def test_delete_undo(self, store, action_manager, normalized_test_docs):
        doc_id_to_delete    = 8
        action_manager.do(actions.DeleteAction(store, doc_id_to_delete))
        action_manager.undo()
        result_docs         = store.find()
        assert len(normalized_test_docs) == len(result_docs)
        for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
            for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                assert doc_bef[key] == doc_after[key]


    def test_delete_undo_redo(self, store, action_manager):
        doc_id_to_delete    = 8
        action_manager.do(actions.DeleteAction(store, doc_id_to_delete))
        action_manager.undo()
        action_manager.redo()
        assert doc_id_to_delete not in store.identifiers()


    def test_delete_invalid_id(self, store, action_manager):
        for id_ in [None, 3.5]:
            with pytest.raises(connectors.InvalidIdentifierException):
                action_manager.do(actions.DeleteAction(store, id_))


    def test_delete_unavailable_id(self, store, action_manager):
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager.do(actions.DeleteAction(store, 99))



class TestChain:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_chain(self, store, action_manager, normalized_test_docs):

        assert action_manager.undo_chain_length == 0
        assert action_manager.redo_chain_length == 0
        
        action_manager.do(actions.MergeAction(store, 1, 2))
        assert action_manager.undo_chain_length == 1
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.AssignDoctypeAction(store, 8, ['fax', 'verfügung', 'chat']))
        assert action_manager.undo_chain_length == 2
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.MergeAction(store, 11, 12))
        assert action_manager.undo_chain_length == 3
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.MergeAction(store, 8, 9))
        assert action_manager.undo_chain_length == 4
        assert action_manager.redo_chain_length == 0

        action_manager.undo()
        assert action_manager.undo_chain_length == 3
        assert action_manager.redo_chain_length == 1

        action_manager.redo()
        assert action_manager.undo_chain_length == 4
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.SplitAction(store, 3, 9))
        assert action_manager.undo_chain_length == 5
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.SplitAction(store, 7, 0))
        assert action_manager.undo_chain_length == 6
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.DeleteAction(store, 13))
        assert action_manager.undo_chain_length == 7
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.ClusterAction(store, 10, [0, 1]))
        assert action_manager.undo_chain_length == 8
        assert action_manager.redo_chain_length == 0

        action_manager.undo()
        assert action_manager.undo_chain_length == 7
        assert action_manager.redo_chain_length == 1

        action_manager.redo()
        assert action_manager.undo_chain_length == 8
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.ClusterAction(store, 5, [3]))
        assert action_manager.undo_chain_length == 9
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.AssignJunkAction(store, 4, True))
        assert action_manager.undo_chain_length == 10
        assert action_manager.redo_chain_length == 0

        action_manager.do(actions.SplitAction(store, 6, 4))
        assert action_manager.undo_chain_length == 11
        assert action_manager.redo_chain_length == 0

        action_manager.undo()
        assert action_manager.undo_chain_length == 10
        assert action_manager.redo_chain_length == 1

        action_manager.redo()
        assert action_manager.undo_chain_length == 11
        assert action_manager.redo_chain_length == 0

        action_manager.undo()
        assert action_manager.undo_chain_length == 10
        assert action_manager.redo_chain_length == 1

        action_manager.do(actions.AssignDoctypeAction(store, 4, connectors.NO_DOCTYPE))
        assert action_manager.undo_chain_length == 11
        assert action_manager.redo_chain_length == 0

        for i in range(11):
            action_manager.undo()
            assert action_manager.undo_chain_length == 11 - i - 1
            assert action_manager.redo_chain_length == i + 1

        for i in range(11):
            action_manager.redo()
            assert action_manager.undo_chain_length == i + 1
            assert action_manager.redo_chain_length == 11 - i - 1
        
        for i in range(11):
            action_manager.undo()
            assert action_manager.undo_chain_length == 11 - i - 1
            assert action_manager.redo_chain_length == i + 1

        result_docs = store.find()
        for (doc_bef, doc_after) in zip(normalized_test_docs, result_docs):
            for key in KEYS_TO_COMPARE.union(set(['identifier'])):
                assert doc_bef[key] == doc_after[key]
