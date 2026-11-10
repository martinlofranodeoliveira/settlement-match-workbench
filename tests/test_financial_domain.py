"""Domain/literal expectations fixed before the financial model call/source."""
import copy
import datetime as dt

from financial_test_support import FinancialCase, load, small_wire, base_wire, as_sdk, canonical, analyze, analyze_json, Status, Limits

class DomainLiterals(FinancialCase):
    def test_complete_unique_analysis_literal(self):
        expected = load('unique-analysis.json')
        self.assertEqual(self.complete_wire(base_wire()), expected)
        self.assertEqual(self.report(analyze(as_sdk(base_wire()))), expected)

    def test_all_26_pre_source_domain_literals(self):
        cases = load('domain-literals.json')['cases']
        self.assertEqual(len(cases), 26)
        covered = set()
        for c in cases:
            with self.subTest(c['name']):
                self.run_domain_literal(c)
                covered.add(c['name'])
        self.assertEqual(len(covered), 26)

    def run_domain_literal(self, c):
        value = small_wire()
        lot, credit = value['lots'][0], value['credits'][0]
        if 'gross_minor' in c:
            for k in ('gross_minor', 'fees_minor', 'refunds_minor'):
                lot[k] = c[k]
            if 'expected_invalid' in c:
                self.invalid_wire(value, c['expected_invalid'])
                return
            a = self.complete_wire(value)
            self.assertEqual(a['lot_facts'][0]['net_minor'], c['expected_net_minor'])
            if 'expected_state' in c:
                self.assertEqual(a['lots'][0]['state'], c['expected_state'])
        elif 'expected_candidate_date' in c:
            lot['expected_on'], credit['booked_on'] = c['expected_on'], c['booked_on']
            value['policy'] = {k: c[k] for k in ('early_days', 'late_days')}
            pair = self.complete_wire(value)['pairs'][0]
            self.assertEqual('DATE' not in pair['rejection_reasons'], c['expected_candidate_date'])
            if 'expected_abs_day_gap' in c:
                self.assertEqual(abs(pair['signed_day_gap']), c['expected_abs_day_gap'])
        elif 'date' in c:
            lot['expected_on'] = credit['booked_on'] = c['date']
            if c['expected_valid']:
                self.complete_wire(value)
            else:
                self.invalid_wire(value, 'DATE')
        elif 'lot_reference' in c:
            lot['reference'], credit['reference'] = c['lot_reference'], c['credit_reference']
            pair = self.complete_wire(value)['pairs'][0]
            self.assertEqual('REFERENCE' not in pair['rejection_reasons'], c['expected_reference_candidate'])
            if c['expected_reference_candidate']:
                self.assertEqual(pair['candidate_cost'], c['expected_missing_penalty'])  # W1/gap0 literal.
        elif 'lot_currency' in c:
            value['currencies'].append({'code': 'USD', 'minor_digits': 2})
            lot['currency'], credit['currency'] = c['lot_currency'], c['credit_currency']
            self.assertEqual(self.complete_wire(value)['pairs'][0]['rejection_reasons'], ['CURRENCY'])
        elif 'net_minor' in c:
            lot['gross_minor'], credit['amount_minor'] = c['net_minor'], c['amount_minor']
            self.assertEqual(self.complete_wire(value)['pairs'][0]['rejection_reasons'], ['AMOUNT'])
        elif c['name'] == 'inclusive_missing_ref_cost':
            value['policy'] = {'early_days': c['early_days'], 'late_days': c['late_days']}
            credit['booked_on'] = '2026-11-11'
            a = self.complete_wire(value)
            self.assertEqual(a['policy_facts']['reference_weight'], c['expected_W'])
            self.assertEqual(a['pairs'][0]['candidate_cost'], c['expected_cost'])
        elif c['name'] == 'reference_dominates_date':
            value['policy'] = {'early_days': 0, 'late_days': 2}
            lot['reference'] = 'R'
            value['credits'] = [dict(credit, id='KNOWN', booked_on='2026-11-12', reference='R'), dict(credit, id='MISSING')]
            a = self.complete_wire(value)
            pairs = self.pair_map(a)
            self.assertEqual(a['policy_facts']['reference_weight'], c['expected_W'])
            self.assertEqual(pairs['A', 'KNOWN']['candidate_cost'], c['expected_known_cost'])
            self.assertEqual(pairs['A', 'MISSING']['candidate_cost'], c['expected_missing_cost'])
            self.assertEqual(pairs['A', 'KNOWN']['classification'], 'FORCED')
            self.assertEqual(pairs['A', 'MISSING']['classification'], 'GLOBALLY_EXCLUDED')
        elif c['name'] == 'scalarization_maximum':
            # Two8x8 currency components give128edges, all16+16 vertices and W497.
            value['currencies'].append({'code': 'USD', 'minor_digits': 2})
            value['policy'] = {'early_days': 31, 'late_days': 31}
            value['lots'] = [dict(lot, id='L%02d' % i, currency='BRL' if i < 8 else 'USD') for i in range(16)]
            value['credits'] = [dict(credit, id='C%02d' % i, currency='BRL' if i < 8 else 'USD', booked_on='2026-12-11') for i in range(16)]
            a = self.report(analyze_json(canonical(value), Limits(100_000_000)), limit=100_000_000)
            self.assertEqual(a['policy_facts']['reference_weight'], c['expected_W'])
            candidates = [p for p in a['pairs'] if not p['rejection_reasons']]
            self.assertEqual(len(a['pairs']), 256)
            self.assertEqual(len(candidates), 128)
            self.assertEqual({p['candidate_cost'] for p in candidates}, {c['expected_cost']})
            self.assertEqual(a['objective'], {'cardinality': 16, 'cost': 8448})
            self.assertEqual({p['classification'] for p in candidates}, {'OPTIONAL'})
            self.assertTrue(all(not x['can_be_unmatched'] for x in a['lots'] + a['credits']))
        elif 'expected_sum_minor' in c:
            value['lots'] = [dict(lot, id='L%02d' % i, gross_minor=c['per_record_minor']) for i in range(c['count'])]
            value['credits'] = []
            self.assertEqual(self.complete_wire(value)['totals_by_currency'][0]['net_minor'], c['expected_sum_minor'])
        elif 'expected_distinct' in c:
            value['lots'] = [dict(lot, id=name, reference='R'+name) for name in c['left_ids']]
            value['credits'] = [dict(credit, id='C'+name, reference='R'+name) for name in c['left_ids']]
            a = self.complete_wire(value)
            self.assertEqual([r['id'] for r in a['lots']], ['001', '1'])
            self.assertEqual(a['objective']['cardinality'], 2)
        elif 'expected_not_one_money_total' in c:
            value['currencies'] = [{'code': code, 'minor_digits': 2} for code in ('BRL', 'USD')]
            value['lots'] = [dict(lot, id=code, currency=code, gross_minor=amount) for code, amount in c['per_currency_minor'].items()]
            value['credits'] = []
            totals = self.complete_wire(value)['totals_by_currency']
            self.assertEqual({t['currency']: t['net_minor'] for t in totals}, c['per_currency_minor'])
            self.assertNotIn('grand_total_minor', self.complete_wire(value))
        else:
            self.fail('Unhandled pre-source literal '+c['name'])

    def test_nim_reference_priority_four_cell_literal(self):
        c = load('nim-financial-literals.json')['reference_weight']
        value = small_wire()
        value['currencies'], value['policy'] = [c['currency']], c['policy']
        value['lots'] = [{k: str(v) if k.endswith('_minor') else v for k,v in row.items()} for row in c['lots']]
        value['credits'] = [{k: str(v) if k.endswith('_minor') else v for k,v in row.items()} for row in c['credits']]
        a = self.complete_wire(value)
        self.assertEqual(a['objective'], c['expected']['objective'])
        self.assertEqual(a['policy_facts']['reference_weight'], 3)
        self.assertEqual({p['lot_id']+':'+p['credit_id']:p['candidate_cost'] for p in a['pairs']}, c['expected']['edges'])
        self.assertEqual([p['lot_id']+':'+p['credit_id'] for p in a['pairs'] if p['classification']=='FORCED'], c['expected']['forced'])

    def test_nim_inclusive_leap_window(self):
        c = load('nim-financial-literals.json')['inclusive_leap_date_window']
        value = small_wire()
        value['lots'][0].update(expected_on=c['expected_on'], gross_minor='100')
        value['policy'] = {'early_days': 1, 'late_days': 2}
        value['credits'] = [dict(value['credits'][0], amount_minor='100', **row) for row in c['credits']]
        a = self.complete_wire(value)
        self.assertEqual(a['objective'], c['expected']['objective'])
        self.assertEqual({p['credit_id']:p['signed_day_gap'] for p in a['pairs']}, dict(c['expected']['accepted_gaps'], **c['expected']['rejected_gaps']))
        self.assertEqual([p['credit_id'] for p in a['pairs'] if p['classification']=='FORCED'], ['EARLY'])

    def test_nim_zero_net_one_minor_unit(self):
        c = load('nim-financial-literals.json')['zero_net_and_exact_minor_unit']
        value = small_wire()
        value['lots'] = [dict(value['lots'][0], id=name, **{k:str(v) for k,v in c[key].items()}) for name,key in [('ZERO','zero_lot'),('POS','positive_lot')]]
        value['credits'][0]['amount_minor'] = '1'
        a = self.complete_wire(value)
        self.assertEqual({x['lot_id']:x['net_minor'] for x in a['lot_facts']}, {'POS':'1','ZERO':'0'})
        self.assertEqual(a['objective'], {'cardinality':1,'cost':1})
        self.assertEqual(next(x for x in a['lots'] if x['id']=='ZERO')['state'], 'NO_CREDIT_DUE')

    def test_nim_maximum_aggregate_preserves_17_digits(self):
        c = load('nim-financial-literals.json')['exact_aggregate_above_js_safe_integer']
        value = small_wire()
        value['lots'] = [dict(value['lots'][0], id='L%02d'%i, gross_minor=str(c['each_gross_minor'])) for i in range(16)]
        value['credits'] = []
        a = self.complete_wire(value)
        self.assertEqual(a['totals_by_currency'][0]['gross_minor'], c['expected_aggregate_minor_string'])
        self.assertIs(type(a['totals_by_currency'][0]['gross_minor']), str)

    def test_ambiguous_representative_is_only_member_not_reconciled(self):
        value = small_wire()
        value['lots'] = [dict(value['lots'][0], id=x) for x in ('A','B')]
        value['credits'] = [dict(value['credits'][0], id=x) for x in ('X','Y')]
        a = self.complete_wire(value)
        representative = {(p['lot_id'],p['credit_id']) for p in a['illustrative_matching']}
        self.assertIn(representative, [{('A','X'),('B','Y')},{('A','Y'),('B','X')}])
        self.assertEqual({p['classification'] for p in a['pairs']}, {'OPTIONAL'})
        self.assertEqual({x['state'] for x in a['lots']+a['credits']}, {'AMBIGUOUS_PARTNER'})
        self.assertTrue(all(not x['can_be_unmatched'] for x in a['lots']+a['credits']))
        self.assertEqual(a['totals_by_currency'][0]['forced_pair_minor'], '0')
        self.assertEqual(a['totals_by_currency'][0]['unresolved_lot_minor'], '18000')

    def test_match_status_ambiguity_2_by_1(self):
        value = small_wire()
        value['lots'] = [dict(value['lots'][0], id=x) for x in ('A','B')]
        a = self.complete_wire(value)
        self.assertEqual({x['state'] for x in a['lots']}, {'AMBIGUOUS_MATCH_STATUS'})
        self.assertTrue(all(x['can_be_unmatched'] for x in a['lots']))
        self.assertEqual(a['credits'][0]['state'], 'AMBIGUOUS_PARTNER')
        self.assertFalse(a['credits'][0]['can_be_unmatched'])

    def test_candidate_limit_refuses_no_truncation(self):
        value = small_wire()
        value['lots'] = [dict(value['lots'][0], id='L%02d'%i) for i in range(16)]
        value['credits'] = [dict(value['credits'][0], id='C%02d'%i) for i in range(9)]
        self.invalid_wire(value, 'CANDIDATE_LIMIT')

    def test_empty_and_zero_net_without_credits(self):
        for lots in ([], [dict(small_wire()['lots'][0], gross_minor='0')]):
            with self.subTest(lots=bool(lots)):
                value = small_wire(); value['lots'] = lots; value['credits'] = []
                a = self.complete_wire(value)
                self.assertEqual(a['objective'], {'cardinality':0,'cost':0})
                self.assertEqual(a['pairs'], [])
                self.assertEqual(a['policy_facts']['reference_weight'], 1)

    def test_different_currency_units_and_unused_catalogue_retained(self):
        a = self.complete_wire(base_wire())
        self.assertEqual([x['currency'] for x in a['totals_by_currency']], ['BRL','EUR','USD'])
        self.assertEqual(a['pairs'][2]['rejection_reasons'], ['NO_CREDIT_DUE','CURRENCY','AMOUNT','DATE','REFERENCE'])
