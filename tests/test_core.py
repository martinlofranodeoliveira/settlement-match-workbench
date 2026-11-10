"""Codex independent tests prepared after primary call admission, BEFORE source ingestion.

Fixtures are frozen pre-generation mathematical oracles. This file is not model
output and must not be executed until root observes generation terminal and the
owner has read every complete runtime file as DATA.
"""
import dataclasses
import json
from pathlib import Path
import random
import unittest
import settlement_match_workbench as s

DATA=Path(__file__).parent/'data'
LITERALS=json.loads((DATA/'hand-literal-graphs.compact.json').read_text())['cases']
DERIVED={r['name']:r for r in json.loads((DATA/'enumeration-results.json').read_text())['results']}
CORPUS=json.loads((DATA/'exhaustive-small-corpus.json').read_text())['records']
CODES={'OK','TYPE','SHAPE','ID','DUPLICATE_ID','EDGE','DUPLICATE_EDGE','UNKNOWN_ID','COST','LIMITS','SIZE','WORK_LIMIT','INVARIANT'}

def problem(case,mutable=False):
    left=list(case['left_ids']);right=list(case['right_ids'])
    edges=[s.Edge(e['left_id'],e['right_id'],e['cost']) for e in case['edges']]
    return s.Problem(left if mutable else tuple(left),right if mutable else tuple(right),edges if mutable else tuple(edges))

def signature(a):
    return (a.objective.cardinality,a.objective.cost,
        tuple((p.left_id,p.right_id) for p in a.representative),
        tuple((e.left_id,e.right_id,e.cost,e.classification,e.probe_objective.cardinality,e.probe_objective.cost) for e in a.edges),
        tuple((v.id,v.can_be_matched,v.can_be_unmatched,v.possible_partner_ids,v.forced_partner_id,None if v.unmatched_probe_objective is None else (v.unmatched_probe_objective.cardinality,v.unmatched_probe_objective.cost)) for v in a.left),
        tuple((v.id,v.can_be_matched,v.can_be_unmatched,v.possible_partner_ids,v.forced_partner_id,None if v.unmatched_probe_objective is None else (v.unmatched_probe_objective.cardinality,v.unmatched_probe_objective.cost)) for v in a.right))

class CoreTests(unittest.TestCase):
    def envelope(self,r,status,limit=50000000):
        self.assertIs(type(r),s.Result);self.assertIs(type(r.status),s.Status)
        self.assertEqual(r.status,status);self.assertIs(type(r.code),str);self.assertIn(r.code,CODES)
        self.assertIs(type(r.work_used),int);self.assertGreaterEqual(r.work_used,0);self.assertLessEqual(r.work_used,limit)
        if status is not s.Status.COMPLETE:self.assertIsNone(r.analysis)
        else:self.assertEqual(r.code,'OK');self.assertIs(type(r.analysis),s.Analysis)
        return r
    def complete(self,p):return self.envelope(s.solve(p),s.Status.COMPLETE)
    def assert_objective(self,obj,expected):
        self.assertIs(type(obj),s.Objective);self.assertIs(type(obj.cardinality),int);self.assertIs(type(obj.cost),int)
        self.assertEqual((obj.cardinality,obj.cost),(expected['cardinality'],expected['cost']))
    def assert_case(self,case):
        r=self.complete(problem(case));a=r.analysis;truth=DERIVED[case['name']]
        self.assert_objective(a.objective,truth['objective'])
        representative=tuple(p.left_id+':'+p.right_id for p in a.representative)
        self.assertIn(list(representative),truth['optimal_family'])
        self.assertEqual(tuple((p.left_id,p.right_id) for p in a.representative),tuple(sorted((p.left_id,p.right_id) for p in a.representative)))
        for p in a.representative:self.assertIs(type(p),s.Pair)
        self.assertEqual([(e.left_id,e.right_id) for e in a.edges],sorted((e['left_id'],e['right_id']) for e in case['edges']))
        costs={e['left_id']+':'+e['right_id']:e['cost'] for e in case['edges']}
        for e in a.edges:
            self.assertIs(type(e),s.EdgeAnalysis);self.assertIs(type(e.classification),s.EdgeClass)
            label=e.left_id+':'+e.right_id;self.assertEqual(e.cost,costs[label]);self.assertIs(type(e.cost),int)
            expected='FORCED' if label in truth['forced'] else 'OPTIONAL' if label in truth['optional'] else 'GLOBALLY_EXCLUDED'
            self.assertEqual(e.classification,s.EdgeClass[expected])
            probe='exclude' if label in representative else 'force'
            self.assert_objective(e.probe_objective,truth['edge_probe_objectives'][label][probe])
        for side,rows,ids in [('left',a.left,case['left_ids']),('right',a.right,case['right_ids'])]:
            self.assertEqual([v.id for v in rows],sorted(ids))
            for v in rows:
                self.assertIs(type(v),s.VertexAnalysis);self.assertIs(type(v.can_be_matched),bool);self.assertIs(type(v.can_be_unmatched),bool)
                expected=truth[side][v.id];self.assertEqual(v.can_be_matched,expected['can_be_matched']);self.assertEqual(v.can_be_unmatched,expected['can_be_unmatched'])
                self.assertIs(type(v.possible_partner_ids),tuple);self.assertEqual(v.possible_partner_ids,tuple(expected['possible_partner_ids']));self.assertEqual(v.forced_partner_id,expected['forced_partner_id'])
                matched=any((p.left_id if side=='left' else p.right_id)==v.id for p in a.representative)
                if matched:self.assert_objective(v.unmatched_probe_objective,expected['ban_vertex_objective'])
                else:self.assertIsNone(v.unmatched_probe_objective)
        return r

    def test_twenty_frozen_literal_families_and_every_probe_cell(self):
        self.assertEqual(len(LITERALS),20)
        for c in LITERALS:
            with self.subTest(case=c['name']):self.assert_case(c)

    def test_all_81_weighted_2x2_and_512_unweighted_3x3_oracles(self):
        self.assertEqual(len(CORPUS),593)
        for row in CORPUS:
            n=2 if row['group'].startswith('2x2') else 3
            left=tuple('L'+str(i) for i in range(n));right=tuple('R'+str(i) for i in range(n))
            edges=tuple(s.Edge(left[pos//n],right[pos%n],cost) for pos,cost in enumerate(row['cost_tokens']) if cost>=0)
            with self.subTest(group=row['group'],ordinal=row['ordinal']):
                a=self.complete(s.Problem(left,right,edges)).analysis;ex=row['expected'];self.assert_objective(a.objective,ex)
                rep=sum(1<<(left.index(p.left_id)*n+right.index(p.right_id)) for p in a.representative);self.assertIn(rep,ex['family_masks'])
                self.assertEqual([(e.left_id,e.right_id) for e in a.edges],[(left[pos//n],right[pos%n]) for pos,c in enumerate(row['cost_tokens']) if c>=0])
                self.assertEqual(tuple(v.id for v in a.left),left);self.assertEqual(tuple(v.id for v in a.right),right)
                for e in a.edges:
                    bit=1<<(left.index(e.left_id)*n+right.index(e.right_id))
                    want=s.EdgeClass.FORCED if ex['forced_mask']&bit else s.EdgeClass.OPTIONAL if ex['possible_mask']&bit else s.EdgeClass.GLOBALLY_EXCLUDED
                    self.assertEqual(e.classification,want)
                    # Probe cells are exhaustively covered by the20hand fixtures;
                    # this corpus independently fixes objective/family/classes/vertices.
                for rows,ids,key in [(a.left,left,'left_can_be_unmatched_mask'),(a.right,right,'right_can_be_unmatched_mask')]:
                    for v in rows:
                        at=ids.index(v.id);self.assertEqual(v.can_be_unmatched,bool(ex[key]>>at&1))
                        partners=right if ids is left else left
                        positions=[at*n+j if ids is left else j*n+at for j in range(n)]
                        possible=tuple(partners[j] for j,pos in enumerate(positions) if ex['possible_mask']>>pos&1)
                        forced=tuple(partners[j] for j,pos in enumerate(positions) if ex['forced_mask']>>pos&1)
                        self.assertEqual(v.possible_partner_ids,possible);self.assertEqual(v.can_be_matched,bool(possible));self.assertEqual(v.forced_partner_id,forced[0] if forced else None)

    def test_permutations_preserve_entire_analysis(self):
        rng=random.Random(70831)
        for case in LITERALS:
            expected=signature(self.complete(problem(case)).analysis)
            for _ in range(5):
                l=list(case['left_ids']);rr=list(case['right_ids']);e=list(case['edges']);rng.shuffle(l);rng.shuffle(rr);rng.shuffle(e)
                perm=dict(case,left_ids=l,right_ids=rr,edges=e)
                self.assertEqual(signature(self.complete(problem(perm,True)).analysis),expected)

    def test_input_unchanged_and_output_detached_frozen_slots(self):
        case=next(x for x in LITERALS if x['name']=='forced_component_plus_optional_cycle');p=problem(case,True)
        before=(list(p.left_ids),list(p.right_ids),list(p.edges));r=self.complete(p);saved=signature(r.analysis)
        self.assertEqual((p.left_ids,p.right_ids,p.edges),before)
        p.left_ids.reverse();p.right_ids.clear();p.edges.clear();self.assertEqual(signature(r.analysis),saved)
        objects=[r,r.analysis,r.analysis.objective,*r.analysis.representative,*r.analysis.edges,*r.analysis.left,*r.analysis.right]
        for obj in objects:
            self.assertTrue(dataclasses.is_dataclass(obj));self.assertTrue(obj.__dataclass_params__.frozen);self.assertFalse(hasattr(obj,'__dict__'))
        for rows in [r.analysis.representative,r.analysis.edges,r.analysis.left,r.analysis.right]:self.assertIs(type(rows),tuple)
        with self.assertRaises((dataclasses.FrozenInstanceError,AttributeError,TypeError)):r.code='forged'
        with self.assertRaises((dataclasses.FrozenInstanceError,AttributeError,TypeError)):r.analysis.edges[0].cost=99
        self.assertEqual(signature(r.analysis),saved)

    def test_budget_zero_invalid_priority_and_no_reused_prefix(self):
        valid=s.Problem((),(),());complete=self.complete(valid);self.assertGreaterEqual(complete.work_used,2)
        r=self.envelope(s.solve(valid,s.Limits(0)),s.Status.UNKNOWN_BUDGET,0);self.assertEqual(r.code,'WORK_LIMIT');self.assertEqual(r.work_used,0)
        invalid=s.Problem(('A',),('X',),(s.Edge('A','X',-1),))
        r=self.envelope(s.solve(invalid,s.Limits(0)),s.Status.INVALID_INPUT,0);self.assertEqual(r.work_used,0)
        self.assertIsNotNone(complete.analysis)

    def test_exact_observed_work_boundary_and_exhaustion_fail_closed(self):
        case=next(x for x in LITERALS if x['name']=='different_edge_costs_equal_global_cost');p=problem(case)
        baseline=self.complete(p);work=baseline.work_used;self.assertGreater(work,1)
        exact=self.envelope(s.solve(p,s.Limits(work)),s.Status.COMPLETE,work);self.assertEqual(signature(exact.analysis),signature(baseline.analysis));self.assertEqual(exact.work_used,work)
        for bound in sorted(set([0,1,work-1,*range(0,work,max(1,work//11))])):
            r=self.envelope(s.solve(p,s.Limits(bound)),s.Status.UNKNOWN_BUDGET,bound);self.assertEqual(r.code,'WORK_LIMIT')
        self.assertEqual(signature(baseline.analysis),signature(self.complete(p).analysis))

    def test_exact_types_structural_caps_and_bad_values_before_work(self):
        valid=s.Problem(('A',),('X',),(s.Edge('A','X',0),))
        invalid=[None,{},s.Problem('A',('X',),()),s.Problem(('A','A'),('X',),()),s.Problem(('A',),('X',),(s.Edge('missing','X',0),)),s.Problem(('A',),('X',),(s.Edge('A','X',0),s.Edge('A','X',0))),s.Problem(('A',),('X',),(s.Edge('A','X',True),)),s.Problem(('A',),('X',),(s.Edge('A','X',1.0),)),s.Problem(('A',),('X',),(s.Edge('A','X',1000001),)),s.Problem(('A',),('X',),(s.Edge('A','X',1<<100000),)),s.Problem(('-A',),('X',),()),s.Problem(('é',),('X',),())]
        for i,p in enumerate(invalid):
            with self.subTest(case=i):self.assertEqual(self.envelope(s.solve(p,s.Limits(0)),s.Status.INVALID_INPUT,0).work_used,0)
        for limit in [s.Limits(True),s.Limits(-1),s.Limits(100000001),s.Limits(1.0),None]:
            r=self.envelope(s.solve(valid,limit),s.Status.INVALID_INPUT);self.assertEqual(r.work_used,0)
        class ProblemChild(s.Problem):pass
        class EdgeChild(s.Edge):pass
        class LimitsChild(s.Limits):pass
        for p,lim in [(ProblemChild(('A',),('X',),()),s.Limits(0)),(s.Problem(('A',),('X',),(EdgeChild('A','X',0),)),s.Limits(0)),(valid,LimitsChild(0))]:
            self.assertEqual(self.envelope(s.solve(p,lim),s.Status.INVALID_INPUT,0).work_used,0)
        for p in [s.Problem(tuple('L'+str(i) for i in range(17)),(),()),s.Problem((),tuple('R'+str(i) for i in range(17)),())]:
            r=self.envelope(s.solve(p,s.Limits(0)),s.Status.INVALID_INPUT,0);self.assertEqual(r.code,'SIZE')

    def test_unknown_iterables_and_subclasses_are_not_executed(self):
        calls=[]
        class Trap:
            def __iter__(self):calls.append('iter');raise AssertionError('callback')
            def __len__(self):calls.append('len');raise AssertionError('callback')
            def __repr__(self):calls.append('repr');raise AssertionError('callback')
        class TrapList(list):
            def __iter__(self):calls.append('iter-subclass');raise AssertionError('callback')
            def __len__(self):calls.append('len-subclass');raise AssertionError('callback')
        for p in [s.Problem(Trap(),(),()),s.Problem((),Trap(),()),s.Problem((),(),Trap()),s.Problem(TrapList(['A']),(),())]:
            self.envelope(s.solve(p,s.Limits(0)),s.Status.INVALID_INPUT,0)
        self.assertEqual(calls,[])

    def test_full_caps_have_honest_state_without_partial_result(self):
        left=tuple(f'L{i:02}' for i in range(16));right=tuple(f'R{i:02}' for i in range(16))
        edges=tuple(s.Edge(left[i],right[(i+j)%16],0 if j==0 else 1) for i in range(16) for j in range(8));self.assertEqual(len(edges),128)
        r=s.solve(s.Problem(left,right,edges),s.Limits(100000000))
        self.assertIn(r.status,(s.Status.COMPLETE,s.Status.UNKNOWN_BUDGET));self.envelope(r,r.status,100000000)
        if r.status is s.Status.COMPLETE:
            self.assert_objective(r.analysis.objective,{'cardinality':16,'cost':0})
            self.assertEqual(sum(e.classification is s.EdgeClass.FORCED for e in r.analysis.edges),16)
            self.assertEqual(sum(e.classification is s.EdgeClass.GLOBALLY_EXCLUDED for e in r.analysis.edges),112)
            self.assertTrue(all(not v.can_be_unmatched for v in (*r.analysis.left,*r.analysis.right)))
        else:self.assertEqual(r.code,'WORK_LIMIT')
        overflow=s.Problem(left,right,edges+(s.Edge(left[0],right[8],1),))
        invalid=self.envelope(s.solve(overflow,s.Limits(0)),s.Status.INVALID_INPUT,0);self.assertEqual(invalid.code,'SIZE')

    def test_public_exports_are_only_frozen_sdk_surface(self):
        expected={'solve','Status','EdgeClass','Edge','Problem','Limits','Pair','Objective','EdgeAnalysis','VertexAnalysis','Analysis','Result'}
        self.assertEqual(set(s.__all__),expected);self.assertEqual(len(s.__all__),len(expected))
        self.assertEqual(set(s.Status.__members__),{'COMPLETE','INVALID_INPUT','UNKNOWN_BUDGET','INTERNAL_ERROR'});self.assertEqual(set(s.EdgeClass.__members__),{'FORCED','OPTIONAL','GLOBALLY_EXCLUDED'})

if __name__=='__main__':unittest.main()
