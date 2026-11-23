import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lib import logic  # noqa: E402

Q1, Q2, Q3 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"


class ScoreMcqTest(unittest.TestCase):
    questions = [
        {"id": Q1, "kind": "mcq", "correct_option": 1, "marks": 1},
        {"id": Q2, "kind": "mcq", "correct_option": 0, "marks": 2},
        {"id": Q3, "kind": "short", "correct_option": None, "marks": 5},
    ]

    def test_all_correct(self):
        self.assertEqual(logic.score_mcq(self.questions, {Q1: "1", Q2: "0", Q3: "text"}), (3.0, True))

    def test_wrong_blank_and_garbage(self):
        self.assertEqual(logic.score_mcq(self.questions, {Q1: "2", Q2: "abc"}), (0.0, True))

    def test_mcq_only_exam(self):
        self.assertEqual(logic.score_mcq(self.questions[:2], {Q2: 0}), (2.0, False))


class UploadValidationTest(unittest.TestCase):
    def test_accepts_pdf_and_zip(self):
        self.assertEqual(logic.validate_upload_request("report.PDF", 40 * 1024 * 1024), ("application/pdf", None))
        self.assertEqual(logic.validate_upload_request("code.zip", 1), ("application/zip", None))

    def test_rejects_large_and_wrong_type(self):
        self.assertIsNotNone(logic.validate_upload_request("big.pdf", 50 * 1024 * 1024 + 1)[1])
        self.assertIsNotNone(logic.validate_upload_request("virus.exe", 100)[1])
        self.assertIsNotNone(logic.validate_upload_request("empty.pdf", 0)[1])
        self.assertIsNotNone(logic.validate_upload_request("x.pdf", "lots")[1])

    def test_magic_bytes(self):
        self.assertTrue(logic.sniff_file_type(b"%PDF-1.7", "a.pdf"))
        self.assertTrue(logic.sniff_file_type(b"PK\x03\x04abcd", "a.zip"))
        self.assertFalse(logic.sniff_file_type(b"MZ\x90\x00", "a.pdf"))

    def test_safe_filename(self):
        self.assertEqual(logic.safe_filename("../../etc/My Report (final).pdf"), "My_Report_final_.pdf")
        self.assertEqual(logic.safe_filename(""), "file")
        self.assertTrue(logic.safe_filename("a" * 300 + ".pdf").endswith(".pdf"))
        self.assertLessEqual(len(logic.safe_filename("a" * 300 + ".pdf")), 100)


class RolesTest(unittest.TestCase):
    def test_parse_groups(self):
        self.assertEqual(logic.parse_groups("[students tutors]"), ["students", "tutors"])
        self.assertEqual(logic.parse_groups("admins"), ["admins"])
        self.assertEqual(logic.parse_groups(None), [])

    def test_primary_role_precedence(self):
        self.assertEqual(logic.primary_role(["students", "admins"]), "admin")
        self.assertEqual(logic.primary_role(["tutors"]), "tutor")
        self.assertIsNone(logic.primary_role([]))


class ExamValidationTest(unittest.TestCase):
    def test_valid(self):
        body = {"title": "Quiz", "duration_minutes": 30, "questions": [
            {"kind": "mcq", "prompt": "Q?", "options": ["a", "b"], "correct_option": 1},
            {"kind": "short", "prompt": "Explain"},
        ]}
        self.assertEqual(logic.validate_exam(body), [])

    def test_invalid(self):
        errors = logic.validate_exam({"title": "", "duration_minutes": 0, "questions": [
            {"kind": "mcq", "prompt": "Q?", "options": ["a"], "correct_option": 3},
        ]})
        self.assertGreaterEqual(len(errors), 3)


class RoutingTest(unittest.TestCase):
    def test_match(self):
        routes = [("GET", r"/api/exams/(?P<exam_id>[0-9a-f-]{36})", "get")]
        fn, params = logic.match_route(routes, "GET", f"/api/exams/{Q1}")
        self.assertEqual((fn, params), ("get", {"exam_id": Q1}))
        self.assertEqual(logic.match_route(routes, "POST", f"/api/exams/{Q1}"), (None, None))


if __name__ == "__main__":
    unittest.main()
