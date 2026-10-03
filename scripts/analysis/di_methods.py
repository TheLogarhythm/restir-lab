"""Stable method identity for DI measurements and their presentation."""
METHODS = ("restir_di", "pdf_similarity")


def method(config):
    enabled = config["definition"].get("pdf_similarity", False)
    if not isinstance(enabled, bool):
        raise ValueError("pdf_similarity must be a boolean")
    return METHODS[int(enabled)]


def row_method(row):
    return row.get("method", "restir_di")  # Existing baseline CSVs have no method column.


def method_label(name):
    return {"restir_di": "PDF off", "pdf_similarity": "PDF on"}[name]
