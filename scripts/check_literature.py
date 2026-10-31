"""Validate the static ReSTIR map; optionally synchronize the reading matrix.

No network, PDF, renderer, Zotero, or third-party Python dependency is required.
Bibliographic metadata lives in papers.json; matrix workflow state is preserved.
"""
import argparse
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/literature/restir-map"
MATRIX_FIELDS = ["paper_id", "title", "year", "venue", "source_url", "code_url",
                 "method_family", "reading_status", "reproduction_status", "notes_path"]
TAGS = {"foundations", "reuse_quality", "camera_dynamics", "transport", "estimators", "supporting"}
STATUSES = {"published", "preprint", "course", "book_chapter", "abstract", "technical_report", "talk", "unverified"}


def public_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"https", "http"} and bool(parsed.netloc) and not parsed.username


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def string_list(value):
    return isinstance(value, list) and bool(value) and all(nonempty(v) for v in value)


def valid_date(value):
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def validate(paper_document, relation_document):
    errors = []
    if not isinstance(paper_document, dict) or not isinstance(relation_document, dict):
        return ["documents must be objects"]
    if paper_document.get("schema_version") != 1 or relation_document.get("schema_version") != 1:
        errors.append("unsupported schema_version")
    cutoff = paper_document.get("cutoff_date")
    if not valid_date(cutoff):
        errors.append("invalid cutoff_date")
    papers, relations = paper_document.get("papers"), relation_document.get("relations")
    if not isinstance(papers, list) or not papers:
        return errors + ["papers must be a nonempty list"]
    if not isinstance(relations, list):
        return errors + ["relations must be a list"]
    ids, dois, titles = {}, set(), set()
    for paper in papers:
        if not isinstance(paper, dict):
            errors.append("paper must be an object")
            continue
        identifier = paper.get("paper_id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", identifier):
            errors.append("invalid paper_id")
            continue
        prefix = f"{identifier}: "
        if identifier in ids:
            errors.append(prefix + "duplicate paper_id")
        ids[identifier] = paper
        for key in ("title", "short_title", "venue", "problem", "changes"):
            if not nonempty(paper.get(key)):
                errors.append(prefix + f"invalid {key}")
        for key in ("authors", "contributions", "limitations"):
            if not string_list(paper.get(key)):
                errors.append(prefix + f"invalid {key}")
        title = re.sub(r"\W+", "", str(paper.get("title", "")).casefold())
        if title in titles:
            errors.append(prefix + "duplicate title/version")
        titles.add(title)
        year = paper.get("year")
        if type(year) is not int or not 1900 <= year <= (int(cutoff[:4]) if valid_date(cutoff) else 2100):
            errors.append(prefix + "invalid publication year")
        if paper.get("publication_status") not in STATUSES:
            errors.append(prefix + "invalid publication_status")
        if paper.get("role") not in {"mainline", "branch", "optimization", "resource"}:
            errors.append(prefix + "invalid role")
        tags = paper.get("tags")
        if not string_list(tags) or not set(tags).issubset(TAGS) or len(tags) != len(set(tags)):
            errors.append(prefix + "invalid tags")
        doi = paper.get("doi")
        if doi is not None:
            if not isinstance(doi, str) or not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
                errors.append(prefix + "invalid DOI")
            elif doi.casefold() in dois:
                errors.append(prefix + "duplicate DOI/version")
            else:
                dois.add(doi.casefold())
        links = paper.get("links")
        if not isinstance(links, dict):
            errors.append(prefix + "invalid links")
        else:
            for key in ("paper", "pdf", "code"):
                if key not in links or (links[key] is None and key == "paper") or (links[key] is not None and not public_url(links[key])):
                    errors.append(prefix + f"{key} must be a public URL or explicit null")
        sources = paper.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(prefix + "missing metadata sources")
        else:
            for source in sources:
                if not isinstance(source, dict) or not public_url(source.get("url")) or not valid_date(source.get("checked")) or source.get("kind") not in {"publisher", "author", "institution"} or not nonempty(source.get("note")):
                    errors.append(prefix + "invalid metadata source")
        verification = paper.get("verification", {})
        if not isinstance(verification, dict) or verification.get("metadata") not in {"verified", "partial"} or verification.get("content") not in {"full_text", "abstract_only"} or not isinstance(verification.get("notes"), str):
            errors.append(prefix + "invalid verification")
        pdf = paper.get("pdf", {})
        if not isinstance(pdf, dict) or pdf.get("status") not in {"available", "missing"}:
            errors.append(prefix + "invalid PDF record")
        elif pdf["status"] == "available":
            local = pdf.get("local_file")
            if not (nonempty(local) and re.fullmatch(r"[^/\\:]+\.pdf", local) and re.fullmatch(r"[a-fA-F0-9]{64}", str(pdf.get("sha256", ""))) and nonempty(pdf.get("version")) and public_url(pdf.get("source_url"))):
                errors.append(prefix + "available PDF requires safe relative filename, hash, version and source URL")
    edge_ids, pairs = set(), set()
    for edge in relations:
        if not isinstance(edge, dict):
            errors.append("relation must be an object")
            continue
        identifier = edge.get("id")
        prefix = f"{identifier}: "
        if not nonempty(identifier) or identifier in edge_ids:
            errors.append(prefix + "invalid/duplicate relation ID")
        if isinstance(identifier, str):
            edge_ids.add(identifier)
        prior, later = edge.get("predecessor"), edge.get("successor")
        if not isinstance(prior, str) or not isinstance(later, str):
            errors.append(prefix + "invalid endpoints")
            continue
        if prior not in ids or later not in ids:
            errors.append(prefix + "unknown endpoint")
        if prior == later:
            errors.append(prefix + "self relation")
        if edge.get("citing_paper") != later or edge.get("cited_paper") != prior:
            errors.append(prefix + "citation direction must be cited/predecessor -> citing/successor")
        kind = edge.get("type")
        if kind not in {"citation", "inheritance"}:
            errors.append(prefix + "invalid relation type")
        key = (prior, later, str(kind))
        if key in pairs:
            errors.append(prefix + "duplicate relation")
        pairs.add(key)
        if edge.get("verification") not in {"verified", "pending"}:
            errors.append(prefix + "invalid verification status")
        evidence = edge.get("evidence")
        if not isinstance(evidence, list):
            errors.append(prefix + "evidence must be a list")
            continue
        if edge.get("verification") != "verified":
            continue
        if not evidence:
            errors.append(prefix + "verified relation lacks evidence")
        for item in evidence:
            if not isinstance(item, dict):
                errors.append(prefix + "invalid evidence record")
                continue
            methods = {"full_text_review"} if kind == "inheritance" else {"full_text_review", "reference_list_review"}
            if not public_url(item.get("source_url")) or not nonempty(item.get("locator")) or not nonempty(item.get("explanation")) or not valid_date(item.get("checked")) or item.get("method") not in methods:
                errors.append(prefix + "evidence needs public source, locator, explanation, date and appropriate review method")
            locator = str(item.get("locator", "")).casefold()
            if kind == "inheritance" and re.match(r"^(references|bibliography|参考文献)", locator):
                errors.append(prefix + "inheritance needs body evidence, not only a reference entry")
        years = [ids.get(p, {}).get("year") for p in (prior, later)]
        if all(type(y) is int for y in years) and years[0] > years[1]:
            description = json.dumps(evidence, ensure_ascii=False).casefold()
            if not any(word in description for word in ("preprint", "预印本", "版本")):
                errors.append(prefix + "later formal publication requires a version explanation")
    return errors


def matrix_projection(papers, previous):
    existing = {row["paper_id"]: row for row in previous}
    rows = []
    for paper in papers:
        old = existing.get(paper["paper_id"], {})
        rows.append(dict(zip(MATRIX_FIELDS, [paper["paper_id"], paper["title"], str(paper["year"]),
            paper["venue"], paper["links"]["paper"], paper["links"]["code"] or "", paper["tags"][0],
            old.get("reading_status", "not_started"), old.get("reproduction_status", "not_started"),
            old.get("notes_path", "docs/literature/restir-map/README.md")])))
    return rows


def check_matrix(papers, rows):
    errors = []
    by_id = {row["paper_id"]: row for row in rows}
    if len(by_id) != len(rows):
        errors.append("duplicate reading-matrix paper_id")
    if set(by_id) != {paper["paper_id"] for paper in papers}:
        errors.append("reading-matrix paper IDs differ from papers.json")
    for expected in matrix_projection(papers, rows):
        actual = by_id.get(expected["paper_id"], {})
        for field in MATRIX_FIELDS[:7]:
            if actual.get(field) != expected[field]:
                errors.append(f"matrix drift: {expected['paper_id']}.{field}")
    return errors


def check_layout(papers, layout):
    if not isinstance(layout, dict):
        return ["layout must be an object"]
    errors = []
    if set(layout) != {paper["paper_id"] for paper in papers}:
        errors.append("layout IDs differ from papers.json")
    points = set()
    for identifier, point in layout.items():
        if not isinstance(point, dict) or set(point) != {"x", "y"} or not all(type(point.get(axis)) in (int, float) and math.isfinite(point[axis]) for axis in ("x", "y")):
            errors.append(f"{identifier}: layout requires finite x/y coordinates only")
            continue
        coordinates = (point["x"], point["y"])
        if coordinates in points:
            errors.append(f"{identifier}: coincident initial node positions")
        points.add(coordinates)
    return errors


def check_figures(papers, document, public_root):
    """Check publication-ready figure metadata and local bytes without imaging libraries."""
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("records"), list):
        return ["invalid figure manifest"]
    errors, paper_ids, image_ids, paths = [], set(), set(), set()
    expected_ids = {paper["paper_id"] for paper in papers}
    public_root = Path(public_root).resolve()
    for record in document["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("paper_id"), str):
            errors.append("invalid figure paper record")
            continue
        identifier = record["paper_id"]
        prefix = f"figures/{identifier}: "
        if identifier in paper_ids:
            errors.append(prefix + "duplicate paper record")
        paper_ids.add(identifier)
        images = record.get("images")
        if not isinstance(images, list):
            errors.append(prefix + "images must be a list")
            continue
        if record.get("status") == "unavailable":
            if images or not nonempty(record.get("reason")):
                errors.append(prefix + "unavailable figure needs a reason and empty images")
            continue
        if record.get("status") != "available" or not 1 <= len(images) <= 2:
            errors.append(prefix + "available paper needs one or two figures")
        for image in images:
            if not isinstance(image, dict):
                errors.append(prefix + "invalid image record")
                continue
            image_id, source = image.get("id"), image.get("src")
            if not nonempty(image_id) or image_id in image_ids:
                errors.append(prefix + "invalid or duplicate image ID")
            else:
                image_ids.add(image_id)
            if not all(nonempty(image.get(key)) for key in ("alt", "caption", "credit", "source_locator")) or not public_url(image.get("source_url")) or image.get("source_kind") not in ("paper_figure", "project_teaser"):
                errors.append(prefix + "missing figure provenance or accessible description")
            if not all(type(image.get(key)) is int and 0 < image[key] <= 10000 for key in ("width", "height")):
                errors.append(prefix + "invalid image dimensions")
            if not isinstance(source, str) or not re.fullmatch(r"figures/[a-z0-9_-]+\.(?:webp|png|jpg)", source):
                errors.append(prefix + "unsafe local asset path")
                continue
            if source in paths:
                errors.append(prefix + "duplicate asset path")
            paths.add(source)
            path = (public_root / source).resolve()
            if not path.is_relative_to(public_root) or not path.is_file():
                errors.append(prefix + "image asset missing or outside public directory")
                continue
            digest = image.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                errors.append(prefix + "image hash differs or is invalid")
    if paper_ids != expected_ids:
        errors.append("figure manifest coverage differs from papers.json")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync-matrix", action="store_true", help="Regenerate bibliography, preserving reading/reproduction statuses")
    parser.add_argument("--check-local-pdfs", action="store_true", help="Optional local SHA-256 check; never used in CI")
    args = parser.parse_args()
    try:
        papers = json.loads((DATA / "papers.json").read_text(encoding="utf-8"))
        relations = json.loads((DATA / "relations.json").read_text(encoding="utf-8"))
        matrix_path = ROOT / "docs/literature/reading-matrix.csv"
        with matrix_path.open(encoding="utf-8", newline="") as file:
            matrix = list(csv.DictReader(file))
        errors = validate(papers, relations)
        layout = json.loads((ROOT / "web/restir-map/src/graph/layout.json").read_text(encoding="utf-8"))
        errors.extend(check_layout(papers["papers"], layout))
        figures = json.loads((DATA / "figures.json").read_text(encoding="utf-8"))
        errors.extend(check_figures(papers["papers"], figures, ROOT / "web/restir-map/public"))
        if args.sync_matrix and not errors:
            # Duplicate IDs make preserving human workflow fields ambiguous.
            if len({row["paper_id"] for row in matrix}) != len(matrix):
                raise ValueError("duplicate reading-matrix paper_id")
            with matrix_path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=MATRIX_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(matrix_projection(papers["papers"], matrix))
        else:
            errors.extend(check_matrix(papers["papers"], matrix))
        if args.check_local_pdfs and not errors:
            for paper in papers["papers"]:
                record = paper["pdf"]
                if record["status"] == "available":
                    path = ROOT / "assets/papers" / record["local_file"]
                    actual_hash = None
                    if path.is_file():
                        with path.open("rb") as file:
                            actual_hash = hashlib.file_digest(file, "sha256").hexdigest()
                    if actual_hash != record["sha256"].lower():
                        errors.append(f"PDF missing or hash differs: {paper['paper_id']}")
        if errors:
            print("\n".join("FAIL: " + error for error in errors))
            return 1
        verified = sum(r["verification"] == "verified" for r in relations["relations"])
        print(f"PASS: {len(papers['papers'])} papers/resources, {verified} verified relations; metadata and reading matrix agree.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: literature data: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
