import unittest
from unittest.mock import Mock

from app.core.config import Settings
from app.core.container import Container


class ContainerGraphCacheTests(unittest.TestCase):
    def test_reuses_graph_for_same_knowledge_base_and_config(self):
        container = Container(Settings())
        graph = object()
        container._compile_graph = Mock(return_value=graph)

        first = container.compile_graph("kb-1")
        second = container.compile_graph("kb-1")

        self.assertIs(first, graph)
        self.assertIs(second, graph)
        container._compile_graph.assert_called_once_with(
            kb_id="kb-1", settings=container.settings
        )

    def test_uses_separate_graphs_for_different_knowledge_bases(self):
        container = Container(Settings())
        first_graph = object()
        second_graph = object()
        container._compile_graph = Mock(
            side_effect=[first_graph, second_graph]
        )

        self.assertIs(container.compile_graph("kb-1"), first_graph)
        self.assertIs(container.compile_graph("kb-2"), second_graph)
        self.assertEqual(container._compile_graph.call_count, 2)


if __name__ == "__main__":
    unittest.main()
