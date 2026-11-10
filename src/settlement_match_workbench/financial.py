"""Synthetic financial domain candidate builder and owned report adapter.

MIT License
Copyright (c) 2026 Lofrano Tecnologia
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import hashlib
import json
import re
from typing import Any, Final

from .solver import solve
from .types import (
    Analysis,
    Edge,
    EdgeAnalysis,
    EdgeClass,
    Limits,
    Objective,
    Pair,
    Problem,
    Result,
    Status,
    VertexAnalysis,
)

__all__ = [
    "Credit",
    "Currency",
    "Lot",
    "Policy",
    "ReportResult",
    "Scenario",
    "analyze",
    "analyze_json",
]

_SCHEMA_VERSION: Final[int] = 1
_MAX_RAW_BYTES: Final[int] = 524_288
_MAX_OUTPUT_BYTES: Final[int] = 524_288
_MAX_JSON_DEPTH: Final[int] = 8
_MAX_JSON_NODES: Final[int] = 4096
_MIN_CURRENCIES: Final[int] = 1
_MAX_CURRENCIES: Final[int] = 8
_MAX_RECORDS_PER_SIDE: Final[int] = 16
_MAX_CANDIDATE_EDGES: Final[int] = 128
_MAX_MINOR_DIGITS: Final[int] = 4
_MAX_POLICY_DAYS: Final[int] = 31
_MAX_MONEY_MINOR: Final[int] = 1_000_000_000_000_000
_MAX_MONEY_BITS: Final[int] = 50
_MAX_AGGREGATE_MINOR: Final[int] = _MAX_RECORDS_PER_SIDE * _MAX_MONEY_MINOR
_MAX_LIMIT_WORK: Final[int] = 100_000_000
_MAX_LIMIT_WORK_BITS: Final[int] = 27
_MAX_CORE_EDGE_COST: Final[int] = 1_000_000
_MAX_CORE_TOTAL_COST: Final[int] = _MAX_RECORDS_PER_SIDE * _MAX_CORE_EDGE_COST
_DIGEST_PREFIX: Final[bytes] = b"SMW-SCENARIO1\n"

_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,31}$", re.ASCII)
_CURRENCY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{3}$", re.ASCII)
_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:20[0-9]{2})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$",
    re.ASCII,
)
_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_./:-]{0,63}$",
    re.ASCII,
)
_MONEY_STR_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0|[1-9][0-9]{0,15})$", re.ASCII)
_AGGREGATE_STR_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:0|[1-9][0-9]{0,16})$",
    re.ASCII,
)
_JSON_INT_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^(?:0|[1-9][0-9]?)$", re.ASCII)

_ROOT_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "scenario_id", "currencies", "policy", "lots", "credits"}
)
_CURRENCY_KEYS: Final[frozenset[str]] = frozenset({"code", "minor_digits"})
_POLICY_KEYS: Final[frozenset[str]] = frozenset({"early_days", "late_days"})
_LOT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "currency",
        "expected_on",
        "gross_minor",
        "fees_minor",
        "refunds_minor",
        "reference",
    }
)
_CREDIT_KEYS: Final[frozenset[str]] = frozenset(
    {"id", "currency", "booked_on", "amount_minor", "reference"}
)


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    minor_digits: int


@dataclass(frozen=True, slots=True)
class Policy:
    early_days: int
    late_days: int


@dataclass(frozen=True, slots=True)
class Lot:
    id: str
    currency: str
    expected_on: str
    gross_minor: int
    fees_minor: int
    refunds_minor: int
    reference: str | None


@dataclass(frozen=True, slots=True)
class Credit:
    id: str
    currency: str
    booked_on: str
    amount_minor: int
    reference: str | None


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    currencies: tuple[Currency, ...] | list[Currency]
    policy: Policy
    lots: tuple[Lot, ...] | list[Lot]
    credits: tuple[Credit, ...] | list[Credit]


@dataclass(frozen=True, slots=True)
class ReportResult:
    status: Status
    code: str
    work_used: int
    json_bytes: bytes


class _BudgetExhausted(Exception):
    """Raised internally when logical work exceeds Limits.max_work."""


class _InvariantError(Exception):
    """Raised internally when an internal or solver invariant fails."""


class _JsonDecodeDefect(Exception):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code: str = code


class _WorkMeter:
    __slots__ = ("max_work", "work")

    def __init__(self, max_work: int) -> None:
        self.max_work: int = max_work
        self.work: int = 0

    def charge(self, units: int = 1) -> None:
        if units < 0:
            raise _InvariantError()
        next_work = self.work + units
        if next_work > self.max_work:
            raise _BudgetExhausted()
        self.work = next_work

    @property
    def remaining(self) -> int:
        rem = self.max_work - self.work
        if rem < 0:
            raise _InvariantError()
        return rem


@dataclass(frozen=True, slots=True)
class _ValidatedLot:
    id: str
    currency: str
    expected_on: str
    expected_ordinal: int
    gross_minor: int
    fees_minor: int
    refunds_minor: int
    net_minor: int
    reference: str | None


@dataclass(frozen=True, slots=True)
class _ValidatedCredit:
    id: str
    currency: str
    booked_on: str
    booked_ordinal: int
    amount_minor: int
    reference: str | None


@dataclass(frozen=True, slots=True)
class _ValidatedScenario:
    scenario_id: str
    currencies: tuple[Currency, ...]
    policy: Policy
    lots: tuple[_ValidatedLot, ...]
    credits: tuple[_ValidatedCredit, ...]


@dataclass(frozen=True, slots=True)
class _PairDraft:
    lot_id: str
    credit_id: str
    signed_day_gap: int
    reference_state: str
    rejection_reasons: tuple[str, ...]
    candidate_cost: int | None


def _has_surrogate(text: str) -> bool:
    if text.isascii():
        return False
    for ch in text:
        code_pt = ord(ch)
        if 0xD800 <= code_pt <= 0xDFFF:
            return True
    return False


def _is_valid_id(value: str) -> bool:
    if len(value) == 0 or len(value) > 32 or not value.isascii():
        return False
    return _ID_RE.fullmatch(value) is not None


def _is_valid_currency_code(value: str) -> bool:
    if len(value) != 3 or not value.isascii():
        return False
    return _CURRENCY_RE.fullmatch(value) is not None


def _is_valid_reference(value: str) -> bool:
    if len(value) == 0 or len(value) > 64 or not value.isascii():
        return False
    return _REF_RE.fullmatch(value) is not None


def _parse_date_ordinal(value: str) -> int | None:
    if len(value) != 10 or not value.isascii() or _DATE_RE.fullmatch(value) is None:
        return None
    year = int(value[0:4])
    month = int(value[5:7])
    day = int(value[8:10])
    if year < 2000 or year > 2099:
        return None
    try:
        return datetime.date(year, month, day).toordinal()
    except ValueError:
        return None


def _parse_wire_money(value: str) -> int | None:
    if len(value) == 0 or len(value) > 16 or not value.isascii():
        return None
    if _MONEY_STR_RE.fullmatch(value) is None:
        return None
    parsed = int(value)
    if parsed < 0 or parsed.bit_length() > _MAX_MONEY_BITS or parsed > _MAX_MONEY_MINOR:
        return None
    return parsed


def _is_valid_sdk_money(value: int) -> bool:
    if value < 0 or value.bit_length() > _MAX_MONEY_BITS or value > _MAX_MONEY_MINOR:
        return False
    return True


def _format_aggregate_money(value: int) -> str:
    if type(value) is not int or value < 0 or value > _MAX_AGGREGATE_MINOR:
        raise _InvariantError()
    text = str(value)
    if _AGGREGATE_STR_RE.fullmatch(text) is None:
        raise _InvariantError()
    return text


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _build_report_result(
    status: Status,
    code: str,
    work_used: int,
    analysis: dict[str, Any] | None,
    max_output_bytes: int = _MAX_OUTPUT_BYTES,
) -> ReportResult:
    if status is not Status.COMPLETE or code != "OK":
        analysis = None
    frame: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": status.value,
        "code": code,
        "work_used": work_used,
        "analysis": analysis,
    }
    raw_bytes = _canonical_json_bytes(frame) + b"\n"
    if len(raw_bytes) > max_output_bytes:
        fallback_frame: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "status": Status.UNKNOWN_BUDGET.value,
            "code": "OUTPUT_LIMIT",
            "work_used": work_used,
            "analysis": None,
        }
        fallback_bytes = _canonical_json_bytes(fallback_frame) + b"\n"
        return ReportResult(
            status=Status.UNKNOWN_BUDGET,
            code="OUTPUT_LIMIT",
            work_used=work_used,
            json_bytes=fallback_bytes,
        )
    return ReportResult(
        status=status,
        code=code,
        work_used=work_used,
        json_bytes=raw_bytes,
    )


def _validate_limits(limits: Limits) -> str | None:
    if type(limits) is not Limits:
        return "TYPE"
    try:
        max_work = limits.max_work
    except AttributeError:
        return "SHAPE"
    if type(max_work) is not int:
        return "TYPE"
    if max_work < 0 or max_work.bit_length() > _MAX_LIMIT_WORK_BITS or max_work > _MAX_LIMIT_WORK:
        return "LIMITS"
    return None


def _count_candidates_phase0(
    policy: Policy,
    lots: list[_ValidatedLot],
    credits: list[_ValidatedCredit],
) -> int:
    early_days = policy.early_days
    late_days = policy.late_days
    candidate_count = 0
    for i in range(len(lots)):
        lot = lots[i]
        if lot.net_minor <= 0:
            continue
        for j in range(len(credits)):
            credit = credits[j]
            if lot.currency != credit.currency:
                continue
            if lot.net_minor != credit.amount_minor:
                continue
            day_gap = credit.booked_ordinal - lot.expected_ordinal
            if day_gap < -early_days or day_gap > late_days:
                continue
            if (
                lot.reference is not None
                and credit.reference is not None
                and lot.reference != credit.reference
            ):
                continue
            candidate_count += 1
    return candidate_count


def _validate_sdk_phase0(scenario: Scenario) -> tuple[_ValidatedScenario | None, str | None]:
    if type(scenario) is not Scenario:
        return None, "TYPE"
    try:
        scenario_id = scenario.scenario_id
        raw_currencies = scenario.currencies
        policy = scenario.policy
        raw_lots = scenario.lots
        raw_credits = scenario.credits
    except AttributeError:
        return None, "SHAPE"

    if (
        type(scenario_id) is not str
        or type(raw_currencies) not in (tuple, list)
        or type(policy) is not Policy
        or type(raw_lots) not in (tuple, list)
        or type(raw_credits) not in (tuple, list)
    ):
        return None, "TYPE"

    if len(raw_currencies) < _MIN_CURRENCIES or len(raw_currencies) > _MAX_CURRENCIES:
        return None, "CURRENCY"
    if len(raw_lots) > _MAX_RECORDS_PER_SIDE or len(raw_credits) > _MAX_RECORDS_PER_SIDE:
        return None, "SIZE"

    if not _is_valid_id(scenario_id):
        return None, "ID"

    seen_currencies: set[str] = set()
    currencies_out: list[Currency] = []
    for i in range(len(raw_currencies)):
        curr = raw_currencies[i]
        if type(curr) is not Currency:
            return None, "TYPE"
        try:
            code = curr.code
            minor_digits = curr.minor_digits
        except AttributeError:
            return None, "SHAPE"
        if type(code) is not str or type(minor_digits) is not int:
            return None, "TYPE"
        if (
            not _is_valid_currency_code(code)
            or minor_digits < 0
            or minor_digits > _MAX_MINOR_DIGITS
            or code in seen_currencies
        ):
            return None, "CURRENCY"
        seen_currencies.add(code)
        currencies_out.append(Currency(code=code, minor_digits=minor_digits))

    try:
        early_days = policy.early_days
        late_days = policy.late_days
    except AttributeError:
        return None, "SHAPE"
    if type(early_days) is not int or type(late_days) is not int:
        return None, "TYPE"
    if (
        early_days < 0
        or early_days > _MAX_POLICY_DAYS
        or late_days < 0
        or late_days > _MAX_POLICY_DAYS
    ):
        return None, "POLICY"
    validated_policy = Policy(early_days=early_days, late_days=late_days)

    seen_lot_ids: set[str] = set()
    lots_out: list[_ValidatedLot] = []
    for i in range(len(raw_lots)):
        lot = raw_lots[i]
        if type(lot) is not Lot:
            return None, "TYPE"
        try:
            lid = lot.id
            lcurr = lot.currency
            expected_on = lot.expected_on
            gross_minor = lot.gross_minor
            fees_minor = lot.fees_minor
            refunds_minor = lot.refunds_minor
            lref = lot.reference
        except AttributeError:
            return None, "SHAPE"
        if (
            type(lid) is not str
            or type(lcurr) is not str
            or type(expected_on) is not str
            or type(gross_minor) is not int
            or type(fees_minor) is not int
            or type(refunds_minor) is not int
            or (lref is not None and type(lref) is not str)
        ):
            return None, "TYPE"
        if not _is_valid_id(lid):
            return None, "ID"
        if lid in seen_lot_ids:
            return None, "DUPLICATE_ID"
        seen_lot_ids.add(lid)
        if lcurr not in seen_currencies:
            return None, "CURRENCY"
        expected_ordinal = _parse_date_ordinal(expected_on)
        if expected_ordinal is None:
            return None, "DATE"
        if (
            not _is_valid_sdk_money(gross_minor)
            or not _is_valid_sdk_money(fees_minor)
            or not _is_valid_sdk_money(refunds_minor)
            or fees_minor + refunds_minor > gross_minor
        ):
            return None, "MONEY"
        if lref is not None and not _is_valid_reference(lref):
            return None, "REFERENCE"
        lots_out.append(
            _ValidatedLot(
                id=lid,
                currency=lcurr,
                expected_on=expected_on,
                expected_ordinal=expected_ordinal,
                gross_minor=gross_minor,
                fees_minor=fees_minor,
                refunds_minor=refunds_minor,
                net_minor=gross_minor - fees_minor - refunds_minor,
                reference=lref,
            )
        )

    seen_credit_ids: set[str] = set()
    credits_out: list[_ValidatedCredit] = []
    for i in range(len(raw_credits)):
        credit = raw_credits[i]
        if type(credit) is not Credit:
            return None, "TYPE"
        try:
            cid = credit.id
            ccurr = credit.currency
            booked_on = credit.booked_on
            amount_minor = credit.amount_minor
            cref = credit.reference
        except AttributeError:
            return None, "SHAPE"
        if (
            type(cid) is not str
            or type(ccurr) is not str
            or type(booked_on) is not str
            or type(amount_minor) is not int
            or (cref is not None and type(cref) is not str)
        ):
            return None, "TYPE"
        if not _is_valid_id(cid):
            return None, "ID"
        if cid in seen_credit_ids:
            return None, "DUPLICATE_ID"
        seen_credit_ids.add(cid)
        if ccurr not in seen_currencies:
            return None, "CURRENCY"
        booked_ordinal = _parse_date_ordinal(booked_on)
        if booked_ordinal is None:
            return None, "DATE"
        if amount_minor < 1 or not _is_valid_sdk_money(amount_minor):
            return None, "MONEY"
        if cref is not None and not _is_valid_reference(cref):
            return None, "REFERENCE"
        credits_out.append(
            _ValidatedCredit(
                id=cid,
                currency=ccurr,
                booked_on=booked_on,
                booked_ordinal=booked_ordinal,
                amount_minor=amount_minor,
                reference=cref,
            )
        )

    if _count_candidates_phase0(validated_policy, lots_out, credits_out) > _MAX_CANDIDATE_EDGES:
        return None, "CANDIDATE_LIMIT"

    return (
        _ValidatedScenario(
            scenario_id=scenario_id,
            currencies=tuple(currencies_out),
            policy=validated_policy,
            lots=tuple(lots_out),
            credits=tuple(credits_out),
        ),
        None,
    )


def _object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in pairs:
        if _has_surrogate(key):
            raise _JsonDecodeDefect("JSON_UTF8")
        if type(val) is str and _has_surrogate(val):
            raise _JsonDecodeDefect("JSON_UTF8")
        if key in out:
            raise _JsonDecodeDefect("JSON_DUPLICATE")
        out[key] = val
    return out


def _parse_json_float(_token: str) -> Any:
    raise _JsonDecodeDefect("TYPE")


def _parse_json_int(token: str) -> int:
    if len(token) == 0 or len(token) > 2 or not token.isascii():
        raise _JsonDecodeDefect("TYPE")
    if _JSON_INT_TOKEN_RE.fullmatch(token) is None:
        raise _JsonDecodeDefect("TYPE")
    return int(token)


def _parse_json_constant(_token: str) -> Any:
    raise _JsonDecodeDefect("JSON_SYNTAX")


def _inspect_json_tree(root: Any) -> str | None:
    # Iterative BFS/DFS over decoded JSON AST enforcing surrogate-free strings,
    # max depth <= 8, and total nodes <= 4096.
    stack: list[tuple[Any, int]] = [(root, 1)]
    node_count = 0
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if depth > _MAX_JSON_DEPTH or node_count > _MAX_JSON_NODES:
            return "JSON_LIMIT"
        node_type = type(node)
        if node_type is str:
            if _has_surrogate(node):
                return "JSON_UTF8"
        elif node_type is dict:
            next_depth = depth + 1
            if len(node) > 0 and next_depth > _MAX_JSON_DEPTH:
                return "JSON_LIMIT"
            for k, v in node.items():
                if _has_surrogate(k):
                    return "JSON_UTF8"
                stack.append((v, next_depth))
        elif node_type is list:
            next_depth = depth + 1
            if len(node) > 0 and next_depth > _MAX_JSON_DEPTH:
                return "JSON_LIMIT"
            for item in node:
                stack.append((item, next_depth))
    return None


def _validate_json_phase0(raw: bytes) -> tuple[_ValidatedScenario | None, str | None]:
    if type(raw) is not bytes:
        return None, "TYPE"
    if len(raw) > _MAX_RAW_BYTES:
        return None, "SIZE"
    if raw.startswith(b"\xef\xbb\xbf"):
        return None, "JSON_UTF8"
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, "JSON_UTF8"

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_object_pairs_hook,
            parse_float=_parse_json_float,
            parse_int=_parse_json_int,
            parse_constant=_parse_json_constant,
        )
    except _JsonDecodeDefect as exc:
        return None, exc.code
    except RecursionError:
        return None, "JSON_LIMIT"
    except json.JSONDecodeError:
        return None, "JSON_SYNTAX"

    tree_err = _inspect_json_tree(decoded)
    if tree_err is not None:
        return None, tree_err

    if type(decoded) is not dict:
        return None, "SHAPE"
    if len(decoded) != len(_ROOT_KEYS) or set(decoded.keys()) != _ROOT_KEYS:
        return None, "SHAPE"

    schema_version = decoded["schema_version"]
    if type(schema_version) is not int:
        return None, "TYPE"
    if schema_version != _SCHEMA_VERSION:
        return None, "SHAPE"

    scenario_id = decoded["scenario_id"]
    raw_currencies = decoded["currencies"]
    raw_policy = decoded["policy"]
    raw_lots = decoded["lots"]
    raw_credits = decoded["credits"]

    if type(scenario_id) is not str:
        return None, "TYPE"
    if (
        type(raw_currencies) is not list
        or type(raw_policy) is not dict
        or type(raw_lots) is not list
        or type(raw_credits) is not list
    ):
        return None, "SHAPE"

    if len(raw_policy) != len(_POLICY_KEYS) or set(raw_policy.keys()) != _POLICY_KEYS:
        return None, "SHAPE"

    if len(raw_currencies) < _MIN_CURRENCIES or len(raw_currencies) > _MAX_CURRENCIES:
        return None, "CURRENCY"
    if len(raw_lots) > _MAX_RECORDS_PER_SIDE or len(raw_credits) > _MAX_RECORDS_PER_SIDE:
        return None, "SIZE"

    if not _is_valid_id(scenario_id):
        return None, "ID"

    seen_currencies: set[str] = set()
    currencies_out: list[Currency] = []
    for i in range(len(raw_currencies)):
        curr = raw_currencies[i]
        if type(curr) is not dict:
            return None, "SHAPE"
        if len(curr) != len(_CURRENCY_KEYS) or set(curr.keys()) != _CURRENCY_KEYS:
            return None, "SHAPE"
        code = curr["code"]
        minor_digits = curr["minor_digits"]
        if type(code) is not str or type(minor_digits) is not int:
            return None, "TYPE"
        if (
            not _is_valid_currency_code(code)
            or minor_digits < 0
            or minor_digits > _MAX_MINOR_DIGITS
            or code in seen_currencies
        ):
            return None, "CURRENCY"
        seen_currencies.add(code)
        currencies_out.append(Currency(code=code, minor_digits=minor_digits))

    early_days = raw_policy["early_days"]
    late_days = raw_policy["late_days"]
    if type(early_days) is not int or type(late_days) is not int:
        return None, "TYPE"
    if (
        early_days < 0
        or early_days > _MAX_POLICY_DAYS
        or late_days < 0
        or late_days > _MAX_POLICY_DAYS
    ):
        return None, "POLICY"
    validated_policy = Policy(early_days=early_days, late_days=late_days)

    seen_lot_ids: set[str] = set()
    lots_out: list[_ValidatedLot] = []
    for i in range(len(raw_lots)):
        lot = raw_lots[i]
        if type(lot) is not dict:
            return None, "SHAPE"
        if len(lot) != len(_LOT_KEYS) or set(lot.keys()) != _LOT_KEYS:
            return None, "SHAPE"
        lid = lot["id"]
        lcurr = lot["currency"]
        expected_on = lot["expected_on"]
        gross_str = lot["gross_minor"]
        fees_str = lot["fees_minor"]
        refunds_str = lot["refunds_minor"]
        lref = lot["reference"]
        if (
            type(lid) is not str
            or type(lcurr) is not str
            or type(expected_on) is not str
            or type(gross_str) is not str
            or type(fees_str) is not str
            or type(refunds_str) is not str
            or (lref is not None and type(lref) is not str)
        ):
            return None, "TYPE"
        if not _is_valid_id(lid):
            return None, "ID"
        if lid in seen_lot_ids:
            return None, "DUPLICATE_ID"
        seen_lot_ids.add(lid)
        if lcurr not in seen_currencies:
            return None, "CURRENCY"
        expected_ordinal = _parse_date_ordinal(expected_on)
        if expected_ordinal is None:
            return None, "DATE"
        gross_minor = _parse_wire_money(gross_str)
        fees_minor = _parse_wire_money(fees_str)
        refunds_minor = _parse_wire_money(refunds_str)
        if (
            gross_minor is None
            or fees_minor is None
            or refunds_minor is None
            or fees_minor + refunds_minor > gross_minor
        ):
            return None, "MONEY"
        if lref is not None and not _is_valid_reference(lref):
            return None, "REFERENCE"
        lots_out.append(
            _ValidatedLot(
                id=lid,
                currency=lcurr,
                expected_on=expected_on,
                expected_ordinal=expected_ordinal,
                gross_minor=gross_minor,
                fees_minor=fees_minor,
                refunds_minor=refunds_minor,
                net_minor=gross_minor - fees_minor - refunds_minor,
                reference=lref,
            )
        )

    seen_credit_ids: set[str] = set()
    credits_out: list[_ValidatedCredit] = []
    for i in range(len(raw_credits)):
        credit = raw_credits[i]
        if type(credit) is not dict:
            return None, "SHAPE"
        if len(credit) != len(_CREDIT_KEYS) or set(credit.keys()) != _CREDIT_KEYS:
            return None, "SHAPE"
        cid = credit["id"]
        ccurr = credit["currency"]
        booked_on = credit["booked_on"]
        amount_str = credit["amount_minor"]
        cref = credit["reference"]
        if (
            type(cid) is not str
            or type(ccurr) is not str
            or type(booked_on) is not str
            or type(amount_str) is not str
            or (cref is not None and type(cref) is not str)
        ):
            return None, "TYPE"
        if not _is_valid_id(cid):
            return None, "ID"
        if cid in seen_credit_ids:
            return None, "DUPLICATE_ID"
        seen_credit_ids.add(cid)
        if ccurr not in seen_currencies:
            return None, "CURRENCY"
        booked_ordinal = _parse_date_ordinal(booked_on)
        if booked_ordinal is None:
            return None, "DATE"
        amount_minor = _parse_wire_money(amount_str)
        if amount_minor is None or amount_minor < 1:
            return None, "MONEY"
        if cref is not None and not _is_valid_reference(cref):
            return None, "REFERENCE"
        credits_out.append(
            _ValidatedCredit(
                id=cid,
                currency=ccurr,
                booked_on=booked_on,
                booked_ordinal=booked_ordinal,
                amount_minor=amount_minor,
                reference=cref,
            )
        )

    if _count_candidates_phase0(validated_policy, lots_out, credits_out) > _MAX_CANDIDATE_EDGES:
        return None, "CANDIDATE_LIMIT"

    return (
        _ValidatedScenario(
            scenario_id=scenario_id,
            currencies=tuple(currencies_out),
            policy=validated_policy,
            lots=tuple(lots_out),
            credits=tuple(credits_out),
        ),
        None,
    )


def _derive_record_state(
    can_be_matched: bool,
    can_be_unmatched: bool,
    possible_partner_ids: tuple[str, ...],
    forced_partner_id: str | None,
    candidate_degree: int,
) -> str:
    if forced_partner_id is not None:
        if not can_be_matched or can_be_unmatched or possible_partner_ids != (forced_partner_id,):
            raise _InvariantError()
        return "FORCED_PAIR"
    if candidate_degree == 0:
        if can_be_matched or not can_be_unmatched or len(possible_partner_ids) != 0:
            raise _InvariantError()
        return "NO_CANDIDATE"
    if len(possible_partner_ids) == 0:
        if can_be_matched or not can_be_unmatched:
            raise _InvariantError()
        return "ALWAYS_UNMATCHED"
    if can_be_matched and can_be_unmatched:
        return "AMBIGUOUS_MATCH_STATUS"
    if can_be_matched and not can_be_unmatched:
        return "AMBIGUOUS_PARTNER"
    raise _InvariantError()


def _execute_phase1(validated: _ValidatedScenario, limits: Limits) -> ReportResult:
    meter = _WorkMeter(limits.max_work)
    try:
        # 1. Copy and canonicalize currencies, policy, lots, credits.
        meter.charge(1)
        currencies_copy: list[Currency] = []
        for i in range(len(validated.currencies)):
            meter.charge(1)
            currencies_copy.append(validated.currencies[i])
        if len(currencies_copy) > 0:
            meter.charge(len(currencies_copy) * len(currencies_copy))
            currencies_copy.sort(key=lambda item: item.code)

        normalized_currencies: list[dict[str, Any]] = []
        for i in range(len(currencies_copy)):
            meter.charge(1)
            c = currencies_copy[i]
            normalized_currencies.append({"code": c.code, "minor_digits": c.minor_digits})

        meter.charge(1)
        early_days = validated.policy.early_days
        late_days = validated.policy.late_days
        normalized_policy: dict[str, int] = {
            "early_days": early_days,
            "late_days": late_days,
        }

        lots_copy: list[_ValidatedLot] = []
        for i in range(len(validated.lots)):
            meter.charge(1)
            lots_copy.append(validated.lots[i])
        if len(lots_copy) > 0:
            meter.charge(len(lots_copy) * len(lots_copy))
            lots_copy.sort(key=lambda item: item.id)

        normalized_lots: list[dict[str, Any]] = []
        lot_facts: list[dict[str, Any]] = []
        eligible_lot_ids: list[str] = []
        lot_by_id: dict[str, _ValidatedLot] = {}
        for i in range(len(lots_copy)):
            meter.charge(1)
            lot = lots_copy[i]
            lot_by_id[lot.id] = lot
            normalized_lots.append(
                {
                    "id": lot.id,
                    "currency": lot.currency,
                    "expected_on": lot.expected_on,
                    "gross_minor": str(lot.gross_minor),
                    "fees_minor": str(lot.fees_minor),
                    "refunds_minor": str(lot.refunds_minor),
                    "reference": lot.reference,
                }
            )
            no_credit_due = lot.net_minor == 0
            lot_facts.append(
                {
                    "lot_id": lot.id,
                    "net_minor": str(lot.net_minor),
                    "no_credit_due": no_credit_due,
                }
            )
            if not no_credit_due:
                eligible_lot_ids.append(lot.id)

        credits_copy: list[_ValidatedCredit] = []
        for i in range(len(validated.credits)):
            meter.charge(1)
            credits_copy.append(validated.credits[i])
        if len(credits_copy) > 0:
            meter.charge(len(credits_copy) * len(credits_copy))
            credits_copy.sort(key=lambda item: item.id)

        normalized_credits: list[dict[str, Any]] = []
        credit_ids: list[str] = []
        credit_by_id: dict[str, _ValidatedCredit] = {}
        for i in range(len(credits_copy)):
            meter.charge(1)
            credit = credits_copy[i]
            credit_by_id[credit.id] = credit
            credit_ids.append(credit.id)
            normalized_credits.append(
                {
                    "id": credit.id,
                    "currency": credit.currency,
                    "booked_on": credit.booked_on,
                    "amount_minor": str(credit.amount_minor),
                    "reference": credit.reference,
                }
            )

        normalized_input: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "scenario_id": validated.scenario_id,
            "currencies": normalized_currencies,
            "policy": normalized_policy,
            "lots": normalized_lots,
            "credits": normalized_credits,
        }
        canonical_input_bytes = _canonical_json_bytes(normalized_input)
        meter.charge(len(_DIGEST_PREFIX) + len(canonical_input_bytes))
        input_digest = hashlib.sha256(_DIGEST_PREFIX + canonical_input_bytes).hexdigest()

        # 2. Policy scalarization facts and full pair scan.
        meter.charge(1)
        n_eligible_lots = len(eligible_lot_ids)
        n_credits = len(credit_ids)
        m_bound = min(n_eligible_lots, n_credits)
        max_day_gap = max(early_days, late_days)
        reference_weight = m_bound * max_day_gap + 1

        policy_facts: dict[str, int] = {
            "eligible_lot_count": n_eligible_lots,
            "credit_count": n_credits,
            "max_day_gap": max_day_gap,
            "reference_weight": reference_weight,
        }

        pair_drafts: list[_PairDraft] = []
        candidate_edges: list[Edge] = []
        candidate_cost_by_key: dict[tuple[str, str], int] = {}
        lot_candidate_degree: dict[str, int] = {lot.id: 0 for lot in lots_copy}
        credit_candidate_degree: dict[str, int] = {credit.id: 0 for credit in credits_copy}

        for i in range(len(lots_copy)):
            lot = lots_copy[i]
            for j in range(len(credits_copy)):
                meter.charge(1)
                credit = credits_copy[j]
                signed_day_gap = credit.booked_ordinal - lot.expected_ordinal
                if lot.reference is None or credit.reference is None:
                    reference_state = "MISSING"
                elif lot.reference == credit.reference:
                    reference_state = "MATCHED"
                else:
                    reference_state = "CONFLICT"

                reasons: list[str] = []
                if lot.net_minor == 0:
                    reasons.append("NO_CREDIT_DUE")
                if lot.currency != credit.currency:
                    reasons.append("CURRENCY")
                if lot.net_minor != credit.amount_minor:
                    reasons.append("AMOUNT")
                if signed_day_gap < -early_days or signed_day_gap > late_days:
                    reasons.append("DATE")
                if reference_state == "CONFLICT":
                    reasons.append("REFERENCE")

                if len(reasons) == 0:
                    meter.charge(1)
                    missing_penalty = 1 if reference_state == "MISSING" else 0
                    cost = reference_weight * missing_penalty + abs(signed_day_gap)
                    if cost < 0 or cost > _MAX_CORE_EDGE_COST:
                        raise _InvariantError()
                    key = (lot.id, credit.id)
                    if key in candidate_cost_by_key:
                        raise _InvariantError()
                    candidate_cost_by_key[key] = cost
                    candidate_edges.append(Edge(left_id=lot.id, right_id=credit.id, cost=cost))
                    lot_candidate_degree[lot.id] += 1
                    credit_candidate_degree[credit.id] += 1
                    pair_drafts.append(
                        _PairDraft(
                            lot_id=lot.id,
                            credit_id=credit.id,
                            signed_day_gap=signed_day_gap,
                            reference_state=reference_state,
                            rejection_reasons=(),
                            candidate_cost=cost,
                        )
                    )
                else:
                    pair_drafts.append(
                        _PairDraft(
                            lot_id=lot.id,
                            credit_id=credit.id,
                            signed_day_gap=signed_day_gap,
                            reference_state=reference_state,
                            rejection_reasons=tuple(reasons),
                            candidate_cost=None,
                        )
                    )

        if len(candidate_edges) > _MAX_CANDIDATE_EDGES:
            raise _InvariantError()

        # 3. Delegate to the genuine bipartite matching solver with remaining work.
        problem = Problem(
            left_ids=tuple(eligible_lot_ids),
            right_ids=tuple(credit_ids),
            edges=tuple(candidate_edges),
        )
        core_result = solve(problem, Limits(max_work=meter.remaining))
        if type(core_result) is not Result:
            raise _InvariantError()
        if type(core_result.work_used) is not int or core_result.work_used < 0:
            raise _InvariantError()
        meter.charge(core_result.work_used)

        if core_result.status is Status.UNKNOWN_BUDGET:
            return _build_report_result(
                status=Status.UNKNOWN_BUDGET,
                code="WORK_LIMIT",
                work_used=meter.work,
                analysis=None,
            )
        if (
            core_result.status is not Status.COMPLETE
            or core_result.code != "OK"
            or type(core_result.analysis) is not Analysis
        ):
            raise _InvariantError()

        # 4. Direct replay and verification of solver output.
        core_analysis = core_result.analysis
        if type(core_analysis.objective) is not Objective:
            raise _InvariantError()
        base_k = core_analysis.objective.cardinality
        base_c = core_analysis.objective.cost
        if (
            type(base_k) is not int
            or type(base_c) is not int
            or base_k < 0
            or base_k > m_bound
            or base_c < 0
            or base_c > _MAX_CORE_TOTAL_COST
        ):
            raise _InvariantError()

        if (
            type(core_analysis.representative) is not tuple
            or len(core_analysis.representative) != base_k
        ):
            raise _InvariantError()

        rep_left_seen: set[str] = set()
        rep_right_seen: set[str] = set()
        rep_edge_keys: set[tuple[str, str]] = set()
        rep_cost_sum = 0
        prev_rep_key: tuple[str, str] | None = None
        illustrative_matching: list[dict[str, str]] = []

        for i in range(len(core_analysis.representative)):
            meter.charge(1)
            pair = core_analysis.representative[i]
            if type(pair) is not Pair:
                raise _InvariantError()
            if type(pair.left_id) is not str or type(pair.right_id) is not str:
                raise _InvariantError()
            key = (pair.left_id, pair.right_id)
            if prev_rep_key is not None and key <= prev_rep_key:
                raise _InvariantError()
            prev_rep_key = key
            if pair.left_id in rep_left_seen or pair.right_id in rep_right_seen:
                raise _InvariantError()
            if key not in candidate_cost_by_key:
                raise _InvariantError()
            rep_left_seen.add(pair.left_id)
            rep_right_seen.add(pair.right_id)
            rep_edge_keys.add(key)
            rep_cost_sum += candidate_cost_by_key[key]
            illustrative_matching.append({"lot_id": pair.left_id, "credit_id": pair.right_id})

        if len(rep_edge_keys) != base_k or rep_cost_sum != base_c:
            raise _InvariantError()

        if (
            type(core_analysis.edges) is not tuple
            or len(core_analysis.edges) != len(candidate_edges)
        ):
            raise _InvariantError()

        edge_analysis_by_key: dict[tuple[str, str], EdgeAnalysis] = {}
        forced_pairs: list[tuple[_ValidatedLot, _ValidatedCredit]] = []
        for i in range(len(core_analysis.edges)):
            meter.charge(1)
            ea = core_analysis.edges[i]
            ce = candidate_edges[i]
            if type(ea) is not EdgeAnalysis:
                raise _InvariantError()
            if (
                ea.left_id != ce.left_id
                or ea.right_id != ce.right_id
                or ea.cost != ce.cost
                or type(ea.classification) is not EdgeClass
                or type(ea.probe_objective) is not Objective
            ):
                raise _InvariantError()
            pk = ea.probe_objective.cardinality
            pc = ea.probe_objective.cost
            if (
                type(pk) is not int
                or type(pc) is not int
                or pk < 0
                or pk > m_bound
                or pc < 0
                or pc > _MAX_CORE_TOTAL_COST
            ):
                raise _InvariantError()
            key = (ea.left_id, ea.right_id)
            if key in rep_edge_keys and ea.classification is EdgeClass.GLOBALLY_EXCLUDED:
                raise _InvariantError()
            if ea.classification is EdgeClass.FORCED:
                if key not in rep_edge_keys:
                    raise _InvariantError()
                forced_pairs.append((lot_by_id[ea.left_id], credit_by_id[ea.right_id]))
            edge_analysis_by_key[key] = ea

        if (
            type(core_analysis.left) is not tuple
            or len(core_analysis.left) != len(eligible_lot_ids)
            or type(core_analysis.right) is not tuple
            or len(core_analysis.right) != len(credit_ids)
        ):
            raise _InvariantError()

        left_va_by_id: dict[str, VertexAnalysis] = {}
        for i in range(len(core_analysis.left)):
            meter.charge(1)
            va = core_analysis.left[i]
            expected_id = eligible_lot_ids[i]
            if type(va) is not VertexAnalysis or va.id != expected_id:
                raise _InvariantError()
            if (
                type(va.can_be_matched) is not bool
                or type(va.can_be_unmatched) is not bool
                or type(va.possible_partner_ids) is not tuple
                or (va.forced_partner_id is not None and type(va.forced_partner_id) is not str)
            ):
                raise _InvariantError()
            if va.id in rep_left_seen:
                if type(va.unmatched_probe_objective) is not Objective:
                    raise _InvariantError()
            else:
                if va.unmatched_probe_objective is not None or not va.can_be_unmatched:
                    raise _InvariantError()
            left_va_by_id[va.id] = va

        right_va_by_id: dict[str, VertexAnalysis] = {}
        for i in range(len(core_analysis.right)):
            meter.charge(1)
            va = core_analysis.right[i]
            expected_id = credit_ids[i]
            if type(va) is not VertexAnalysis or va.id != expected_id:
                raise _InvariantError()
            if (
                type(va.can_be_matched) is not bool
                or type(va.can_be_unmatched) is not bool
                or type(va.possible_partner_ids) is not tuple
                or (va.forced_partner_id is not None and type(va.forced_partner_id) is not str)
            ):
                raise _InvariantError()
            if va.id in rep_right_seen:
                if type(va.unmatched_probe_objective) is not Objective:
                    raise _InvariantError()
            else:
                if va.unmatched_probe_objective is not None or not va.can_be_unmatched:
                    raise _InvariantError()
            right_va_by_id[va.id] = va

        # 5. Build pair, lot, credit, and currency-total output records.
        pairs_output: list[dict[str, Any]] = []
        for i in range(len(pair_drafts)):
            meter.charge(1)
            draft = pair_drafts[i]
            if draft.candidate_cost is None:
                pairs_output.append(
                    {
                        "lot_id": draft.lot_id,
                        "credit_id": draft.credit_id,
                        "signed_day_gap": draft.signed_day_gap,
                        "reference_state": draft.reference_state,
                        "rejection_reasons": list(draft.rejection_reasons),
                        "candidate_cost": None,
                        "classification": None,
                        "probe_kind": None,
                        "probe_objective": None,
                    }
                )
            else:
                key = (draft.lot_id, draft.credit_id)
                ea = edge_analysis_by_key.get(key)
                if ea is None:
                    raise _InvariantError()
                probe_kind = "EXCLUDE" if key in rep_edge_keys else "FORCE"
                pairs_output.append(
                    {
                        "lot_id": draft.lot_id,
                        "credit_id": draft.credit_id,
                        "signed_day_gap": draft.signed_day_gap,
                        "reference_state": draft.reference_state,
                        "rejection_reasons": [],
                        "candidate_cost": draft.candidate_cost,
                        "classification": ea.classification.value,
                        "probe_kind": probe_kind,
                        "probe_objective": {
                            "cardinality": ea.probe_objective.cardinality,
                            "cost": ea.probe_objective.cost,
                        },
                    }
                )

        lots_output: list[dict[str, Any]] = []
        for i in range(len(lots_copy)):
            meter.charge(1)
            lot = lots_copy[i]
            if lot.net_minor == 0:
                lots_output.append(
                    {
                        "id": lot.id,
                        "state": "NO_CREDIT_DUE",
                        "can_be_matched": False,
                        "can_be_unmatched": True,
                        "possible_partner_ids": [],
                        "forced_partner_id": None,
                        "unmatched_probe_objective": None,
                    }
                )
            else:
                va = left_va_by_id.get(lot.id)
                if va is None:
                    raise _InvariantError()
                state = _derive_record_state(
                    can_be_matched=va.can_be_matched,
                    can_be_unmatched=va.can_be_unmatched,
                    possible_partner_ids=va.possible_partner_ids,
                    forced_partner_id=va.forced_partner_id,
                    candidate_degree=lot_candidate_degree[lot.id],
                )
                unmatched_probe_dict = (
                    None
                    if va.unmatched_probe_objective is None
                    else {
                        "cardinality": va.unmatched_probe_objective.cardinality,
                        "cost": va.unmatched_probe_objective.cost,
                    }
                )
                lots_output.append(
                    {
                        "id": va.id,
                        "state": state,
                        "can_be_matched": va.can_be_matched,
                        "can_be_unmatched": va.can_be_unmatched,
                        "possible_partner_ids": list(va.possible_partner_ids),
                        "forced_partner_id": va.forced_partner_id,
                        "unmatched_probe_objective": unmatched_probe_dict,
                    }
                )

        credits_output: list[dict[str, Any]] = []
        for i in range(len(credits_copy)):
            meter.charge(1)
            credit = credits_copy[i]
            va = right_va_by_id.get(credit.id)
            if va is None:
                raise _InvariantError()
            state = _derive_record_state(
                can_be_matched=va.can_be_matched,
                can_be_unmatched=va.can_be_unmatched,
                possible_partner_ids=va.possible_partner_ids,
                forced_partner_id=va.forced_partner_id,
                candidate_degree=credit_candidate_degree[credit.id],
            )
            unmatched_probe_dict = (
                None
                if va.unmatched_probe_objective is None
                else {
                    "cardinality": va.unmatched_probe_objective.cardinality,
                    "cost": va.unmatched_probe_objective.cost,
                }
            )
            credits_output.append(
                {
                    "id": va.id,
                    "state": state,
                    "can_be_matched": va.can_be_matched,
                    "can_be_unmatched": va.can_be_unmatched,
                    "possible_partner_ids": list(va.possible_partner_ids),
                    "forced_partner_id": va.forced_partner_id,
                    "unmatched_probe_objective": unmatched_probe_dict,
                }
            )

        gross_by_curr: dict[str, int] = {c.code: 0 for c in currencies_copy}
        fees_by_curr: dict[str, int] = {c.code: 0 for c in currencies_copy}
        refunds_by_curr: dict[str, int] = {c.code: 0 for c in currencies_copy}
        net_by_curr: dict[str, int] = {c.code: 0 for c in currencies_copy}
        credit_by_curr: dict[str, int] = {c.code: 0 for c in currencies_copy}
        forced_by_curr: dict[str, int] = {c.code: 0 for c in currencies_copy}

        for i in range(len(lots_copy)):
            lot = lots_copy[i]
            gross_by_curr[lot.currency] += lot.gross_minor
            fees_by_curr[lot.currency] += lot.fees_minor
            refunds_by_curr[lot.currency] += lot.refunds_minor
            net_by_curr[lot.currency] += lot.net_minor

        for i in range(len(credits_copy)):
            credit = credits_copy[i]
            credit_by_curr[credit.currency] += credit.amount_minor

        forced_lot_seen: set[str] = set()
        forced_credit_seen: set[str] = set()
        for i in range(len(forced_pairs)):
            f_lot, f_credit = forced_pairs[i]
            if (
                f_lot.id in forced_lot_seen
                or f_credit.id in forced_credit_seen
                or f_lot.currency != f_credit.currency
                or f_lot.net_minor != f_credit.amount_minor
            ):
                raise _InvariantError()
            forced_lot_seen.add(f_lot.id)
            forced_credit_seen.add(f_credit.id)
            forced_by_curr[f_lot.currency] += f_lot.net_minor

        totals_by_currency: list[dict[str, str]] = []
        for i in range(len(currencies_copy)):
            meter.charge(1)
            code = currencies_copy[i].code
            gross_val = gross_by_curr[code]
            fees_val = fees_by_curr[code]
            refunds_val = refunds_by_curr[code]
            net_val = net_by_curr[code]
            credit_val = credit_by_curr[code]
            forced_val = forced_by_curr[code]
            if gross_val - fees_val - refunds_val != net_val:
                raise _InvariantError()
            unresolved_lot_val = net_val - forced_val
            unresolved_credit_val = credit_val - forced_val
            if unresolved_lot_val < 0 or unresolved_credit_val < 0:
                raise _InvariantError()
            totals_by_currency.append(
                {
                    "currency": code,
                    "gross_minor": _format_aggregate_money(gross_val),
                    "fees_minor": _format_aggregate_money(fees_val),
                    "refunds_minor": _format_aggregate_money(refunds_val),
                    "net_minor": _format_aggregate_money(net_val),
                    "credit_minor": _format_aggregate_money(credit_val),
                    "forced_pair_minor": _format_aggregate_money(forced_val),
                    "unresolved_lot_minor": _format_aggregate_money(unresolved_lot_val),
                    "unresolved_credit_minor": _format_aggregate_money(unresolved_credit_val),
                }
            )

        meter.charge(1)
        analysis_payload: dict[str, Any] = {
            "input": normalized_input,
            "input_digest": input_digest,
            "policy_facts": policy_facts,
            "lot_facts": lot_facts,
            "pairs": pairs_output,
            "objective": {"cardinality": base_k, "cost": base_c},
            "illustrative_matching": illustrative_matching,
            "lots": lots_output,
            "credits": credits_output,
            "totals_by_currency": totals_by_currency,
        }
        return _build_report_result(
            status=Status.COMPLETE,
            code="OK",
            work_used=meter.work,
            analysis=analysis_payload,
        )
    except _BudgetExhausted:
        return _build_report_result(
            status=Status.UNKNOWN_BUDGET,
            code="WORK_LIMIT",
            work_used=meter.work,
            analysis=None,
        )
    except _InvariantError:
        return _build_report_result(
            status=Status.INTERNAL_ERROR,
            code="INVARIANT",
            work_used=meter.work,
            analysis=None,
        )


def analyze(scenario: Scenario, limits: Limits = Limits()) -> ReportResult:
    """Validate a synthetic financial Scenario, solve candidate matching, and emit an owned JSON report."""
    if type(scenario) is not Scenario or type(limits) is not Limits:
        return _build_report_result(
            status=Status.INVALID_INPUT,
            code="TYPE",
            work_used=0,
            analysis=None,
        )
    limits_err = _validate_limits(limits)
    if limits_err is not None:
        return _build_report_result(
            status=Status.INVALID_INPUT,
            code=limits_err,
            work_used=0,
            analysis=None,
        )
    validated, err_code = _validate_sdk_phase0(scenario)
    if err_code is not None or validated is None:
        return _build_report_result(
            status=Status.INVALID_INPUT,
            code=err_code or "SHAPE",
            work_used=0,
            analysis=None,
        )
    return _execute_phase1(validated, limits)


def analyze_json(raw: bytes, limits: Limits = Limits()) -> ReportResult:
    """Validate raw UTF-8 JSON bytes, solve candidate matching, and emit an owned JSON report."""
    if type(limits) is not Limits:
        return _build_report_result(
            status=Status.INVALID_INPUT,
            code="TYPE",
            work_used=0,
            analysis=None,
        )
    limits_err = _validate_limits(limits)
    if limits_err is not None:
        return _build_report_result(
            status=Status.INVALID_INPUT,
            code=limits_err,
            work_used=0,
            analysis=None,
        )
    validated, err_code = _validate_json_phase0(raw)
    if err_code is not None or validated is None:
        return _build_report_result(
            status=Status.INVALID_INPUT,
            code=err_code or "SHAPE",
            work_used=0,
            analysis=None,
        )
    return _execute_phase1(validated, limits)
