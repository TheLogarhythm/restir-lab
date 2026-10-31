"""Portable research-data invariants, without PDFs, APIs, renderers or npm."""
import copy
import csv
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.check_literature import validate, matrix_projection, check_matrix, check_layout, check_figures


ROOT = Path(__file__).resolve().parents[2]


def paper(identifier, year, doi):
    return {
        "paper_id": identifier, "title": f"Title {identifier}", "short_title": identifier,
        "authors": ["Example Author"], "year": year, "venue": "Example Journal",
        "publication_status": "published", "doi": doi, "tags": ["foundations"],
        "role": "mainline", "problem": "A sampling problem.",
        "contributions": ["A new estimator."], "changes": "Extends prior reuse.",
        "limitations": ["Assumes static geometry."],
        "links": {"paper": "https://example.org/paper", "pdf": None, "code": None},
        "sources": [{"url": "https://example.org/paper", "kind": "publisher",
                     "checked": "2026-10-30", "note": "Metadata record."}],
        "verification": {"metadata": "verified", "content": "full_text", "notes": "Reviewed sections."},
        "pdf": {"status": "missing", "local_file": None, "sha256": None,
                "version": "No local copy", "source_url": None},
    }


def fixture():
    papers = {"schema_version": 1, "cutoff_date": "2026-10-30", "papers": [
        paper("prior2020", 2020, "10.1234/prior"), paper("next2021", 2021, "10.1234/next")]}
    relations = {"schema_version": 1, "relations": [{
        "id": "prior-next-inheritance", "predecessor": "prior2020", "successor": "next2021",
        "citing_paper": "next2021", "cited_paper": "prior2020", "type": "inheritance",
        "verification": "verified", "evidence": [{"source_url": "https://example.org/paper.pdf",
        "locator": "Section 3, p. 4", "explanation": "Extends the prior algorithm's sampling domain.",
        "checked": "2026-10-30", "method": "full_text_review"}]}]}
    return papers, relations


class LiteratureValidationTests(unittest.TestCase):
    def setUp(self):
        self.papers, self.relations = fixture()

    def assertInvalid(self, fragment):
        self.assertTrue(any(fragment in e for e in validate(self.papers, self.relations)), fragment)

    def test_valid_small_graph_and_pending_edges(self):
        self.assertEqual([], validate(self.papers, self.relations))
        self.relations["relations"][0].update(verification="pending", evidence=[])
        self.assertEqual([], validate(self.papers, self.relations))

    def test_rejects_duplicate_identity_and_publication_version(self):
        self.papers["papers"].append(copy.deepcopy(self.papers["papers"][0]))
        self.assertInvalid("duplicate paper_id")
        self.papers["papers"][-1]["paper_id"] = "alias2020"
        self.assertInvalid("duplicate DOI")

    def test_rejects_missing_endpoints_self_edges_and_duplicates(self):
        edge = self.relations["relations"][0]
        edge["predecessor"] = "missing"
        self.assertInvalid("unknown endpoint")
        edge["predecessor"] = edge["successor"]
        self.assertInvalid("self relation")
        self.papers, self.relations = fixture()
        duplicate = copy.deepcopy(self.relations["relations"][0])
        duplicate["id"] = "other-id"
        self.relations["relations"].append(duplicate)
        self.assertInvalid("duplicate relation")

    def test_display_direction_does_not_reverse_citation_semantics(self):
        edge = self.relations["relations"][0]
        edge["citing_paper"], edge["cited_paper"] = edge["cited_paper"], edge["citing_paper"]
        self.assertInvalid("citation direction")

    def test_inheritance_requires_body_evidence_not_just_bibliography(self):
        self.relations["relations"][0]["evidence"] = []
        self.assertInvalid("verified relation lacks evidence")
        self.papers, self.relations = fixture()
        self.relations["relations"][0]["evidence"][0]["locator"] = "References, p. 12"
        self.assertInvalid("inheritance needs body")

    def test_formal_year_can_follow_citing_year_only_with_version_explanation(self):
        self.papers["papers"][0]["year"] = 2024
        self.assertInvalid("version explanation")
        self.relations["relations"][0]["evidence"][0]["explanation"] += " Cites its 2019 preprint version."
        self.assertEqual([], validate(self.papers, self.relations))

    def test_public_links_cannot_point_to_local_files_or_script_urls(self):
        self.papers["papers"][0]["links"]["pdf"] = "C:/papers/private.pdf"
        self.assertInvalid("public URL")
        self.papers["papers"][0]["links"]["pdf"] = "javascript:alert(1)"
        self.assertInvalid("public URL")

    def test_available_local_copy_requires_source_hash_and_version(self):
        self.papers["papers"][0]["pdf"]["status"] = "available"
        self.assertInvalid("available PDF")

    def test_matrix_projection_preserves_human_workflow_state(self):
        old = [{"paper_id": "prior2020", "reading_status": "read_sections_2_3",
                "reproduction_status": "in_progress", "notes_path": "notes/mine.md"}]
        projected = matrix_projection(self.papers["papers"], old)
        self.assertEqual(projected[0]["reading_status"], "read_sections_2_3")
        self.assertEqual(projected[0]["notes_path"], "notes/mine.md")
        self.assertEqual(projected[1]["reading_status"], "not_started")
        self.assertEqual([], check_matrix(self.papers["papers"], projected))
        projected[0]["title"] = "stale title"
        self.assertTrue(any("matrix drift" in e for e in check_matrix(self.papers["papers"], projected)))

    def test_malformed_field_is_reported_instead_of_crashing(self):
        self.papers["papers"][0]["authors"] = "Author"
        self.assertInvalid("authors")
        self.relations["relations"][0]["evidence"] = "not evidence"
        self.assertInvalid("evidence")

    def test_layout_requires_complete_finite_distinct_positions(self):
        layout = {"prior2020": {"x": 0, "y": 0}, "next2021": {"x": 150, "y": 60}}
        self.assertEqual([], check_layout(self.papers["papers"], layout))
        del layout["next2021"]
        self.assertTrue(any("layout IDs" in e for e in check_layout(self.papers["papers"], layout)))
        layout["next2021"] = {"x": float("nan"), "y": 60}
        self.assertTrue(any("finite" in e for e in check_layout(self.papers["papers"], layout)))
        layout["next2021"] = {"x": 0, "y": 0}
        self.assertTrue(any("coincident" in e for e in check_layout(self.papers["papers"], layout)))

    def test_checked_in_dataset_and_matrix(self):
        directory = ROOT / "docs/literature/restir-map"
        import csv
        papers = json.loads((directory / "papers.json").read_text(encoding="utf-8"))
        relations = json.loads((directory / "relations.json").read_text(encoding="utf-8"))
        with (ROOT / "docs/literature/reading-matrix.csv").open(encoding="utf-8", newline="") as file:
            matrix = list(csv.DictReader(file))
        self.assertEqual([], validate(papers, relations))
        self.assertEqual([], check_matrix(papers["papers"], matrix))
        layout = json.loads((ROOT / "web/restir-map/src/graph/layout.json").read_text(encoding="utf-8"))
        self.assertEqual([], check_layout(papers["papers"], layout))
        figures = json.loads((directory / "figures.json").read_text(encoding="utf-8"))
        self.assertEqual([], check_figures(papers["papers"], figures, ROOT / "web/restir-map/public"))


class FigureValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.public = Path(self.temp.name)
        (self.public / "figures").mkdir()
        self.asset = self.public / "figures/prior2020-fig1.webp"
        self.asset.write_bytes(b"fixture-image-bytes")
        self.papers = fixture()[0]["papers"]
        self.document = {"schema_version": 1, "records": [
            {"paper_id": "prior2020", "status": "available", "images": [{
                "id": "prior2020-fig1", "src": "figures/prior2020-fig1.webp",
                "alt": "Diagram of sample reuse.", "caption": "The sampling pipeline.",
                "source_url": "https://example.org/paper.pdf", "source_locator": "Figure 2, p. 3",
                "credit": "Figure © the authors", "source_kind": "paper_figure",
                "sha256": hashlib.sha256(self.asset.read_bytes()).hexdigest(), "width": 1200, "height": 600,
            }]},
            {"paper_id": "next2021", "status": "unavailable", "reason": "No accessible figure found.", "images": []},
        ]}

    def check(self):
        return check_figures(self.papers, self.document, self.public)

    def test_accepts_attributed_figures_and_explicit_missing_status(self):
        self.assertEqual([], self.check())
        self.document["records"][1]["reason"] = ""
        self.assertTrue(any("reason" in e for e in self.check()))

    def test_requires_complete_unique_paper_coverage_and_one_or_two_images(self):
        self.document["records"].pop()
        self.assertTrue(any("coverage" in e for e in self.check()))
        self.document["records"].append(copy.deepcopy(self.document["records"][0]))
        self.assertTrue(any("duplicate paper" in e for e in self.check()))
        self.document["records"][0]["images"] *= 3
        self.assertTrue(any("one or two" in e for e in self.check()))

    def test_rejects_unsafe_asset_paths_and_missing_provenance(self):
        image = self.document["records"][0]["images"][0]
        image["src"] = "../private.webp"
        image["source_url"] = "file:///private.pdf"
        image["credit"] = ""
        errors = self.check()
        self.assertTrue(any("asset path" in e for e in errors))
        self.assertTrue(any("provenance" in e for e in errors))

    def test_detects_missing_or_changed_static_images(self):
        self.asset.write_bytes(b"changed-image")
        self.assertTrue(any("hash" in e for e in self.check()))
        self.asset.unlink()
        self.assertTrue(any("missing" in e for e in self.check()))


class MatrixSyncTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch, prefix="literature-sync-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.script = self.root / "scripts/check_literature.py"
        self.script.parent.mkdir()
        self.script.write_bytes((ROOT / "scripts/check_literature.py").read_bytes())
        data = self.root / "docs/literature/restir-map"
        data.mkdir(parents=True)
        papers, relations = fixture()
        (data / "papers.json").write_text(json.dumps(papers), encoding="utf-8")
        (data / "relations.json").write_text(json.dumps(relations), encoding="utf-8")
        (data / "figures.json").write_text(json.dumps({"schema_version": 1, "records": [
            {"paper_id": item["paper_id"], "status": "unavailable", "images": [],
             "reason": "No fixture image."} for item in papers["papers"]
        ]}), encoding="utf-8")
        layout = self.root / "web/restir-map/src/graph/layout.json"
        layout.parent.mkdir(parents=True)
        layout.write_text(json.dumps({
            "prior2020": {"x": 0, "y": 0}, "next2021": {"x": 150, "y": 60},
        }), encoding="utf-8")
        self.matrix = self.root / "docs/literature/reading-matrix.csv"
        self.rows = [{
            "paper_id": "prior2020", "title": "Stale title", "year": "2019",
            "venue": "Stale venue", "source_url": "https://example.org/stale",
            "code_url": "", "method_family": "transport", "reading_status": "read_sections_2_3",
            "reproduction_status": "in_progress", "notes_path": "notes/mine.md",
        }]

    def write_matrix(self):
        with self.matrix.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def sync(self):
        return subprocess.run([sys.executable, "-B", str(self.script), "--sync-matrix"],
                              cwd=self.root, capture_output=True, text=True, check=False)

    def test_duplicate_ids_fail_without_changing_input_bytes(self):
        self.rows.append({**self.rows[0], "reading_status": "not_started",
                          "reproduction_status": "not_started", "notes_path": "notes/other.md"})
        self.write_matrix()
        before = self.matrix.read_bytes()
        result = self.sync()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("duplicate reading-matrix paper_id", result.stdout)
        self.assertEqual(self.matrix.read_bytes(), before)

    def test_metadata_drift_sync_preserves_workflow_state(self):
        self.write_matrix()
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with self.matrix.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual([row["paper_id"] for row in rows], ["prior2020", "next2021"])
        self.assertEqual(rows[0], {
            "paper_id": "prior2020", "title": "Title prior2020", "year": "2020",
            "venue": "Example Journal", "source_url": "https://example.org/paper",
            "code_url": "", "method_family": "foundations", "reading_status": "read_sections_2_3",
            "reproduction_status": "in_progress", "notes_path": "notes/mine.md",
        })
        self.assertEqual(rows[1]["reading_status"], "not_started")
        self.assertEqual(rows[1]["reproduction_status"], "not_started")


if __name__ == "__main__":
    unittest.main()
