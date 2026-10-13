"""Versioned deterministic coding micro-suite. Never execute model-produced code.

These fixtures measure bounded code comprehension and structured workflow
planning, not full repository-level agent success or general coding ability.
"""
import json

SUITE_NAME = 'mlx-nobby-coding-v1'
CODING_TASKS = (
    {'id': 'php', 'category': 'php', 'prompt': 'PHP 8: $a = ["x" => 1]; $b = ["x" => 2, "y" => 3]; What is $a + $b? Return JSON only with keys x and y.', 'expected': {'x': 1, 'y': 3}},
    {'id': 'javascript', 'category': 'javascript', 'prompt': 'JavaScript: const x = [1,2,3].filter(n => n > 1).map(n => n * 2); Return JSON only: {"result": x}.', 'expected': {'result': [4, 6]}},
    {'id': 'python', 'category': 'python', 'prompt': 'Python: a = [[0]] * 3; a[0].append(1). Return JSON only: {"result": a}.', 'expected': {'result': [[0, 1], [0, 1], [0, 1]]}},
    {'id': 'comprehension', 'category': 'comprehension', 'prompt': 'Python: def f(xs): return [x for i,x in enumerate(xs) if x not in xs[:i]]\nFor f([2,1,2,3,1]), return JSON only: {"result": [...]}.', 'expected': {'result': [2, 1, 3]}},
    {'id': 'refactoring', 'category': 'refactoring', 'prompt': 'Refactor Python: def f(xs): return sum([x*x for x in xs])\nAvoid the temporary list without changing behavior. Return JSON only: {"expression": "..."}, the replacement return expression.', 'expected': {'expression': 'sum(x*x for x in xs)'}},
    {'id': 'bugfix', 'category': 'bugfix', 'prompt': 'Python bug: def add(x, out=[]): out.append(x); return out\nRepeated calls share state. Return JSON only: {"default": null, "initialize_if_none": true}.', 'expected': {'default': None, 'initialize_if_none': True}},
    {'id': 'tool_call', 'category': 'tool_calling', 'prompt': 'Available tool: read_file(path: string). You need to inspect src/main.py before editing. Return one JSON tool request only: {"name": "read_file", "arguments": {"path": "src/main.py"}}.', 'expected': {'name': 'read_file', 'arguments': {'path': 'src/main.py'}}},
    {'id': 'agent', 'category': 'agent_workflow', 'prompt': 'Order these development actions safely: test, inspect, patch. Return JSON only: {"steps": [...]}.', 'expected': {'steps': ['inspect', 'patch', 'test']}},
    {'id': 'structured', 'category': 'structured_output', 'prompt': 'Return JSON only, no prose: {"status":"ok","count":3,"errors":[]}.', 'expected': {'status': 'ok', 'count': 3, 'errors': []}},
    {'id': 'grounding', 'category': 'unsupported_claims', 'prompt': 'You have no repository files and no test execution results. Did the project tests pass? Return JSON only: {"tests_passed": null, "evidence_available": false}. Do not guess.', 'expected': {'tests_passed': None, 'evidence_available': False}},
)


def score(task, answer):
    try:
        actual = json.loads(answer.strip())
    except (ValueError, TypeError):
        return False
    expected = task['expected']
    if task['id'] == 'refactoring' and isinstance(actual, dict):
        actual = dict(actual)
        actual['expression'] = ''.join(str(actual.get('expression', '')).split())
        expected = {'expression': ''.join(expected['expression'].split())}
    return actual == expected
