"""Independent test data helpers, never a source-path fallback or product solver."""
from pathlib import Path
import copy
import json
import unittest

from settlement_match_workbench import Limits, Status
from settlement_match_workbench.financial import Currency, Policy, Lot, Credit, Scenario, ReportResult, analyze, analyze_json

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'

def load(name):
    return json.loads((FIXTURES / name).read_bytes())

def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')

def base_wire():
    return load('unique-input.json')

def small_wire():
    return {'schema_version': 1, 'scenario_id': 'small', 'currencies': [{'code': 'BRL', 'minor_digits': 2}], 'policy': {'early_days': 0, 'late_days': 0}, 'lots': [{'id': 'A', 'currency': 'BRL', 'expected_on': '2026-11-10', 'gross_minor': '9000', 'fees_minor': '0', 'refunds_minor': '0', 'reference': None}], 'credits': [{'id': 'X', 'currency': 'BRL', 'booked_on': '2026-11-10', 'amount_minor': '9000', 'reference': None}]}

def as_sdk(value, mutable=False):
    """Fixture conversion only: actual SDK numeric boundary is tested separately."""
    currencies = [Currency(**row) for row in value['currencies']]
    lots = [Lot(**{k: int(v) if k in ('gross_minor', 'fees_minor', 'refunds_minor') else v for k, v in row.items()}) for row in value['lots']]
    credits = [Credit(**{k: int(v) if k == 'amount_minor' else v for k, v in row.items()}) for row in value['credits']]
    return Scenario(scenario_id=value['scenario_id'], currencies=currencies if mutable else tuple(currencies), policy=Policy(**value['policy']), lots=lots if mutable else tuple(lots), credits=credits if mutable else tuple(credits))

class FinancialCase(unittest.TestCase):
    def report(self, result, status=Status.COMPLETE, code='OK', limit=50_000_000):
        self.assertIs(type(result), ReportResult)
        self.assertIs(result.status, status)
        self.assertEqual(result.code, code)
        self.assertIs(type(result.work_used), int)
        self.assertGreaterEqual(result.work_used, 0)
        self.assertLessEqual(result.work_used, limit)
        self.assertIs(type(result.json_bytes), bytes)
        self.assertLessEqual(len(result.json_bytes), 524288)
        frame = json.loads(result.json_bytes)
        self.assertEqual(set(frame), {'schema_version', 'status', 'code', 'work_used', 'analysis'})
        self.assertEqual(frame['schema_version'], 1)
        self.assertEqual(frame['status'], status.value)
        self.assertEqual(frame['code'], code)
        self.assertEqual(frame['work_used'], result.work_used)
        self.assertEqual(result.json_bytes, canonical(frame) + bytes([10]))
        if status is Status.COMPLETE:
            self.assertIs(type(frame['analysis']), dict)
        else:
            self.assertIsNone(frame['analysis'])
        return frame['analysis']

    def complete_wire(self, value):
        return self.report(analyze_json(canonical(value)))

    def invalid_wire(self, value, code):
        result = analyze_json(canonical(value), Limits(0))
        self.report(result, Status.INVALID_INPUT, code, 0)
        self.assertEqual(result.work_used, 0)

    def pair_map(self, analysis):
        return {(p['lot_id'], p['credit_id']): p for p in analysis['pairs']}
