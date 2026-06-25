from __future__ import annotations

import datetime as dt
from sqlalchemy import create_engine, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint, delete, exists, select, text, or_, case as case_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import mapped_column, Mapped, DeclarativeBase, relationship, sessionmaker, Session
from sqlalchemy.sql import func
from typing import Any

from .document_store import _NO_DOCTYPE, NO_DOCTYPE, CaseNotFoundException, DocumentStore, EmptyUpdateException, DuplicateException, IdentifierNotFoundException, InvalidIdentifierException, InvalidPageNumberException, InvalidPageIntervalException, UniquePageToDocumentAssignmentException
from src.config import DatabaseConfig



class Base(DeclarativeBase):
    pass



class IdCounter(Base):
    __tablename__           = "counter"
    id: Mapped[int]         = mapped_column(Integer, primary_key = True)
    max_id: Mapped[int]     = mapped_column(Integer, nullable = False, default = 0)



class Case(Base):
    __tablename__           = "cases"
    id: Mapped[int]         = mapped_column(Integer, primary_key = True)
    name: Mapped[str]       = mapped_column(String(512), unique = True, nullable = False)

    # one-to-many: Case → File
    files: Mapped[list[File]]   = relationship(
        back_populates  = "case",
        cascade         = "all, delete-orphan",
    )



class File(Base):
    __tablename__           = "files"
    id: Mapped[int]         = mapped_column(Integer, primary_key = True)
    case_id: Mapped[int]    = mapped_column(Integer, ForeignKey("cases.id", ondelete = "CASCADE"), nullable = False)
    path: Mapped[str]       = mapped_column(String(512), nullable = False)

    __table_args__          = (UniqueConstraint('case_id', 'path', name = 'uq_file_case_path'),)

    # many-to-one: File → Case
    case: Mapped[Case]      = relationship(back_populates = "files")

    # one-to-many: File → Page
    pages: Mapped[list[Page]] = relationship(
        back_populates  = "file",
        cascade         = "all, delete-orphan",
    )



class Page(Base):
    __tablename__           = "pages"
    id: Mapped[int]         = mapped_column(Integer, primary_key = True)
    file_id: Mapped[int]    = mapped_column(Integer, ForeignKey("files.id", ondelete = "CASCADE"), nullable = False)
    number: Mapped[int]     = mapped_column(Integer, nullable = False)

    __table_args__  = (UniqueConstraint('file_id', 'number', name = 'uq_page_file_number'),)

    # many-to-one: Page → File
    file: Mapped[File]      = relationship(back_populates = "pages")

    # one-to-many: Page → PageAssignment
    assignments: Mapped[list[PageAssignment]]   = relationship(
        back_populates  = "page",
        cascade         = "all, delete-orphan",
    )



class Document(Base):
    __tablename__                   = "documents"
    id: Mapped[int]                 = mapped_column(Integer, primary_key = True)
    junk: Mapped[bool]              = mapped_column(Boolean)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default = func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default = func.now(), onupdate = func.now())

    # one-to-many: Document ↔ DoctypeAssignment (via association table)
    doctype_assignments: Mapped[list[DoctypeAssignment]]    = relationship(
        back_populates  = "document",
        cascade         = "all, delete-orphan",
    )
    # one-to-many: Document ↔ PageAssignment
    page_assignments: Mapped[list[PageAssignment]]          = relationship(
        back_populates  = "document",
        cascade         = "all, delete-orphan",
    )



class Doctype(Base):
    __tablename__               = "doctypes"
    id: Mapped[int]             = mapped_column(Integer, primary_key = True)
    name: Mapped[str]           = mapped_column(String(512), unique = True, nullable = False)

    # one-to-many: Doctype ↔ DoctypeAssignment
    assignments: Mapped[list[DoctypeAssignment]]    = relationship(
        back_populates  = "doctype",
        cascade         = "all, delete-orphan",
    )



class DoctypeAssignment(Base):
    __tablename__   = "doctype_assignments"
    document_id: Mapped[int]    = mapped_column(Integer, ForeignKey("documents.id", ondelete = "CASCADE"), primary_key = True)
    doctype_id: Mapped[int]     = mapped_column(Integer, ForeignKey("doctypes.id", ondelete = "CASCADE"), primary_key = True)

    # many-to-one relationships
    document: Mapped[Document]  = relationship(back_populates = "doctype_assignments")
    doctype: Mapped[Doctype]    = relationship(back_populates = "assignments")



class PageAssignment(Base):
    __tablename__ = "page_assignments"
    document_id: Mapped[int]    = mapped_column(Integer, ForeignKey("documents.id", ondelete = "CASCADE"), nullable = False)
    page_id: Mapped[int]        = mapped_column(Integer, ForeignKey("pages.id", ondelete = "CASCADE"), primary_key = True)

    # many-to-one: Document ↔ PageAssignment
    document: Mapped[Document]  = relationship(back_populates = "page_assignments")

    # many-to-one: Page ↔ PageAssignment
    page: Mapped[Page]          = relationship(back_populates = "assignments")



class PostgresStore(DocumentStore):

    def __init__(self, config: DatabaseConfig):
        super().__init__()
        self._config    = config
        dsn             = "postgresql://{}{}@{}:{}/{}".format(config.user, ":{}".format(config.password) if config.password else '', config.host, config.port, config.name)
        self.engine     = create_engine(dsn)

        try:
            Base.metadata.create_all(self.engine)
        except:
            # DATABASE DOES NOT EXIST YET -> Create it
            self._create_database()
            Base.metadata.create_all(self.engine)

        self.SessionLocal   = sessionmaker(bind = self.engine)

        # Note: To support consistent navigation within an action chain using undo and redo, the document store has the ability to insert documents with a specific ID.
        # When doing so, the current document ID sequence does not increment automatically and one runs into the chance of assigning IDs twice.
        # Therefore the store ALWAYS assigns a specific ID, no matter if a specific ID was provided or not.
        # A counter is used, that keeps track of the maximum assigned ID, so than incrementing for subsequent inserts without a specified ID does not run into duplicate problems.
        with self.SessionLocal() as session:
            if not session.query(IdCounter).scalar():
                session.add(IdCounter(id = 0))
                session.commit()


    def _create_database(self):
        # Connect to the default 'postgres' DB as postgres user
        config  = self._config
        dsn     = "postgresql://{}{}@{}:{}/postgres".format(config.user, ":{}".format(config.password) if config.password else '', config.host, config.port)
        engine  = create_engine(dsn)

        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level = "AUTOCOMMIT")
            conn.execute(text("CREATE DATABASE {}".format(config.name)))

        print("Database '{}' created!".format(config.name))


    def insert(self,
            case:       str,
            path:       str,
            pages:      int | list[int],
            identifier: int | None              = None,
            doctypes:   str | list[str] | None  = None,
            junk:       bool | None             = False
        ) -> int:

        if not isinstance(identifier, (int, type(None))):
            raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))

        if isinstance(pages, int):
            pages       = [pages]
        if pages is not None and (not len(pages) or min(pages) < 0):
            raise InvalidPageNumberException("Page number '{}' is invalid!".format(pages))

        if doctypes is None:
            doctypes    = []
        elif isinstance(doctypes, str):
            doctypes    = [doctypes]

        with self.SessionLocal() as session:

            try:

                # Get or create Case
                case_obj = session.scalar(select(Case).where(Case.name == case))
                if not case_obj:
                    case_obj = Case(name = case)
                    session.add(case_obj)
                    session.flush()

                # Get or create File
                file_obj = session.scalar(select(File).where(File.case_id == case_obj.id, File.path == path))
                if not file_obj:
                    file_obj = File(case_id = case_obj.id, path = path)
                    session.add(file_obj)
                    session.flush()

                # Get or create Page objects
                page_objs = []
                for number in pages:
                    page = session.scalar(select(Page).where(Page.file_id == file_obj.id, Page.number == number))
                    if not page:
                        page = Page(file_id = file_obj.id, number = number)
                        session.add(page)
                        session.flush()
                    page_objs.append(page)

                # Get or create Doctype objects
                doctype_objs = []
                for dt_name in doctypes:
                    doctype_obj = session.scalar(select(Doctype).where(Doctype.name == dt_name))
                    if not doctype_obj:
                        doctype_obj = Doctype(name = dt_name)
                        session.add(doctype_obj)
                        session.flush()
                    doctype_objs.append(doctype_obj)

                # Create Document
                if identifier is None:
                    identifier = self._increment_id(session)
                elif identifier > self._highest_id(session):
                    self._update_highest_id(session, identifier)

                doc = Document(id = identifier, junk = junk)
                session.add(doc)
                session.flush()
                doc_id = doc.id

                # Create PageAssignments (doc ↔ page many-to-many)
                for page in page_objs:
                    assignment = session.scalar(select(PageAssignment).where(PageAssignment.document_id == doc.id, PageAssignment.page_id == page.id))
                    if not assignment:
                        assignment = PageAssignment(document_id = doc.id, page_id = page.id)
                        session.add(assignment)

                # Create DoctypeAssignments (doc ↔ doctype many-to-many)
                for doctype_obj in doctype_objs:
                    assignment = DoctypeAssignment(document_id = doc.id, doctype_id = doctype_obj.id)
                    session.add(assignment)

                session.commit()

            except IntegrityError as e:
                raise DuplicateException(str(e))
            except Exception as e:
                session.rollback()
                raise e

        # Return the document ID (as string for external APIs)
        return doc_id


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

        # Make pages and doctypes always a list
        if isinstance(pages, int):
            pages       = [pages]
        if isinstance(doctypes, str):
            doctypes    = [doctypes]
        elif doctypes == NO_DOCTYPE:
            doctypes    = []

        # Check if page numbers are valid
        if pages is not None and (not len(pages) or min(pages) < 0):
            raise InvalidPageNumberException("Page number '{}' is invalid!".format(pages))

        with self.SessionLocal() as session:

            # Check if Document-ID exists
            found = session.execute(select(Document).where(Document.id == identifier)).scalar()
            if found is None:
                raise IdentifierNotFoundException("Document ID '{}' was not found in Database!".format(identifier))

            # Update junk flag
            if not junk is None:
                found.junk = junk

            # Get one assigned page to determine current file
            current_page    = session.execute(select(Page).join(PageAssignment).where(PageAssignment.document_id == identifier)).scalar()
            cur_file        = session.get(File, current_page.file_id)

            # Path update: Check if File with (case + path) already exists, create it otherwise
            if path is not None:
                target_file = session.execute(select(File).where(File.path == path).where(File.case_id == cur_file.case_id)).scalar_one_or_none()
                if target_file is None:
                    target_file = File(path = path, case_id = cur_file.case_id)
                    session.add(target_file)
                    session.flush()
            else:
                target_file = cur_file

            # Pages update: Remove old assignments; get existing pages (path + number (+ case implicitly)), create it otherwise
            # Note: Pages are not re-assigned directly, due to a possible restructuring
            pages_to_reassign = []
            if pages is not None:
                session.query(PageAssignment).filter(PageAssignment.document_id == identifier).delete()
                for number in pages:
                    page = session.execute(select(Page).where(Page.file_id == target_file.id).where(Page.number == number)).scalar_one_or_none()
                    if page is None:
                        page = Page(file_id = target_file.id, number = number)
                        session.add(page)
                        session.flush()
                    pages_to_reassign.append(page.id)

            # If path changed but pages didn't, move pages to new file
            elif path is not None:
                pages_to_move = session.execute(select(Page).join(PageAssignment).where(PageAssignment.document_id == identifier)).scalars()
                for p in pages_to_move:
                    p.file_id = target_file.id

            # Now assign new pages
            for page_id in pages_to_reassign:
                assignment = PageAssignment(page_id = page_id, document_id = identifier)
                try:
                    session.add(assignment)
                except IntegrityError:
                    session.rollback()
                    raise UniquePageToDocumentAssignmentException

            # Doctype update: Delete all previous assignments; Create new doctype is necessary; Assign it
            if doctypes is not None:
                session.query(DoctypeAssignment).filter(DoctypeAssignment.document_id == identifier).delete()
                for name in doctypes:
                    dt = session.execute(select(Doctype).where(Doctype.name == name)).scalar_one_or_none()
                    if dt is None:
                        dt = Doctype(name = name)
                        session.add(dt)
                        session.flush()
                    session.add(DoctypeAssignment(doctype_id = dt.id, document_id = identifier))

                # Delete orphaned doctypes — no longer used anywhere
                orphan_stmt     = select(Doctype).where(~exists().where(DoctypeAssignment.doctype_id == Doctype.id))
                orphan_doctypes = session.execute(orphan_stmt).scalars().all()
                for dt in orphan_doctypes:
                    session.delete(dt)

            # set the document's updated_at flag
            found.updated_at = func.now()

            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise UniquePageToDocumentAssignmentException

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

        # Make pages, cases and doctypes always a list
        if isinstance(pages, int):
            pages       = [pages]
        if isinstance(cases, str):
            cases       = [cases]
        if isinstance(doctypes, str) or doctypes == NO_DOCTYPE:
            doctypes    = [doctypes]

        # Global join over all tables
        base = (
            select(Document.id)
            .join(PageAssignment, PageAssignment.document_id == Document.id)
            .join(Page, Page.id == PageAssignment.page_id)
            .join(File, File.id == Page.file_id)
            .join(Case, Case.id == File.case_id)
            .outerjoin(DoctypeAssignment, DoctypeAssignment.document_id == Document.id)
            .outerjoin(Doctype, Doctype.id == DoctypeAssignment.doctype_id)
            .group_by(Document.id)
        )

        # Filter criteria
        if identifier is not None:
            base = base.where(Document.id == identifier)
        if cases is not None:
            base = base.where(Case.name.in_(cases))
        if path is not None:
            base = base.where(File.path == path)

        if isinstance(doctypes, list):
            non_empty_doctypes = set(doctypes) - set([NO_DOCTYPE])

            # Only NO_DOCTYPE
            if NO_DOCTYPE in doctypes and not non_empty_doctypes:
                base = base.where(Doctype.name.is_(None))
            # NO_DOCTYPE + others
            elif NO_DOCTYPE in doctypes:
                base = base.where(or_(Doctype.name.is_(None), Doctype.name.in_(non_empty_doctypes)))
            # Only others
            else:
                base = base.where(Doctype.name.in_(non_empty_doctypes))

        if junk is not None:
            base = base.where(Document.junk == junk)
        if updated_since is not None:
            base = base.where(Document.updated_at > updated_since)
        if pages is not None:
            base = base.having(func.count(func.distinct(Page.number)).filter(Page.number.in_(pages)) == len(pages))

        # Find Document matching Document IDs
        filtered_docs = base.subquery()

        # Get complete Document-wise data (not just matched rows)
        query = (
            select(
                Document.id,
                Document.junk,
                Document.created_at,
                Document.updated_at,
                func.array_agg(func.distinct(File.path)).label("path"),
                func.array_agg(func.distinct(Case.name)).label("case"),
                func.array_agg(func.distinct(Page.number)).label("pages"),
                func.array_agg(func.distinct(Doctype.name)).label("doctypes"),
            )
            .join(filtered_docs, filtered_docs.c.id == Document.id)
            .join(PageAssignment, PageAssignment.document_id == Document.id)
            .join(Page, Page.id == PageAssignment.page_id)
            .join(File, File.id == Page.file_id)
            .join(Case, Case.id == File.case_id)
            .outerjoin(DoctypeAssignment, DoctypeAssignment.document_id == Document.id)
            .outerjoin(Doctype, Doctype.id == DoctypeAssignment.doctype_id)
            .group_by(Document.id)
        )
        with self.SessionLocal() as session:
            rows = session.execute(query).all()

        formated = [{
            "identifier":   r.id,
            "created_at":   r.created_at,
            "updated_at":   r.updated_at,
            "case":         r.case[0],
            "path":         r.path[0],
            "pages":        r.pages,
            "doctypes":     r.doctypes if r.doctypes != [None] else [],
            "junk":         r.junk
            } for r in rows]

        return sorted(formated, key = lambda x: (x['case'], x['path'], min(x['pages'])))


    def find_documents_in_page_range(self,
            case:       str,
            path:       str,
            page_min:   int,
            page_max:   int
        ) -> list[dict[str, Any]]:

        if page_min > page_max or min(page_min, page_max) < 0:
            raise InvalidPageIntervalException("[{}, {}] is an invalid Interval!".format(page_min, page_max))

        # Find identifiers of matching documents
        filtered_docs = (
            select(Document.id)
            .join(PageAssignment, PageAssignment.document_id == Document.id)
            .join(Page, Page.id == PageAssignment.page_id)
            .join(File, File.id == Page.file_id)
            .join(Case, Case.id == File.case_id)
            .where(Case.name == case)
            .where(File.path == path)
            .group_by(Document.id)
            .having(func.count(case_((Page.number.between(page_min, page_max), 1))) > 0)
        ).subquery()

        # Get complete Document-wise data (not just matched rows)
        query = (
            select(
                Document.id,
                Document.junk,
                Document.created_at,
                Document.updated_at,
                func.array_agg(func.distinct(File.path)).label("path"),
                func.array_agg(func.distinct(Case.name)).label("case"),
                func.array_agg(func.distinct(Page.number)).label("pages"),
                func.array_agg(func.distinct(Doctype.name)).label("doctypes"),
            )
            .join(filtered_docs, filtered_docs.c.id == Document.id)
            .join(PageAssignment, PageAssignment.document_id == Document.id)
            .join(Page, Page.id == PageAssignment.page_id)
            .join(File, File.id == Page.file_id)
            .join(Case, Case.id == File.case_id)
            .outerjoin(DoctypeAssignment, DoctypeAssignment.document_id == Document.id)
            .outerjoin(Doctype, Doctype.id == DoctypeAssignment.doctype_id)
            .group_by(Document.id)
        )

        with self.SessionLocal() as session:
            rows = session.execute(query).all()

        formated = [{
            "identifier":   r.id,
            "created_at":   r.created_at,
            "updated_at":   r.updated_at,
            "case":         r.case[0],
            "path":         r.path[0],
            "pages":        r.pages,
            "doctypes":     r.doctypes if r.doctypes != [None] else [],
            "junk":         r.junk
            } for r in rows]

        return sorted(formated, key = lambda x: (x['case'], x['path'], min(x['pages'])))


    def delete(self,
            identifier: int | None  = None,
            case:       str | None  = None
        ) -> int:

        if not isinstance(identifier, (int, type(None))):
            raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))

        if identifier is not None and case is not None:
            raise ValueError("Cannot specify both `identifier` and `case`.")

        with self.SessionLocal() as session:
            try:
                # Delete by document ID
                if identifier is not None:
                    if not isinstance(identifier, int):
                        raise InvalidIdentifierException("Identifier '{}' is invalid!".format(identifier))

                    # Delete document
                    doc = session.get(Document, identifier)
                    if doc:
                        session.delete(doc)
                    else:
                        raise IdentifierNotFoundException("ID '{}' not found!".format(identifier))

                    # Delete doctype if orphaned
                    orphan_stmt     = select(Doctype).where(~exists().where(DoctypeAssignment.doctype_id == Doctype.id))
                    orphan_doctypes = session.execute(orphan_stmt).scalars().all()
                    for dt in orphan_doctypes:
                        session.delete(dt)

                    session.commit()
                    return 1

                docs_before = self.count()

                # Delete by case (full cascade)
                if case is not None:
                    case_obj = session.scalar(select(Case).where(Case.name == case))
                    if not case_obj:
                        raise CaseNotFoundException("Case '{}' not found!".format(case))

                    # Cascade delete: files → pages → page_assignments
                    session.execute(delete(Case).where(Case.id == case_obj.id))

                    # Delete now-orphaned documents (cascades down to doctypes)
                    session.execute(delete(Document).where(~exists().where(PageAssignment.document_id == Document.id)))

                    # Delete orphaned doctypes — no longer used anywhere
                    orphan_stmt     = select(Doctype).where(~exists().where(DoctypeAssignment.doctype_id == Doctype.id))
                    orphan_doctypes = session.execute(orphan_stmt).scalars().all()
                    for dt in orphan_doctypes:
                        session.delete(dt)

                    session.commit()
                    return docs_before - self.count()

                # Delete everything (both None)
                if identifier is None and case is None:
                    session.execute(delete(DoctypeAssignment))
                    session.execute(delete(PageAssignment))
                    session.execute(delete(Doctype))
                    session.execute(delete(Page))
                    session.execute(delete(File))
                    session.execute(delete(Case))
                    session.execute(delete(Document))
                    session.commit()
                    return docs_before - self.count()

            except Exception as e:
                session.rollback()
                raise e


    def count(self) -> int:
        with self.SessionLocal() as session:
            stmt = select(func.count()).select_from(Document)
            return session.scalar(stmt)


    def identifiers(self) -> list[int]:
        with self.SessionLocal() as session:
            return session.scalars(select(Document.id)).all()


    def cases(self) -> list[str]:
        with self.SessionLocal() as session:
            return sorted(session.scalars(select(Case.name)).all())


    def doctypes(self) -> list[str]:
        with self.SessionLocal() as session:
            return sorted(session.scalars(select(Doctype.name)).all())


    def _increment_id(self, session: Session) -> int:
        """
        Increment the current ID counter by 1 and return it.

        Args:
            session: The current session

        Returns:
            The incremented ID
        """
        counter = session.query(IdCounter).with_for_update().one()
        counter.max_id += 1
        session.flush()
        return counter.max_id


    def _highest_id(self, session: Session) -> int:
        """
        Returns the highest known ID.

        Args:
            session: The current session.

        Returns:
            The highest ID
        """
        return session.query(IdCounter).with_for_update().one().max_id


    def _update_highest_id(self, session: Session, identifier: int):
        """
        Sets the highest ID.

        Args:
            identifier: The new highest ID
            session:    The current session
        """
        counter = session.query(IdCounter).with_for_update().one()
        counter.max_id = identifier
        session.flush()