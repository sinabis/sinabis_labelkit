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
def action_manager_1() -> actions.ActionManager:
    return actions.ActionManager()


@pytest.fixture
def action_manager_2() -> actions.ActionManager:
    return actions.ActionManager()



class Test_Non_Existing_ID_Do:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_doc_no_longer_exists_delete(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_2.do(actions.DeleteAction(store, 1))


    def test_doc_no_longer_exists_assign_doctype(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_2.do(actions.AssignDoctypeAction(store, 1, ["fax"]))


    def test_doc_no_longer_exists_assign_junk(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_2.do(actions.AssignJunkAction(store, 1, True))


    def test_doc_no_longer_exists_cluster(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_2.do(actions.ClusterAction(store, 1, [1, 2]))


    def test_doc_no_longer_exists_merge(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_2.do(actions.MergeAction(store, 1, 2))


    def test_doc_no_longer_exists_split(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_2.do(actions.SplitAction(store, 1, 1))



class Test_Non_Existing_ID_Undo:

    @pytest.fixture(autouse = True)
    def setup(self, store, initial_test_docs):
        for doc in initial_test_docs:
            store.insert(**doc)


    def test_undo_doc_no_longer_exists_assign_doctype(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.AssignDoctypeAction(store, 1, ["fax"]))
        action_manager_2.do(actions.DeleteAction(store, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_1.undo()


    def test_undo_doc_no_longer_exists_assign_junk(self, store, action_manager_1, action_manager_2):
        action_manager_1.do(actions.AssignJunkAction(store, 1, True))
        action_manager_2.do(actions.DeleteAction(store, 1))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_1.undo()


    def test_undo_doc_no_longer_exists_cluster(self, store, action_manager_1, action_manager_2, id_to_doc):
        action_manager_1.do(actions.ClusterAction(store, 1, [1, 2]))
        first_new_id = list(filter(lambda x: x['identifier'] not in id_to_doc.keys(), store.find()))[0]['identifier']
        action_manager_2.do(actions.DeleteAction(store, first_new_id))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_1.undo()


    def test_undo_doc_no_longer_exists_merge(self, store, action_manager_1, action_manager_2, id_to_doc):
        action_manager_1.do(actions.MergeAction(store, 1, 2))
        first_new_id = list(filter(lambda x: x['identifier'] not in id_to_doc.keys(), store.find()))[0]['identifier']
        action_manager_2.do(actions.DeleteAction(store, first_new_id))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_1.undo()


    def test_undo_doc_no_longer_exists_split(self, store, action_manager_1, action_manager_2, id_to_doc):
        action_manager_1.do(actions.SplitAction(store, 1, 1))
        first_new_id = list(filter(lambda x: x['identifier'] not in id_to_doc.keys(), store.find()))[0]['identifier']
        action_manager_2.do(actions.DeleteAction(store, first_new_id))
        with pytest.raises(connectors.IdentifierNotFoundException):
            action_manager_1.undo()
