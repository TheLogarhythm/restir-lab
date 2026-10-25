"""Stable method identity for DI measurements and their presentation."""
METHODS = ("restir_di", "pdf_similarity", "cgns")


def method(config):
    enabled = config["definition"].get("pdf_similarity", False)
    cgns = config["definition"].get("cgns", False)
    if not isinstance(enabled, bool):
        raise ValueError("pdf_similarity must be a boolean")
    if not isinstance(cgns, bool):
        raise ValueError("cgns must be a boolean")
    if enabled and cgns:
        raise ValueError("CGNS and PDF Similarity must be evaluated separately")
    return "cgns" if cgns else METHODS[int(enabled)]


def row_method(row):
    return row.get("method", "restir_di")  # Existing baseline CSVs have no method column.


def method_label(name):
    return {"restir_di": "ReSTIR DI", "pdf_similarity": "PDF on", "cgns": "CGNS"}[name]
