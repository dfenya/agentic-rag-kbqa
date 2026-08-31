import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage

from app.rag.nodes import rewrite_query
from app.rag.schemas import QueryAnalysis


class RewriteQueryTests(unittest.TestCase):
    def test_unclear_query_is_counted_before_interrupt(self):
        llm = Mock()
        llm.with_config.return_value.with_structured_output.return_value = Mock()
        analysis = QueryAnalysis(
            is_clear=False,
            questions=[],
            clarification_needed="请补充具体的合同类型和争议事实。",
        )
        state = {
            "messages": [HumanMessage(content="这个怎么处理？")],
            "clarification_count": 2,
        }

        with patch("app.rag.nodes.retry_invoke", return_value=analysis):
            result = rewrite_query(state, llm)

        self.assertEqual(result["clarification_count"], 3)
        self.assertEqual(result["originalQuery"], "这个怎么处理？")


if __name__ == "__main__":
    unittest.main()
