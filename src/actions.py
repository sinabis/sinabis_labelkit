from abc import ABC
from collections import deque
from PyQt6.QtCore import pyqtSignal, QObject

from .connectors import DocumentStore, InvalidIdentifierException, IdentifierNotFoundException, NO_DOCTYPE, _NO_DOCTYPE



DOCUMENT_INSERTION_KEYS = ['identifier', 'case', 'path', 'pages', 'doctypes', 'junk']



class MergeException(Exception):
    pass



class SplitException(Exception):
    pass



class ClusterException(Exception):
    pass



class Action(ABC):

    def do(self):
        raise NotImplementedError


    def undo(self):
        raise NotImplementedError


    def redo(self):
        raise NotImplementedError


    def __repr__(self) -> str:
        raise NotImplementedError



class DeleteAction(Action):

    def __init__(self, store: DocumentStore, doc_id: int):
        """
        An action to delete a single document

        Args:
            store:  The document store
            doc_id: The document identifier of the document to delete
        """
        self._store     = store
        self._doc_id    = doc_id
        if doc_id is None:
            raise InvalidIdentifierException("Identifier cannot be None!")


    def do(self):
        if not (doc := self._store.find(identifier = self._doc_id)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._prev_doc  = {k:v for k, v in doc[0].items() if k in DOCUMENT_INSERTION_KEYS}
        self._store.delete(identifier = self._doc_id)


    def undo(self):
        self._store.insert(**self._prev_doc)


    def redo(self):
        self.do()


    def __repr__(self) -> str:
        return "Deleting ID '{}'".format(self._doc_id)



class AssignDoctypeAction(Action):

    def __init__(self, store: DocumentStore, doc_id: int, doctypes: list[str] | _NO_DOCTYPE):
        """
        An action to assign a list of doctypes to a specific document.

        Args:
            store:      The document store
            doc_id:     The identifier of the document to label
            doctypes:   A list of document types or NO_DOCTYPE
        """
        self._store     = store
        self._doc_id    = doc_id
        self._doctypes  = doctypes
        if doc_id is None:
            raise InvalidIdentifierException("Identifier cannot be None!")


    def do(self):
        if not (doc := self._store.find(identifier = self._doc_id)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._prev_doctypes = doc[0]['doctypes']
        self._store.update(identifier = self._doc_id, doctypes = self._doctypes)


    def undo(self):
        if not self._store.find(identifier = self._doc_id):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._store.update(identifier = self._doc_id, doctypes = self._prev_doctypes)


    def redo(self):
        self.do()


    def __repr__(self) -> str:
        return "Assigning Doctypes '{}' to ID '{}'".format(self._doctypes, self._doc_id)



class AssignJunkAction(Action):

    def __init__(self, store: DocumentStore, doc_id: int, junk: bool):
        """
        Sets the junk flag of a document.

        Args:
            store:  The document store
            doc_id: The identifier of the document to label
            junk:   The junk flag
        """
        self._store     = store
        self._doc_id    = doc_id
        self._junk      = junk
        if doc_id is None:
            raise InvalidIdentifierException("Identifier cannot be None!")


    def do(self):
        if not (doc := self._store.find(identifier = self._doc_id)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._prev_value = doc[0]['junk']
        self._store.update(identifier = self._doc_id, junk = self._junk)


    def undo(self):
        if not self._store.find(identifier = self._doc_id):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._store.update(identifier = self._doc_id, junk = self._prev_value)


    def redo(self):
        self.do()


    def __repr__(self) -> str:
        return "Assigning Junk flag '{}' to ID '{}'".format(self._junk, self._doc_id)



class ClusterAction(Action):

    def __init__(self, store: DocumentStore, doc_id: int, page_numbers: list[int]):
        """
        A cluster action creates a new document for a subset of selected pages of a document, inheriting their attributes
        If there are pages to the left and to the right of the selection, new documents with page numbers up to the cluster range and starting from the cluster range are created respectively.

        Args:
            store:          The document store
            doc_id:         The identifier of the document to cluster
            page_numbers:   The page numbers to group together
        """
        if not page_numbers:
            raise ClusterException("Page number list cannot be empty!")
        elif list(sorted(page_numbers)) != list(range(min(page_numbers), max(page_numbers) + 1)):
            raise ClusterException("Indices for clustering must be consecutive pages: '{}'".format(page_numbers))

        self._store         = store
        self._doc_id        = doc_id
        self._page_numbers  = page_numbers
        if doc_id is None:
            raise InvalidIdentifierException("Identifier cannot be None!")


    def do(self, new_doc_ids: list[int] | None = None):
        if not (doc := self._store.find(identifier = self._doc_id)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._prev_doc  = {k:v for k, v in doc[0].items() if k in DOCUMENT_INSERTION_KEYS}

        range_before    = list(filter(lambda x: x < min(self._page_numbers), self._prev_doc['pages']))
        range_mid       = sorted(self._page_numbers)
        range_after     = list(filter(lambda x: x > max(self._page_numbers), self._prev_doc['pages']))

        if not new_doc_ids:
            new_docs = deque([None, None, None])
        else:
            new_docs = deque(new_doc_ids[::-1])

        # Delete original documents
        self._store.delete(identifier = self._doc_id)

        # Insert new documents
        self._created_ids   = []
        for rng in [range_before, range_mid, range_after]:
            if rng:
                new_id  = self._store.insert(
                    identifier  = new_docs.pop(),
                    case        = self._prev_doc['case'],
                    path        = self._prev_doc['path'],
                    pages       = rng,
                    doctypes    = self._prev_doc['doctypes'],
                    junk        = self._prev_doc['junk']
                )
                self._created_ids.append(new_id)


    def undo(self):
        for _id in self._created_ids:
            if not self._store.find(identifier = _id):
                raise IdentifierNotFoundException("Document with ID '{}' not found!".format(_id))

        # Delete created documents
        for new_id in self._created_ids:
            self._store.delete(identifier = new_id)

        # Re-create previous document
        self._store.insert(**self._prev_doc)


    def redo(self):
        self.do(self._created_ids)


    def __repr__(self) -> str:
        return "Clustering Pages '{}' of ID '{}'".format(self._page_numbers, self._doc_id)



class MergeAction(Action):

    def __init__(self, store: DocumentStore, doc_id_1: int, doc_id_2: int):
        """
        Merges two documents together. They need to have similar case, path and doctype attributes.

        Args:
            store:      The document store
            doc_id_1:   The first document identifier
            doc_id_2:   The second document identifier
        """
        self._store     = store
        self._doc_id_1  = doc_id_1
        self._doc_id_2  = doc_id_2
        if doc_id_1 is None or doc_id_2 is None:
            raise InvalidIdentifierException("Identifier cannot be None!")


    def do(self, new_doc_id: int | None = None):
        if not (doc_1 := self._store.find(identifier = self._doc_id_1)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id_1))
        if not (doc_2 := self._store.find(identifier = self._doc_id_2)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id_2))

        self._prev_doc_1  = {k:v for k, v in doc_1[0].items() if k in DOCUMENT_INSERTION_KEYS}
        self._prev_doc_2  = {k:v for k, v in doc_2[0].items() if k in DOCUMENT_INSERTION_KEYS}

        # Check attribute equality
        for attribute in ['case', 'path', 'doctypes', 'junk']:
            if self._prev_doc_1[attribute] != self._prev_doc_2[attribute]:
                raise MergeException("Documents have varying '{}' values: '{}' and '{}'!".format(attribute, self._prev_doc_1[attribute], self._prev_doc_2[attribute]))

        # Delete original documents
        self._store.delete(identifier = self._doc_id_1)
        self._store.delete(identifier = self._doc_id_2)

        # Insert merged document
        self._created_id    = self._store.insert(
            identifier  = new_doc_id,
            case        = self._prev_doc_1['case'],
            path        = self._prev_doc_1['path'],
            pages       = sorted(self._prev_doc_1['pages'] + self._prev_doc_2['pages']),
            doctypes    = self._prev_doc_1['doctypes'],
            junk        = self._prev_doc_1['junk']
        )


    def undo(self):
        if not self._store.find(identifier = self._created_id):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._created_id))

        # Delete created document
        self._store.delete(identifier = self._created_id)

        # Re-create previous documents
        self._store.insert(**self._prev_doc_1)
        self._store.insert(**self._prev_doc_2)


    def redo(self):
        self.do(self._created_id)


    def __repr__(self) -> str:
        return "Merging Documents '{}' and '{}'".format(self._doc_id_1, self._doc_id_2)



class SplitAction(Action):

    def __init__(self, store: DocumentStore, doc_id: int, split_after: int):
        """
        Split a document after a given page number.

        Args:
            store:          The document store
            doc_id:         The first document identifier
            split_after:    The page number after which the document shall be split
        """
        self._store         = store
        self._doc_id        = doc_id
        self._split_after   = split_after
        if doc_id is None:
            raise InvalidIdentifierException("Identifier cannot be None!")


    def do(self, new_doc_ids: list[int] | None = None):
        if not (doc:= self._store.find(identifier = self._doc_id)):
            raise IdentifierNotFoundException("Document with ID '{}' not found!".format(self._doc_id))

        self._prev_doc  = {k:v for k, v in doc[0].items() if k in DOCUMENT_INSERTION_KEYS}

        pages_before    = sorted(filter(lambda x: x <= self._split_after, self._prev_doc['pages']))
        pages_after     = sorted(filter(lambda x: x > self._split_after, self._prev_doc['pages']))
        if min(len(pages_before), len(pages_after)) == 0:
            raise SplitException("Invalid split index '{}' for document pages '{}'".format(self._split_after, self._prev_doc['pages']))

        # Delete original documents
        self._store.delete(identifier = self._doc_id)

        # Insert new documents
        if not new_doc_ids:
            new_doc_ids = [None, None]

        self._created_ids   = []
        for id_, pages in zip(new_doc_ids, [pages_before, pages_after]):
            created_id  = self._store.insert(
                identifier  = id_,
                case        = self._prev_doc['case'],
                path        = self._prev_doc['path'],
                pages       = pages,
                doctypes    = self._prev_doc['doctypes'],
                junk        = self._prev_doc['junk']
            )
            self._created_ids.append(created_id)


    def undo(self):
        for _id in self._created_ids:
            if not self._store.find(identifier = _id):
                raise IdentifierNotFoundException("Document with ID '{}' not found!".format(_id))

        # Delete created documents
        for id_ in self._created_ids:
            self._store.delete(identifier = id_)

        # Re-create previous documents
        self._store.insert(**self._prev_doc)


    def redo(self):
        self.do(self._created_ids)


    def __repr__(self) -> str:
        return "Splitting ID '{}' after Page '{}'".format(self._doc_id, self._split_after)



class ActionManager(QObject):

    undo_chain_length_changed   = pyqtSignal(int)
    redo_chain_length_changed   = pyqtSignal(int)
    do_triggered                = pyqtSignal(Action)
    undo_triggered              = pyqtSignal(Action)
    redo_triggered              = pyqtSignal(Action)


    @property
    def undo_chain_length(self) -> int:
        return len(self._history)


    @property
    def redo_chain_length(self) -> int:
        return len(self._undo_stack)


    def __init__(self):
        """
        A class that offers the ability to navigate within an action chain using do(), undo() and redo() functions.
        """
        super().__init__()

        self._history       = []
        self._undo_stack    = []

        self.undo_chain_length_changed.emit(0)
        self.redo_chain_length_changed.emit(0)


    def do(self, action: Action):
        """
        Adds a new action to the history and executes it. Clears the undo action chain.

        Args:
            action: the action to apply
        """
        action.do()
        self._history.append(action)
        self._undo_stack.clear()

        self.undo_chain_length_changed.emit(len(self._history))
        self.redo_chain_length_changed.emit(0)
        self.do_triggered.emit(action)


    def undo(self):
        """
        Reverses the last action in the action history chain.
        """
        if self._history:
            action = self._history.pop()
            action.undo()
            self._undo_stack.append(action)
            self.undo_triggered.emit(action)

        self.undo_chain_length_changed.emit(len(self._history))
        self.redo_chain_length_changed.emit(len(self._undo_stack))


    def redo(self):
        """
        Re-applies the last action from the undo action chain.
        """
        if self._undo_stack:
            action = self._undo_stack.pop()
            action.redo()
            self._history.append(action)
            self.redo_triggered.emit(action)

        self.undo_chain_length_changed.emit(len(self._history))
        self.redo_chain_length_changed.emit(len(self._undo_stack))