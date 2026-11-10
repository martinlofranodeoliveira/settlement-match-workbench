import unittest
import settlement_match_workbench as s

class PostReadRegressions(unittest.TestCase):
    def test_left_terminal_lf_is_invalid_before_work(self):
        for value in ['A\n','_'+'A'*30+'\n']:
            with self.subTest(shape='left_terminal_lf'):
                r=s.solve(s.Problem((value,),('X',),(s.Edge(value,'X',0),)))
                self.assertEqual(r.status,s.Status.INVALID_INPUT);self.assertIsNone(r.analysis);self.assertEqual(r.work_used,0)
    def test_right_terminal_lf_is_invalid_before_work(self):
        value='X\n';r=s.solve(s.Problem(('A',),(value,),(s.Edge('A',value,0),)))
        self.assertEqual(r.status,s.Status.INVALID_INPUT);self.assertIsNone(r.analysis);self.assertEqual(r.work_used,0)
