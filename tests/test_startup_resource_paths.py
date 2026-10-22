"""A portable launcher may be extracted directly below a drive root."""
import ast
from pathlib import Path
import unittest


class StartupResourcePathTests(unittest.TestCase):
    def test_resource_lookup_does_not_require_a_source_directory_depth(self):
        source = Path(__file__).resolve().parents[1] / 'src/buggcraft/main.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        loop = next(node for node in tree.body if isinstance(node, ast.For)
                    and isinstance(node.target, ast.Name) and node.target.id == '_resource_candidate')
        expression = compile(ast.Expression(loop.iter), str(source), 'eval')
        for location in ('E:/main.py', 'E:/Buggcraft/main.py', str(source)):
            path = Path(location).resolve()
            candidates = eval(expression, {'APP_DIR': path.parent, '__file__': str(path), 'Path': Path})
            self.assertIn(path.parent / 'resources', candidates)


if __name__ == '__main__':
    unittest.main()
