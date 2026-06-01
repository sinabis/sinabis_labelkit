from typing import Any


def normalize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    pages = doc["pages"] if isinstance(doc["pages"], list) else [doc["pages"]]
    doctypes = doc.get("doctypes")
    if doctypes is None:
        doctypes = []
    elif isinstance(doctypes, str):
        doctypes = [doctypes]
    elif not isinstance(doctypes, list):
        doctypes = list(doctypes)
    ret_doc = {
        "case":         doc["case"],
        "path":         doc["path"],
        "pages":        sorted(pages),
        "doctypes":     sorted(doctypes),
        "junk":         doc["junk"] if "junk" in doc else False
    }

    if 'identifier' in doc:
        ret_doc['identifier'] = doc['identifier']

    return ret_doc