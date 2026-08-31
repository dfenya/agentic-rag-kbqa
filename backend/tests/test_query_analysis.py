import unittest

from pydantic import ValidationError

from app.rag.schemas import QueryAnalysis


class QueryAnalysisTests(unittest.TestCase):
    def test_normalizes_empty_and_duplicate_questions(self):
        result = QueryAnalysis(
            is_clear=True,
            questions=["  问题一  ", "", "问题一"],
            clarification_needed="",
        )

        self.assertEqual(result.questions, ["问题一"])

    def test_rejects_more_than_three_questions(self):
        with self.assertRaises(ValidationError):
            QueryAnalysis(
                is_clear=True,
                questions=["一", "二", "三", "四"],
                clarification_needed="",
            )

    def test_clear_query_requires_at_least_one_question(self):
        with self.assertRaises(ValidationError):
            QueryAnalysis(
                is_clear=True,
                questions=[],
                clarification_needed="",
            )

    def test_unclear_query_requires_clarification(self):
        with self.assertRaises(ValidationError):
            QueryAnalysis(
                is_clear=False,
                questions=[],
                clarification_needed="   ",
            )


if __name__ == "__main__":
    unittest.main()
