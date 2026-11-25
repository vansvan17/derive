"""Checking a learner's answer to one step of a derivation chain.

Every kind except a free-text proof is decided here, by the machine, with no
judgement calls: a number, a list, a choice, a formula tested on many values,
or a counterexample tested against a stated property.

The formula language is deliberately tiny. Text typed by the learner is parsed
into a syntax tree and only arithmetic is ever evaluated; nothing typed in the
browser can reach Python's own eval.
"""
from __future__ import annotations
import ast
from fractions import Fraction
import math
import random
import re

MAX_ABS = 10 ** 60          # values larger than this are refused, not computed
MAX_EXPONENT = 200


class CheckError(ValueError):
    """The answer could not be used; the message is shown to the learner."""


class Unreadable(CheckError):
    """The text is not arithmetic at all (as opposed to arithmetic that breaks at some value)."""


def _is_prime(n):
    if n < 2:
        return False
    return all(n % d for d in range(2, math.isqrt(n) + 1))


def _comb(n, k):
    if k < 0 or n < 0 or k > n:
        return 0
    return math.comb(n, k)


def _pow(a, b, m=None):
    if m is not None:
        if m == 0:
            raise CheckError('A modulus cannot be zero.')
        return pow(int(a), int(b), int(m))
    return _power(a, b)


def _power(a, b):
    if isinstance(b, Fraction) and b.denominator != 1:
        raise CheckError('Only whole-number exponents are understood.')
    b = int(b)
    if abs(b) > MAX_EXPONENT:
        raise CheckError('That exponent is too large to evaluate.')
    if b < 0 and a == 0:
        raise CheckError('Zero cannot be raised to a negative power.')
    return Fraction(a) ** b


# Functions a formula or an authored property may call.
FUNCTIONS = {
    'gcd': lambda a, b: math.gcd(int(a), int(b)),
    'lcm': lambda a, b: math.lcm(int(a), int(b)),
    'min': min, 'max': max, 'abs': abs,
    'C': _comb, 'comb': _comb, 'choose': _comb,
    'fact': lambda n: math.factorial(int(n)), 'factorial': lambda n: math.factorial(int(n)),
    'floor': lambda x: math.floor(x), 'ceil': lambda x: math.ceil(x),
    'pow': _pow, 'isprime': _is_prime,
}


def _guard(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, Fraction)) and abs(value) > MAX_ABS:
        raise CheckError('That grows too large to evaluate.')
    return value


def _evaluate(node, names, logic):
    """Walk the syntax tree. `logic` also allows comparisons and and/or/not (authored properties only)."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, names, logic)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) and logic:
            return node.value
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        raise Unreadable('Use whole numbers only.')
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise Unreadable(f'"{node.id}" is not a quantity in this question.')
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, names, logic)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.Not) and logic:
            return not value
        raise Unreadable('That operator is not understood.')
    if isinstance(node, ast.BinOp):
        a, b = _evaluate(node.left, names, logic), _evaluate(node.right, names, logic)
        op = node.op
        if isinstance(op, ast.Add):
            return _guard(a + b)
        if isinstance(op, ast.Sub):
            return _guard(a - b)
        if isinstance(op, ast.Mult):
            return _guard(a * b)
        if isinstance(op, ast.Pow):
            return _guard(_power(a, b))
        if isinstance(op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if b == 0:
                raise CheckError('That divides by zero for some values.')
            if isinstance(op, ast.Div):
                return Fraction(a) / Fraction(b)
            if isinstance(op, ast.FloorDiv):
                return math.floor(Fraction(a) / Fraction(b))
            return a % b
        raise Unreadable('That operator is not understood.')
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
            raise Unreadable('That function is not understood. Available: gcd, lcm, min, max, abs, C(n,k), fact, floor, ceil.')
        args = [_evaluate(a, names, logic) for a in node.args]
        try:
            return _guard(FUNCTIONS[node.func.id](*args))
        except CheckError:
            raise
        except (TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
            raise CheckError('That function cannot take those values.') from exc
    if logic and isinstance(node, ast.Compare):
        left = _evaluate(node.left, names, logic)
        for op, right_node in zip(node.ops, node.comparators):
            right = _evaluate(right_node, names, logic)
            ok = {ast.Eq: left == right, ast.NotEq: left != right, ast.Lt: left < right, ast.LtE: left <= right,
                  ast.Gt: left > right, ast.GtE: left >= right}.get(type(op))
            if ok is None:
                raise Unreadable('That comparison is not understood.')
            if not ok:
                return False
            left = right
        return True
    if logic and isinstance(node, ast.BoolOp):
        values = [_evaluate(v, names, logic) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    raise Unreadable('That is not arithmetic this page can read.')


def _prepare(text):
    """Accept the way people write maths: ^ for powers, 2n and n(n+1) for products."""
    text = text.strip().replace('^', '**').replace('×', '*').replace('·', '*').replace('−', '-').replace('÷', '/')
    if len(text) > 300:
        raise Unreadable('That is too long to be a formula.')
    text = re.sub(r'(\d)\s*([A-Za-z(])', r'\1*\2', text)                      # 2n, 2(n+1)
    text = re.sub(r'\)\s*([A-Za-z0-9(])', r')*\1', text)                      # (n+1)(n+2), (n+1)n
    names = '|'.join(sorted(FUNCTIONS, key=len, reverse=True))
    text = re.sub(rf'\b(?!(?:{names})\b)([A-Za-z])\s*\(', r'\1*(', text)      # n(n+1) but not gcd(
    return text


def evaluate(text, names, logic=False, prepared=False):
    try:
        # Authored properties are already plain Python-style arithmetic; only typed formulas are tidied up.
        tree = ast.parse(text if prepared or logic else _prepare(text), mode='eval')
    except SyntaxError as exc:
        raise Unreadable('That could not be read as a formula. Check the brackets and operators.') from exc
    return _evaluate(tree, names, logic)


def _numbers(raw):
    """Whole numbers typed in any reasonable way: '1, 2, 3', '1 2 3', '{1,2,3}', 'a=2, p=4'."""
    return [int(x) for x in re.findall(r'(?<![\w.])-?\d+', str(raw))]


def _fraction(raw):
    text = str(raw).strip().replace('−', '-')
    if not re.fullmatch(r'-?\d+(\s*/\s*-?\d+)?', text):
        raise CheckError('Type a whole number, or a fraction like 3/4.')
    try:
        return Fraction(text.replace(' ', ''))
    except ZeroDivisionError as exc:
        raise CheckError('A fraction cannot have zero underneath.') from exc


def sample_points(variables, count=40, seed=20261124):
    """Small values first (where wrong formulas usually differ), then random ones in range."""
    rng = random.Random(seed)
    names = list(variables)
    points = []
    for offset in range(4):
        points.append({n: min(variables[n][1], variables[n][0] + offset) for n in names})
    while len(points) < count:
        points.append({n: rng.randint(*variables[n]) for n in names})
    return points


def _partial(right, values, answer, where):
    """How much of a wrong list is right: "4 of your 6 entries are right". It says how many, never which."""
    if len(values) < 2:
        return ''
    note = f'{right} of your {len(values)} entries are right{where}.'
    if len(values) < len(answer):
        note += ' Some are missing.'
    elif len(values) > len(answer):
        note += ' You have listed too many.'
    return note


def check(step, raw):
    """Return (correct, message). The message never contains the answer."""
    kind = step['kind']
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise CheckError('Write an answer first.')
    if kind == 'number':
        value = _fraction(raw)
        if 'mod' in step:
            if value.denominator != 1:
                raise CheckError('Give a whole-number residue.')
            return int(value) % step['mod'] == step['answer'] % step['mod'], ''
        return value == Fraction(str(step['answer'])), ''
    if kind == 'list':
        values = _numbers(raw)
        if not values and str(raw).strip().lower() not in ('none', 'empty', '{}', '[]'):
            raise CheckError('List the numbers, separated by commas or spaces.')
        answer = list(step['answer'])
        if step.get('ordered'):
            return values == answer, '' if values == answer else _partial(sum(1 for a, b in zip(values, answer) if a == b), values, answer, ' and in the right place')
        if len(values) != len(set(values)) and not step.get('multiset'):
            return False, 'You listed a value twice.'
        if sorted(values) == sorted(answer):
            return True, ''
        left = list(answer)
        right = sum(1 for v in values if v in left and (left.remove(v) or True))
        return False, _partial(right, values, answer, '')
    if kind == 'choice':
        try:
            index = int(raw)
        except (TypeError, ValueError) as exc:
            raise CheckError('Pick one of the options.') from exc
        return index == step['answer'], ''
    if kind == 'formula':
        prepared = _prepare(str(raw))
        reference = _prepare(step['answer'])
        for point in sample_points(step['vars']):
            expected = evaluate(reference, point, prepared=True)
            try:
                got = evaluate(prepared, point, prepared=True)
            except Unreadable:
                raise
            except CheckError:
                # A formula that breaks only at some values is wrong there, not unreadable.
                return False, 'It is not defined for ' + ', '.join(f'{k} = {v}' for k, v in point.items()) + '.'
            if Fraction(got) != Fraction(expected):
                # Saying where it fails is a prompt to test small cases, not a giveaway.
                return False, 'It disagrees with the true value at ' + ', '.join(f'{k} = {v}' for k, v in point.items()) + '.'
        return True, ''
    if kind == 'counterexample':
        names = step['vars']
        values = _numbers(raw)
        if len(values) != len(names):
            raise CheckError('Give ' + ', '.join(names) + f' ({len(names)} whole number{"s" if len(names) != 1 else ""}).')
        point = dict(zip(names, values))
        for name, (low, high) in step.get('bounds', {}).items():
            if not low <= point[name] <= high:
                raise CheckError(f'Keep {name} between {low} and {high}.')
        if 'require' in step and not evaluate(step['require'], point, logic=True):
            return False, step.get('require_message', 'Those values do not meet the conditions in the question.')
        return bool(evaluate(step['property'], point, logic=True)), ''
    raise CheckError('This step is not checked here.')
