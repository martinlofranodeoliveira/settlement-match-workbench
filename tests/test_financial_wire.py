"""Financial raw boundaries/digest/ownership; authored before financial source."""
import base64
import copy
import dataclasses
from decimal import Decimal
import hashlib
import json

import settlement_match_workbench.financial as financial
from financial_test_support import FinancialCase, FIXTURES, load, base_wire, small_wire, as_sdk, canonical, analyze, analyze_json, Limits, Status, Scenario, ReportResult

class FinancialWire(FinancialCase):
    def test_12_frozen_raw_refusals(self):
        cases = load('admission-literals.json')['cases']
        self.assertEqual(len(cases), 12)
        for c in cases:
            with self.subTest(c['name']):
                raw = base64.b64decode(c['raw_base64'], validate=True)
                self.assertEqual(len(raw), c['raw_bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), c['raw_sha256'])
                self.report(analyze_json(raw, Limits(0)), Status.INVALID_INPUT, c['expected_code'], 0)

    def test_raw_one_document_complete_EOF(self):
        raw = canonical(base_wire())
        for suffix in (b'x', b'{}', b'\x00'):
            with self.subTest(suffix=suffix):
                self.report(analyze_json(raw+suffix), Status.INVALID_INPUT, 'JSON_SYNTAX')
        for truncated in (b'', b'{', raw[:-1], b'"unterminated'):
            with self.subTest(length=len(truncated)):
                self.report(analyze_json(truncated), Status.INVALID_INPUT, 'JSON_SYNTAX')
        a = self.report(analyze_json(b' \t\r\n'+raw+b' \r\n'))
        self.assertEqual(a, load('unique-analysis.json'))

    def test_exact_input_bytes_cap_then_one_more(self):
        raw = canonical(base_wire())
        padded = raw + b' ' * (524288-len(raw))
        self.assertEqual(len(padded), 524288)
        self.assertEqual(self.report(analyze_json(padded)), load('unique-analysis.json'))
        self.report(analyze_json(padded+b' '), Status.INVALID_INPUT, 'SIZE')
        self.report(analyze_json(b'\xff'*524289, Limits(0)), Status.INVALID_INPUT, 'SIZE', 0)

    def test_raw_type_exact_bytes_no_iterable_or_str_coercion(self):
        class BytesChild(bytes): pass
        class Trap:
            def __bytes__(self):
                raise AssertionError('Must not coerce')
        for raw in (canonical(base_wire()).decode(), bytearray(b'{}'), memoryview(b'{}'), BytesChild(b'{}'), Trap(), None):
            with self.subTest(kind=type(raw).__name__):
                self.report(analyze_json(raw), Status.INVALID_INPUT, 'TYPE')

    def test_decoded_nested_duplicate_rejected_even_identical(self):
        raw = canonical(base_wire())
        duplicate = raw.replace(b'"reference":"R"', b'"reference":"R","\\u0072eference":"R"', 1)
        self.assertNotEqual(raw, duplicate)
        self.report(analyze_json(duplicate), Status.INVALID_INPUT, 'JSON_DUPLICATE')

    def test_valid_escaped_ASCII_keys_and_money_decode_normally(self):
        raw = canonical(base_wire())
        escaped = raw.replace(b'"scenario_id"', b'"\\u0073cenario_id"').replace(b'"gross_minor":"1200"', b'"gross_minor":"\\u0031\\u0032\\u0030\\u0030"')
        self.assertNotEqual(raw, escaped)
        self.assertEqual(self.report(analyze_json(escaped)), load('unique-analysis.json'))

    def test_monetary_wire_strings_are_closed_not_numbers(self):
        for amount in (1, True, 1.0, '01', '+1', '-0', ' 1', '1 ', '1.0', '1e3', '١', '1000000000000001'):
            with self.subTest(amount=repr(amount)):
                value = small_wire(); value['credits'][0]['amount_minor'] = amount
                code = 'TYPE' if type(amount) is not str else 'MONEY'
                self.invalid_wire(value, code)

    def test_SDK_exact_integer_boundary(self):
        class IntChild(int): pass
        scenario = as_sdk(small_wire())
        for amount in (True, 1.0, Decimal('1'), IntChild(1), '9000'):
            with self.subTest(kind=type(amount).__name__):
                bad = dataclasses.replace(scenario, credits=(dataclasses.replace(scenario.credits[0], amount_minor=amount),))
                self.report(analyze(bad, Limits(0)), Status.INVALID_INPUT, 'TYPE', 0)
        for amount in (-1, 0, 10**15+1, 1 << 100000):
            with self.subTest(bit_length=amount.bit_length()):
                bad = dataclasses.replace(scenario, credits=(dataclasses.replace(scenario.credits[0], amount_minor=amount),))
                self.report(analyze(bad, Limits(0)), Status.INVALID_INPUT, 'MONEY', 0)

    def test_ID_reference_and_catalogue_closure(self):
        for field,value,code in [('id','A\n','ID'),('id','-A','ID'),('id','A'*33,'ID'),('reference','R\n','REFERENCE'),('reference','','REFERENCE'),('reference','R'*65,'REFERENCE')]:
            with self.subTest(field=field,value=repr(value)):
                raw = small_wire(); raw['lots'][0][field] = value
                self.invalid_wire(raw, code)
        for catalogue in ([], [{'code':'BRL\n','minor_digits':2}], [{'code':'brl','minor_digits':2}], [{'code':'BRL','minor_digits':2}]*2, [{'code':'BRL','minor_digits':5}], [{'code':code,'minor_digits':2} for code in ('BRL','XAA','XAB','XAC','XAD','XAE','XAF','XAG','XAH')]):
            with self.subTest(catalogue=catalogue):
                value = small_wire(); value['currencies'] = catalogue
                # Invalid catalogues have one intended domain defect; CURRENCY is its public family.
                self.invalid_wire(value, 'CURRENCY')
        value = small_wire(); value['lots'][0]['currency'] = 'USD'
        self.invalid_wire(value, 'CURRENCY')

    def test_closed_shapes_and_duplicate_record_ids(self):
        for mutation in ('extra_root','missing_root','extra_currency','extra_policy','missing_credit_reference','duplicate_lot','duplicate_credit'):
            with self.subTest(mutation=mutation):
                v = small_wire()
                code = 'SHAPE'
                if mutation=='extra_root': v['input_digest']='0'*64
                elif mutation=='missing_root': del v['policy']
                elif mutation=='extra_currency': v['currencies'][0]['name']='realbank'
                elif mutation=='extra_policy': v['policy']['timezone']='UTC'
                elif mutation=='missing_credit_reference': del v['credits'][0]['reference']
                elif mutation=='duplicate_lot': v['lots'].append(copy.deepcopy(v['lots'][0])); code='DUPLICATE_ID'
                else: v['credits'].append(copy.deepcopy(v['credits'][0])); code='DUPLICATE_ID'
                self.invalid_wire(v, code)

    def test_collection_caps_before_copy_and_no_foreign_hooks(self):
        value = small_wire()
        value['lots'] = [dict(value['lots'][0], id='L%02d'%i) for i in range(17)]
        self.invalid_wire(value, 'SIZE')
        value = small_wire(); value['credits'] = [dict(value['credits'][0], id='C%02d'%i) for i in range(17)]
        self.invalid_wire(value, 'SIZE')
        scenario = as_sdk(small_wire())
        class Trap:
            def __iter__(self): raise AssertionError('Must not iterate foreign input')
            def __len__(self): raise AssertionError('Must not size foreign input')
        result = analyze(dataclasses.replace(scenario, lots=Trap()), Limits(0))
        self.assertIs(result.status, Status.INVALID_INPUT)
        self.assertEqual(result.work_used, 0)
        self.assertIsNone(json.loads(result.json_bytes)['analysis'])

    def test_diagnostic_no_raw_echo_and_no_result_prefix(self):
        value = small_wire(); value['lots'][0]['reference']='SENSITIVE_SENTINEL\n'
        result = analyze_json(canonical(value))
        self.report(result, Status.INVALID_INPUT, 'REFERENCE')
        self.assertNotIn(b'SENSITIVE_SENTINEL', result.json_bytes)

    def test_digest_domain_prefix_input_binding_and_permutations(self):
        expected = load('unique-analysis.json')
        value = base_wire()
        normalized = copy.deepcopy(value)
        prefix = bytes.fromhex('534d572d5343454e4152494f310a')
        self.assertEqual(hashlib.sha256(prefix+canonical(normalized)).hexdigest(), expected['input_digest'])
        for key in ('currencies','lots','credits'): value[key].reverse()
        self.assertEqual(self.complete_wire(value), expected)
        mutations = [lambda x:x['policy'].__setitem__('late_days',0), lambda x:x['currencies'][0].__setitem__('minor_digits',3), lambda x:x['lots'][0].__setitem__('gross_minor','1201'), lambda x:x['lots'][0].__setitem__('expected_on','2026-11-11'), lambda x:x['lots'][0].__setitem__('reference','S'), lambda x:x.__setitem__('scenario_id','other')]
        for number,mutate in enumerate(mutations):
            with self.subTest(mutation=number):
                v = base_wire(); mutate(v)
                self.assertNotEqual(self.complete_wire(v)['input_digest'], expected['input_digest'])

    def test_valid_budget0_unknown_invalid_budget0_invalid(self):
        self.report(analyze(as_sdk(base_wire()), Limits(0)), Status.UNKNOWN_BUDGET, 'WORK_LIMIT', 0)
        value = small_wire(); value['credits'][0]['amount_minor']='0'
        self.invalid_wire(value, 'MONEY')

    def test_one_global_budget_exact_observed_threshold(self):
        scenario = as_sdk(base_wire())
        complete = analyze(scenario)
        self.report(complete)
        work = complete.work_used
        self.assertGreater(work, 2)
        self.assertEqual(self.report(analyze(scenario, Limits(work)), limit=work), load('unique-analysis.json'))
        for limit in sorted({0,1,2,work//3,work//2,work-1}):
            with self.subTest(limit=limit):
                result = analyze(scenario, Limits(limit))
                self.report(result, Status.UNKNOWN_BUDGET, 'WORK_LIMIT', limit)
                self.assertIsNone(json.loads(result.json_bytes)['analysis'])

    def test_invalid_limits_and_invalid_scenario_no_algorithm_work(self):
        for limit in (-1,100000001,True,1.0,'100'):
            with self.subTest(limit=limit):
                result = analyze(as_sdk(small_wire()), Limits(limit))
                self.assertIs(result.status, Status.INVALID_INPUT)
                self.assertEqual(result.code, 'TYPE' if type(limit) is not int else 'LIMITS')
                self.assertEqual(result.work_used, 0)
                self.assertIsNone(json.loads(result.json_bytes)['analysis'])
        self.report(analyze(None), Status.INVALID_INPUT, 'TYPE')

    def test_input_and_result_ownership(self):
        value = base_wire()
        for key in ('currencies','lots','credits'): value[key].reverse()
        before = copy.deepcopy(value)
        scenario = as_sdk(value, mutable=True)
        original_collections = (tuple(scenario.currencies),tuple(scenario.lots),tuple(scenario.credits))
        result = analyze(scenario)
        self.assertEqual((tuple(scenario.currencies),tuple(scenario.lots),tuple(scenario.credits)),original_collections)
        self.assertEqual(value,before)
        expected_bytes = result.json_bytes
        expected_analysis = self.report(result)
        scenario.lots.clear(); scenario.credits.clear(); scenario.currencies.clear()
        self.assertEqual(result.json_bytes, expected_bytes)
        self.assertEqual(json.loads(result.json_bytes)['analysis'], expected_analysis)
        for field,new in [('json_bytes',b'bad'),('work_used',0)]:
            with self.assertRaises((dataclasses.FrozenInstanceError,AttributeError)):
                setattr(result,field,new)
        self.assertFalse(hasattr(result,'__dict__'))

    def test_manually_constructed_report_cannot_be_serialized_as_analysis(self):
        forged = ReportResult(Status.COMPLETE,'OK',0,b'{"status":"COMPLETE"}\n')
        self.report(analyze(forged), Status.INVALID_INPUT, 'TYPE')
        self.assertFalse(hasattr(financial,'serialize_report'))
        self.assertFalse(hasattr(financial,'render_report'))

    def test_deep_or_large_node_JSON_refused_without_traceback(self):
        # These also have wrong root shape; contract makes no precedence promise.
        for raw in (b'['*20+b'0'+b']'*20, b'['+b'0,'*5000+b'0]'):
            result = analyze_json(raw, Limits(0))
            self.assertIs(result.status, Status.INVALID_INPUT)
            self.assertIn(result.code, {'JSON_LIMIT','SHAPE'})
            self.assertEqual(result.work_used,0)
            self.assertIsNone(json.loads(result.json_bytes)['analysis'])
        self.report(analyze_json(b'['*10000+b'0'+b']'*10000),Status.INVALID_INPUT,'JSON_LIMIT')
