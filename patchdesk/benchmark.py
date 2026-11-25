"""Reproducible repair experiments on small synthetic Git repositories."""
import argparse
import json
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .engine import ROOT, RUNS, command, git, run
from .usage import benchmark_usage

SUITE_VERSION = "repair-v3"


@dataclass(frozen=True)
class Case:
    task: str
    files: dict[str, str]
    fixes: dict[str, str]
    regression: str
    acceptance: str
    imports: str = "from logic import *"
    baseline_error: str = "AssertionError"


CASES = {
    "分页": Case(
        "分页函数 page(items, size) 应保留最后不足一页的数据。",
        {"logic.py": "def page(items, size):\n    return [items[i:i+size] for i in range(0, len(items)-size+1, size)]\n"},
        {"logic.py": "def page(items, size):\n    return [items[i:i+size] for i in range(0, len(items), size)]\n"},
        "page([1, 2], 2) == [[1, 2]]",
        "page([1, 2, 3], 2) == [[1, 2], [3]] and page([1], 4) == [[1]] and page([], 2) == []",
    ),
    "去重": Case(
        "unique(items) 去重时保持第一次出现的顺序。",
        {"logic.py": "def unique(items):\n    return sorted(set(items))\n"},
        {"logic.py": "def unique(items):\n    return list(dict.fromkeys(items))\n"},
        "unique([1, 1]) == [1]",
        "unique([3, 1, 3, 2]) == [3, 1, 2] and unique(['b', 'a', 'b']) == ['b', 'a']",
    ),
    "均值": Case(
        "mean(values) 对空列表返回 None，保留非空列表的原行为。",
        {"logic.py": "def mean(values):\n    return sum(values) / len(values)\n"},
        {"logic.py": "def mean(values):\n    return sum(values) / len(values) if values else None\n"},
        "mean([1, 2]) == 1.5",
        "mean([]) is None and mean([-2, 2]) == 0 and mean([7]) == 7",
        baseline_error="ZeroDivisionError",
    ),
    "标签规范化": Case(
        "normalize(tags) 应清除每个标签两端空白，丢弃空标签，再小写去重并保持首次出现顺序。",
        {"logic.py": "def normalize(tags):\n    return list(dict.fromkeys(tag.lower() for tag in tags))\n"},
        {"logic.py": "def normalize(tags):\n    clean = (tag.strip().lower() for tag in tags)\n    return list(dict.fromkeys(tag for tag in clean if tag))\n"},
        "normalize(['Py', 'py', 'Git']) == ['py', 'git']",
        "normalize([' Git ', '', 'PY', '\\tgit\\n', '  ']) == ['git', 'py'] and normalize(['  ']) == []",
    ),
    "闭区间重叠": Case(
        "overlaps(a, b) 接收两个端点已排序的闭区间。修复交集判断，让端点相接和单点区间相交时也返回 True。",
        {"logic.py": "def overlaps(a, b):\n    return max(a[0], b[0]) < min(a[1], b[1])\n"},
        {"logic.py": "def overlaps(a, b):\n    return max(a[0], b[0]) <= min(a[1], b[1])\n"},
        "overlaps((1, 4), (2, 5)) and not overlaps((1, 2), (4, 5))",
        "overlaps((1, 2), (2, 3)) and overlaps((2, 2), (2, 2)) and not overlaps((1, 2), (3, 4))",
    ),
    "跨文件折扣": Case(
        "修复 pricing.py 和 logic.py 的公开接口。pricing.discounted(subtotal, member) 只对会员打九折，"
        "logic.checkout(subtotal, member=False) 应将会员标记传给 discounted。保留两者签名，金额按原来的整数截断。",
        {
            "pricing.py": "def discounted(subtotal, member):\n    return subtotal\n",
            "logic.py": "from pricing import discounted\n\n\ndef checkout(subtotal, member=False):\n    return discounted(subtotal, False)\n",
        },
        {
            "pricing.py": "def discounted(subtotal, member):\n    return subtotal * 9 // 10 if member else subtotal\n",
            "logic.py": "from pricing import discounted\n\n\ndef checkout(subtotal, member=False):\n    return discounted(subtotal, member)\n",
        },
        "checkout(100) == 100 and checkout(49, False) == 49",
        "checkout(99, True) == 89 and checkout(99) == 99 and discounted(19, True) == 17 and discounted(19, False) == 19",
        imports="from logic import checkout\nfrom pricing import discounted",
    ),
    "稳定排名": Case(
        "rank(scores) 按分数从高到低返回姓名，分数相同时保持输入顺序。scores 是 (姓名, 分数) 列表。",
        {"logic.py": "def rank(scores):\n    return [name for name, score in sorted(scores, key=lambda entry: (entry[1], entry[0]), reverse=True)]\n"},
        {"logic.py": "def rank(scores):\n    return [name for name, score in sorted(scores, key=lambda entry: entry[1], reverse=True)]\n"},
        "rank([('a', 1), ('z', 2)]) == ['z', 'a']",
        "rank([('a', 8), ('z', 8), ('q', 9), ('x', 8)]) == ['q', 'a', 'z', 'x'] and rank([]) == []",
    ),
    "严格日期": Case(
        "is_date(value) 仅当字符串是有效日历日期且严格匹配 YYYY-MM-DD 时返回 True。禁止接受缺少前导零或尾随字符的输入。",
        {"logic.py": "import re\n\n\ndef is_date(value):\n    return re.match(r'^[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}', value) is not None\n"},
        {"logic.py": "import re\nfrom datetime import date\n\n\ndef is_date(value):\n    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):\n        return False\n    try:\n        date.fromisoformat(value)\n    except ValueError:\n        return False\n    return True\n"},
        "is_date('2024-12-31') and not is_date('no date')",
        "is_date('2024-02-29') and not any(map(is_date, ['2023-02-29', '2024-13-01', '2024-2-09', '2024-02-29\\n', '0000-01-01']))",
    ),
    "原子库存更新": Case(
        "reserve(stock, order) 尝试从库存字典扣减订单字典中的数量。库存不足或缺货时返回 False，且 stock 的任何条目都不能变化。下单成功时原地扣减并返回 True。",
        {"logic.py": "def reserve(stock, order):\n    for item, quantity in order.items():\n        if stock.get(item, 0) < quantity:\n            return False\n        stock[item] -= quantity\n    return True\n"},
        {"logic.py": "def reserve(stock, order):\n    if any(stock.get(item, 0) < quantity for item, quantity in order.items()):\n        return False\n    for item, quantity in order.items():\n        if item in stock:\n            stock[item] -= quantity\n    return True\n"},
        "(stock := {'a': 4}) and reserve(stock, {'a': 2}) and stock == {'a': 2}",
        "(stock := {'a': 4, 'b': 1}) and not reserve(stock, {'a': 2, 'b': 2}) and stock == {'a': 4, 'b': 1} and not reserve(stock, {'a': 1, 'absent': 1}) and stock == {'a': 4, 'b': 1}",
    ),
    "缓存键冲突": Case(
        "cache_key(parts) 接收字符串列表，返回字符串键。相同元素及顺序给出相同键，任何两个不同列表不能因为元素里含分隔符而得到相同键。",
        {"logic.py": "def cache_key(parts):\n    return ':'.join(parts)\n"},
        {"logic.py": "import json\n\n\ndef cache_key(parts):\n    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))\n"},
        "isinstance(cache_key(['a', 'b']), str) and cache_key(['a']) != cache_key(['b'])",
        "len({cache_key(p) for p in [[], [''], ['a:b', 'c'], ['a', 'b:c'], ['a', 'b', 'c'], ['汉字', ''], ['', '汉字']]}) == 7 and cache_key(['a', 'b']) == cache_key(['a', 'b'])",
    ),
    "跨文件配置优先级": Case(
        "修复两个接口。settings.resolve(settings, overrides) 返回新字典，让 overrides 覆盖已有配置，并保留值为 0、False 或空字符串的覆盖项。logic.port(settings, overrides=None) 应经 resolve 读取端口，缺少端口时返回 8000。输入字典保持原样。",
        {
            "settings.py": "def resolve(settings, overrides):\n    result = dict(settings)\n    result.update({key: value for key, value in overrides.items() if value})\n    return result\n",
            "logic.py": "from settings import resolve\n\n\ndef port(settings, overrides=None):\n    return settings.get('port', 8000)\n",
        },
        {
            "settings.py": "def resolve(settings, overrides):\n    return {**settings, **overrides}\n",
            "logic.py": "from settings import resolve\n\n\ndef port(settings, overrides=None):\n    return resolve(settings, overrides or {}).get('port', 8000)\n",
        },
        "port({'port': 8080}) == 8080 and port({}) == 8000",
        "(base := {'port': 8080, 'log': True}) and (extra := {'port': 0, 'log': False, 'name': ''}) and resolve(base, extra) == extra and port(base, extra) == 0 and port({}, {'port': 9000}) == 9000 and base == {'port': 8080, 'log': True} and extra == {'port': 0, 'log': False, 'name': ''}",
        imports="from logic import port\nfrom settings import resolve",
    ),
    "合并预订区间": Case(
        "merge(bookings) 接收任意顺序的闭区间列表，合并重叠或端点相接的区间，返回按起点排序的元组列表。不得修改输入列表。",
        {"logic.py": "def merge(bookings):\n    result = []\n    for start, end in bookings:\n        if result and result[-1][1] > start:\n            result[-1] = (result[-1][0], max(result[-1][1], end))\n        else:\n            result.append((start, end))\n    return result\n"},
        {"logic.py": "def merge(bookings):\n    result = []\n    for start, end in sorted(bookings):\n        if result and result[-1][1] >= start:\n            result[-1] = (result[-1][0], max(result[-1][1], end))\n        else:\n            result.append((start, end))\n    return result\n"},
        "merge([(1, 4), (2, 3), (7, 8)]) == [(1, 4), (7, 8)]",
        "(original := [(8, 10), (4, 8), (12, 13), (1, 4), (2, 3)]) and merge(original) == [(1, 10), (12, 13)] and original == [(8, 10), (4, 8), (12, 13), (1, 4), (2, 3)] and merge([]) == []",
    ),
    "进位取整": Case(
        "batches(n, size) 返回装下 n 个物件所需批次数，n 非负且 size 为正。",
        {"logic.py": "def batches(n, size):\n    return n // size\n"},
        {"logic.py": "def batches(n, size):\n    return (n + size - 1) // size\n"},
        "batches(6, 3) == 2",
        "batches(7, 3) == 3 and batches(1, 9) == 1 and batches(0, 9) == 0",
    ),
    "负数舍入": Case(
        "round_units(amount) 将整数分换算成整单位，半单位远离零舍入。",
        {"logic.py": "def round_units(amount):\n    return (amount + 50) // 100\n"},
        {"logic.py": "def round_units(amount):\n    return (-1 if amount < 0 else 1) * ((abs(amount) + 50) // 100)\n"},
        "round_units(150) == 2",
        "[round_units(n) for n in [-149, -150, -50, -49, 0, 50]] == [-1, -2, -1, 0, 0, 1]",
    ),
    "加权均值": Case(
        "weighted(items) 接收 (数值, 非负权重) 对，返回按权重计算的均值，权重和为零时返回 None。",
        {"logic.py": "def weighted(items):\n    return sum(value for value, weight in items) / len(items)\n"},
        {"logic.py": "def weighted(items):\n    total = sum(weight for value, weight in items)\n    return sum(value * weight for value, weight in items) / total if total else None\n"},
        "weighted([(2, 1), (6, 1)]) == 4",
        "weighted([(2, 3), (10, 1), (90, 0)]) == 4 and weighted([(3, 0)]) is None and weighted([]) is None",
    ),
    "读数分组": Case(
        "group(rows) 接收 (站点, 读数) 对，为每站保留所有读数及其输入顺序。",
        {"logic.py": "def group(rows):\n    return {name: [value] for name, value in rows}\n"},
        {"logic.py": "def group(rows):\n    result = {}\n    for name, value in rows:\n        result.setdefault(name, []).append(value)\n    return result\n"},
        "group([('a', 1), ('b', 2)]) == {'a': [1], 'b': [2]}",
        "group([('a', 4), ('b', 0), ('a', 4), ('a', 1)]) == {'a': [4, 4, 1], 'b': [0]} and group([]) == {}",
    ),
    "对账数量": Case(
        "remaining(expected, received) 返回有序缺件列表，每次收货最多抵消一个同名物件，额外收货忽略。",
        {"logic.py": "def remaining(expected, received):\n    return [item for item in expected if item not in received]\n"},
        {"logic.py": "from collections import Counter\n\ndef remaining(expected, received):\n    counts = Counter(received)\n    result = []\n    for item in expected:\n        if counts[item]:\n            counts[item] -= 1\n        else:\n            result.append(item)\n    return result\n"},
        "remaining(['a', 'b'], ['b']) == ['a']",
        "remaining(['a', 'b', 'a', 'b', 'c'], ['b', 'a', 'z']) == ['a', 'b', 'c']",
    ),
    "流式分块": Case(
        "chunks(values, size) 返回按输入顺序分块的列表，支持单次遍历的迭代器且保留尾块。size 为正。",
        {"logic.py": "def chunks(values, size):\n    return [values[i:i+size] for i in range(0, len(values), size)]\n"},
        {"logic.py": "def chunks(values, size):\n    result = []\n    for index, value in enumerate(values):\n        if index % size == 0:\n            result.append([])\n        result[-1].append(value)\n    return result\n"},
        "chunks([1, 2, 3], 2) == [[1, 2], [3]]",
        "chunks(iter(range(7)), 3) == [[0, 1, 2], [3, 4, 5], [6]] and chunks(iter(()), 1) == []",
        baseline_error="TypeError",
    ),
    "深层配置合并": Case(
        "merge_defaults(base, custom) 递归合并字典，同键都是字典时保留两边子键，其余情况采用 custom 的值，输入不得改变。",
        {"logic.py": "def merge_defaults(base, custom):\n    return {**base, **custom}\n"},
        {"logic.py": "def merge_defaults(base, custom):\n    result = dict(base)\n    for key, value in custom.items():\n        previous = result.get(key)\n        result[key] = merge_defaults(previous, value) if isinstance(previous, dict) and isinstance(value, dict) else value\n    return result\n"},
        "merge_defaults({'a': 1, 'b': 2}, {'a': 3}) == {'a': 3, 'b': 2}",
        "(base := {'x': {'a': 1, 'sub': {'l': 2}}, 'z': 4}) and merge_defaults(base, {'x': {'sub': {'r': 3}}, 'z': None}) == {'x': {'a': 1, 'sub': {'l': 2, 'r': 3}}, 'z': None} and base == {'x': {'a': 1, 'sub': {'l': 2}}, 'z': 4}",
    ),
    "CSV 引号": Case(
        "parse_row(row) 解析一条 CSV 记录，支持引号内逗号、双引号转义与空字段。",
        {"logic.py": "def parse_row(row):\n    return row.split(',')\n"},
        {"logic.py": "import csv\n\ndef parse_row(row):\n    return next(csv.reader([row]))\n"},
        "parse_row('a,b,') == ['a', 'b', '']",
        "parse_row('\"a,b\",\"say \"\"hi\"\"\",') == ['a,b', 'say \"hi\"', '']",
    ),
    "显式布尔解析": Case(
        "read_flag(value) 忽略空白和大小写，接受 true、1、yes 与 false、0、no，其他字符串抛 ValueError。",
        {"logic.py": "def read_flag(value):\n    return bool(value)\n"},
        {"logic.py": "def read_flag(value):\n    flag = value.strip().lower()\n    if flag in {'true', '1', 'yes'}:\n        return True\n    if flag in {'false', '0', 'no'}:\n        return False\n    raise ValueError(value)\n"},
        "read_flag('true') is True",
        "[read_flag(x) for x in [' YES ', '1', 'False', ' no ', '0']] == [True, True, False, False, False] and __import__('unittest').TestCase().assertRaises(ValueError, read_flag, 'unknown') is None",
    ),
    "十进制时长": Case(
        "minutes(value) 解析 H:MM 为分钟，小时非负，分钟必须两位且小于 60。非法输入抛 ValueError。",
        {"logic.py": "def minutes(value):\n    h, m = map(int, value.split(':'))\n    return h * 60 + m\n"},
        {"logic.py": "import re\n\ndef minutes(value):\n    if not re.fullmatch(r'[0-9]+:[0-5][0-9]', value):\n        raise ValueError(value)\n    h, m = map(int, value.split(':'))\n    return h * 60 + m\n"},
        "minutes('2:05') == 125",
        "minutes('25:00') == 1500 and all(__import__('unittest').TestCase().assertRaises(ValueError, minutes, x) is None for x in ['1:60', '2:5', '-1:05', '0:00 '])",
    ),
    "Unicode 文本匹配": Case(
        "same_label(a, b) 比较标签时忽略大小写并将 Unicode 规范等价形式视为相同。",
        {"logic.py": "def same_label(a, b):\n    return a.lower() == b.lower()\n"},
        {"logic.py": "import unicodedata\n\ndef same_label(a, b):\n    return unicodedata.normalize('NFC', a).casefold() == unicodedata.normalize('NFC', b).casefold()\n"},
        "same_label('HELLO', 'hello')",
        "same_label('Straße', 'STRASSE') and same_label('e\\u0301', 'É') and not same_label('a', 'b')",
    ),
    "文本模板保留": Case(
        "render(template, values) 单次替换 {name} 占位符，未知占位符原样保留，插入值中的占位符不再展开。",
        {"logic.py": "def render(template, values):\n    for name, value in values.items():\n        template = template.replace('{' + name + '}', value)\n    return template\n"},
        {"logic.py": "import re\n\ndef render(template, values):\n    return re.sub(r'\\{([^{}]+)\\}', lambda match: values.get(match[1], match[0]), template)\n"},
        "render('Hi {name}', {'name': 'Lin'}) == 'Hi Lin'",
        "render('{a} {b} {c}', {'a': '{b}', 'b': 'ok'}) == '{b} ok {c}'",
    ),
    "图最短路径": Case(
        "distance(edges, start, end) 返回无权有向图最少边数，起终相同返回 0，不可达返回 None。",
        {"logic.py": "def distance(edges, start, end):\n    if start == end:\n        return 0\n    return 1 if end in edges.get(start, []) else None\n"},
        {"logic.py": "from collections import deque\n\ndef distance(edges, start, end):\n    seen = {start}\n    queue = deque([(start, 0)])\n    while queue:\n        node, depth = queue.popleft()\n        if node == end:\n            return depth\n        for other in edges.get(node, []):\n            if other not in seen:\n                seen.add(other)\n                queue.append((other, depth + 1))\n    return None\n"},
        "distance({'a': ['b']}, 'a', 'b') == 1",
        "(graph := {'a': ['b', 'd'], 'b': ['c', 'a'], 'c': ['e'], 'd': ['e']}) and distance(graph, 'a', 'e') == 2 and distance(graph, 'b', 'd') == 2 and distance(graph, 'e', 'a') is None",
    ),
    "依赖遍历": Case(
        "closure(graph, root) 返回 root 的全部传递依赖集合，结果排除 root 并能处理环。",
        {"logic.py": "def closure(graph, root):\n    return set(graph.get(root, []))\n"},
        {"logic.py": "def closure(graph, root):\n    seen = {root}\n    pending = list(graph.get(root, []))\n    while pending:\n        node = pending.pop()\n        if node not in seen:\n            seen.add(node)\n            pending.extend(graph.get(node, []))\n    return seen - {root}\n"},
        "closure({'a': ['b']}, 'a') == {'b'}",
        "closure({'a': ['b', 'd'], 'b': ['a', 'c'], 'c': ['d']}, 'a') == {'b', 'c', 'd'} and closure({}, 'z') == set()",
    ),
    "矩形边界": Case(
        "contains(rect, point) 采用左上包含、右下排除的矩形坐标，零宽或零高矩形不包含任何点。",
        {"logic.py": "def contains(rect, point):\n    left, top, right, bottom = rect\n    x, y = point\n    return left <= x <= right and top <= y <= bottom\n"},
        {"logic.py": "def contains(rect, point):\n    left, top, right, bottom = rect\n    x, y = point\n    return left <= x < right and top <= y < bottom\n"},
        "contains((0, 0, 4, 3), (1, 2))",
        "contains((0, 0, 4, 3), (0, 0)) and not contains((0, 0, 4, 3), (4, 2)) and not contains((0, 0, 4, 3), (2, 3)) and not contains((1, 0, 1, 2), (1, 1))",
    ),
    "稀疏点积": Case(
        "dot(a, b) 接收坐标到数值的字典，缺失坐标按零计算，两个集合可完全不相交。",
        {"logic.py": "def dot(a, b):\n    return sum(value * b[key] for key, value in a.items())\n"},
        {"logic.py": "def dot(a, b):\n    return sum(value * b.get(key, 0) for key, value in a.items())\n"},
        "dot({0: 2, 2: 3}, {0: 4, 2: 5}) == 23",
        "dot({0: 2, 2: 3}, {0: 4, 4: -1}) == 8 and dot({1: 2}, {2: 3}) == 0 and dot({}, {}) == 0",
        baseline_error="KeyError",
    ),
    "有界队列": Case(
        "push(window, value, capacity) 原地加入新值，并从队首移除旧值直到长度不超过非负 capacity，函数返回 None。",
        {"logic.py": "def push(window, value, capacity):\n    window.append(value)\n    if len(window) > capacity:\n        window.pop(0)\n"},
        {"logic.py": "def push(window, value, capacity):\n    window.append(value)\n    del window[:max(0, len(window) - capacity)]\n"},
        "(w := [1, 2]) and push(w, 3, 2) is None and w == [2, 3]",
        "(w := [1, 2, 3, 4]) and push(w, 5, 2) is None and w == [4, 5] and push(w, 6, 0) is None and w == []",
    ),
    "过期缓存": Case(
        "get(cache, key, now) 从字典读取 (value, expires) 记录。now 达到过期时刻时原地删除，缺失或过期返回 None，否则返回 value。",
        {"logic.py": "def get(cache, key, now):\n    if key not in cache:\n        return None\n    value, expires = cache[key]\n    if now > expires:\n        return None\n    return value\n"},
        {"logic.py": "def get(cache, key, now):\n    if key not in cache:\n        return None\n    value, expires = cache[key]\n    if now >= expires:\n        del cache[key]\n        return None\n    return value\n"},
        "get({'x': ('ok', 5)}, 'x', 4) == 'ok'",
        "(c := {'x': (0, 5), 'y': (False, 8)}) and get(c, 'x', 5) is None and 'x' not in c and get(c, 'y', 7) is False and get(c, 'missing', 4) is None",
    ),
    "惰性默认值": Case(
        "lookup(mapping, key, fallback) 在键缺失时才调用零参数 fallback，键存在时返回原值，包括 None、0 和 False。",
        {"logic.py": "def lookup(mapping, key, fallback):\n    return mapping.get(key, fallback())\n"},
        {"logic.py": "def lookup(mapping, key, fallback):\n    return mapping[key] if key in mapping else fallback()\n"},
        "lookup({}, 'k', lambda: 5) == 5",
        "lookup({'k': None}, 'k', lambda: 1/0) is None and lookup({'k': False}, 'k', lambda: 1/0) is False and lookup({}, 'x', lambda: 8) == 8",
        baseline_error="ZeroDivisionError",
    ),
    "独立容器默认值": Case(
        "empty_sections(names) 返回各名称对应的空列表。修改一项不影响其他项。",
        {"logic.py": "def empty_sections(names):\n    return dict.fromkeys(names, [])\n"},
        {"logic.py": "def empty_sections(names):\n    return {name: [] for name in names}\n"},
        "empty_sections(['x']) == {'x': []}",
        "(s := empty_sections(['x', 'y', 'z'])) and s['y'].append(6) is None and s == {'x': [], 'y': [6], 'z': []}",
    ),
    "设置撤销": Case(
        "Undoable.set(value) 应记录当前状态再更新，undo() 恢复上一个状态；没有记录时保持原状态。",
        {"logic.py": "class Undoable:\n    def __init__(self, value):\n        self.value = value\n        self.history = []\n\n    def set(self, value):\n        self.history.append(value)\n        self.value = value\n\n    def undo(self):\n        if self.history:\n            self.value = self.history.pop()\n"},
        {"logic.py": "class Undoable:\n    def __init__(self, value):\n        self.value = value\n        self.history = []\n\n    def set(self, value):\n        self.history.append(self.value)\n        self.value = value\n\n    def undo(self):\n        if self.history:\n            self.value = self.history.pop()\n"},
        "(s := Undoable(0)) and s.undo() is None and s.value == 0",
        "(s := Undoable(0)) and s.set(1) is None and s.set(2) is None and s.undo() is None and s.value == 1 and s.undo() is None and s.value == 0 and s.undo() is None and s.value == 0",
    ),
    "缺失列导出": Case(
        "export(rows, columns) 返回按 columns 顺序排列的值列表。缺列填空字符串，保留已存在的 None、False 和 0。",
        {"logic.py": "def export(rows, columns):\n    return [[row[key] for key in columns] for row in rows]\n"},
        {"logic.py": "def export(rows, columns):\n    return [[row.get(key, '') for key in columns] for row in rows]\n"},
        "export([{'x': 3, 'y': 8}], ['y', 'x']) == [[8, 3]]",
        "export([{'a': None, 'b': 0}, {'c': False}], ['c', 'b', 'a']) == [['', 0, None], [False, '', '']]",
        baseline_error="KeyError",
    ),
    "环境变量展开": Case(
        "expand(values, env) 返回新字典，将字符串里的 ${NAME} 替换成 env 值。缺失变量保留原样，非字符串保持原类型。",
        {"logic.py": "import re\n\ndef expand(values, env):\n    return {key: re.sub(r'\\$\\{(\\w+)\\}', lambda m: env.get(m[1], ''), value) for key, value in values.items()}\n"},
        {"logic.py": "import re\n\ndef expand(values, env):\n    return {key: re.sub(r'\\$\\{(\\w+)\\}', lambda m: env.get(m[1], m[0]), value) if isinstance(value, str) else value for key, value in values.items()}\n"},
        "expand({'path': '${BASE}/x'}, {'BASE': '/root'}) == {'path': '/root/x'}",
        "(v := {'x': '${A}/${B}', 'n': 0, 'flag': False}) and expand(v, {'A': 'ok'}) == {'x': 'ok/${B}', 'n': 0, 'flag': False} and v == {'x': '${A}/${B}', 'n': 0, 'flag': False}",
        baseline_error="TypeError",
    ),
    "分段插值": Case(
        "interpolate(points, x) 在相邻数据点之间线性插值。points 至少两个、横坐标严格递增，区间外采用最近端点值。",
        {"logic.py": "def interpolate(points, x):\n    return min(points, key=lambda p: abs(p[0] - x))[1]\n"},
        {"logic.py": "def interpolate(points, x):\n    if x <= points[0][0]:\n        return points[0][1]\n    for (x0, y0), (x1, y1) in zip(points, points[1:]):\n        if x <= x1:\n            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)\n    return points[-1][1]\n"},
        "interpolate([(0, 3), (4, 7)], 4) == 7",
        "(p := [(0, 0), (4, 8), (8, 0)]) and [interpolate(p, x) for x in [-1, 1, 5, 9]] == [0, 2, 6, 0]",
    ),
    "跨文件单位换算": Case(
        "units.to_grams(value, unit) 支持 g 和 kg、未知单位抛 ValueError。logic.total(rows) 必须按每条的单位换算后求克数。",
        {"units.py": "def to_grams(value, unit):\n    return value\n", "logic.py": "from units import to_grams\n\ndef total(rows):\n    return sum(value for value, unit in rows)\n"},
        {"units.py": "def to_grams(value, unit):\n    if unit == 'g':\n        return value\n    if unit == 'kg':\n        return value * 1000\n    raise ValueError(unit)\n", "logic.py": "from units import to_grams\n\ndef total(rows):\n    return sum(to_grams(value, unit) for value, unit in rows)\n"},
        "total([(1, 'g'), (2, 'g')]) == 3",
        "to_grams(2, 'kg') == 2000 and total([(2, 'kg'), (250, 'g')]) == 2250 and total([]) == 0 and __import__('unittest').TestCase().assertRaises(ValueError, total, [(2, 'lb')]) is None",
        imports="from units import to_grams\nfrom logic import total",
    ),
    "跨文件成绩边界": Case(
        "grading.label(score) 应映射 90 至 100 为 A，60 至 89 为 P，0 至 59 为 F。logic.tally(scores) 返回实际出现的等级及各自数量。",
        {"grading.py": "def label(score):\n    return 'P' if score >= 60 else 'F'\n", "logic.py": "from grading import label\n\ndef tally(scores):\n    return {label(score): 1 for score in scores}\n"},
        {"grading.py": "def label(score):\n    if score >= 90:\n        return 'A'\n    return 'P' if score >= 60 else 'F'\n", "logic.py": "from grading import label\n\ndef tally(scores):\n    result = {}\n    for score in scores:\n        grade = label(score)\n        result[grade] = result.get(grade, 0) + 1\n    return result\n"},
        "tally([59, 60]) == {'F': 1, 'P': 1}",
        "[label(x) for x in [0, 59, 60, 89, 90, 100]] == ['F', 'F', 'P', 'P', 'A', 'A'] and tally([59, 60, 89, 90, 100]) == {'F': 1, 'P': 2, 'A': 2} and tally([]) == {}",
        imports="from grading import label\nfrom logic import tally",
    ),
    "跨文件时间聚合": Case(
        "calendar_utils.bucket(hour) 将 0 至 23 点分为 night（0 至 5 或 22 至 23）、morning（6 至 11）、day（12 至 21）。logic.count_slots(hours) 汇总每个实际出现的时段。",
        {"calendar_utils.py": "def bucket(hour):\n    return 'morning' if hour < 12 else 'day'\n", "logic.py": "from calendar_utils import bucket\n\ndef count_slots(hours):\n    return {bucket(hour): 1 for hour in hours}\n"},
        {"calendar_utils.py": "def bucket(hour):\n    if hour < 6 or hour >= 22:\n        return 'night'\n    return 'morning' if hour < 12 else 'day'\n", "logic.py": "from calendar_utils import bucket\n\ndef count_slots(hours):\n    result = {}\n    for hour in hours:\n        name = bucket(hour)\n        result[name] = result.get(name, 0) + 1\n    return result\n"},
        "count_slots([8, 16]) == {'morning': 1, 'day': 1}",
        "[bucket(h) for h in [0, 5, 6, 11, 12, 21, 22, 23]] == ['night','night','morning','morning','day','day','night','night'] and count_slots([0, 2, 7, 18, 22, 23]) == {'night': 4, 'morning': 1, 'day': 1}",
        imports="from calendar_utils import bucket\nfrom logic import count_slots",
    ),
    "跨文件日志筛选": Case(
        "levels.priority(value) 忽略空白与大小写，将 debug、info、warning、error 映射到 10、20、30、40。logic.select(records, minimum) 返回达到最低等级的原始 (等级, 消息) 记录，保留顺序。",
        {"levels.py": "def priority(value):\n    return {'debug': 10, 'info': 20, 'warning': 30, 'error': 40}[value]\n", "logic.py": "from levels import priority\n\ndef select(records, minimum):\n    return [record for record in records if priority(record[0]) > priority(minimum)]\n"},
        {"levels.py": "def priority(value):\n    return {'debug': 10, 'info': 20, 'warning': 30, 'error': 40}[value.strip().lower()]\n", "logic.py": "from levels import priority\n\ndef select(records, minimum):\n    threshold = priority(minimum)\n    return [record for record in records if priority(record[0]) >= threshold]\n"},
        "select([('debug', 'a'), ('error', 'b')], 'info') == [('error', 'b')]",
        "priority(' Warning ') == 30 and select([('ERROR', 'a'), ('debug', 'b'), ('Warning', 'c')], ' warning ') == [('ERROR', 'a'), ('Warning', 'c')]",
        imports="from levels import priority\nfrom logic import select",
        baseline_error="KeyError",
    ),
}


def example(key, live=False, *, model=None):
    case = CASES[key]
    with tempfile.TemporaryDirectory() as temp:
        repo = Path(temp) / "fixture"
        (repo / "tests").mkdir(parents=True)
        for name, source in case.files.items():
            (repo / name).write_text(source, encoding="utf-8")
        (repo / "tests/test_logic.py").write_text(
            f"import unittest\nfrom logic import *\nclass Regression(unittest.TestCase):\n"
            f"    def test_original(self):\n        self.assertTrue({case.regression})\n", encoding="utf-8")
        git(repo, "init", "-q")
        git(repo, "add", ".")
        git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-qm", "baseline")
        regression = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
        if command(regression, repo)[0]:
            raise ValueError(f"{key} 的原有回归测试未通过")
        acceptance = [sys.executable, "-c", f"{case.imports}\nassert {case.acceptance}"]
        code, output = command(acceptance, repo)
        last_line = output.rstrip().rsplit("\n", 1)[-1]
        if code != 1 or last_line.partition(":")[0] != case.baseline_error:
            raise ValueError(f"{key} 的独立验收未准确捕获预期缺陷")
        actions = [
            *(dict(action="read", path=name) for name in case.fixes),
            *(dict(action="write", path=name, text=source) for name, source in case.fixes.items()),
            dict(action="test"), dict(action="finish"),
        ]
        return run(repo, case.task, None if live else actions, acceptance,
                   "model" if live else "scripted", model=model)


def evaluate(live, repeats, model, jobs=1):
    def run_case(item):
        repeat, name = item
        started = time.monotonic()
        report = example(name, live, model=model)
        regression = report["regression"]["passed"] is True
        acceptance = report["acceptance"]["passed"] is True
        changed = bool(report["diff"])
        solved = report["status"] == "已结束" and regression and acceptance and changed
        row = {
            "case": name, "repeat": repeat, "run_id": report["id"],
            "model": report.get("model") or model, "status": report["status"],
            "solved": solved, "regression": regression, "acceptance": acceptance,
            "changed": changed, "seconds": round(time.monotonic() - started, 2),
            "turns": report["turns"], "error": report.get("error", ""),
            "usage": report.get("usage"),
        }
        print(f"[{repeat}/{repeats}] {name}: {report['status']} · {'通过' if solved else '未解决'}", flush=True)
        return row

    tasks = [(repeat, name) for repeat in range(1, repeats + 1) for name in CASES]
    if jobs == 1:
        return [run_case(item) for item in tasks]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(run_case, tasks))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--model", help="覆盖环境中的 MODEL_ID，仅用于真实模型实验")
    parser.add_argument("--jobs", type=int, default=1, help="同时运行的任务数")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs 必须大于 0")
    if args.repeat < 1:
        parser.error("--repeat 必须大于 0")
    if args.model and not args.live:
        parser.error("--model 需要与 --live 一起使用")
    if args.live:
        load_dotenv(ROOT / ".env", override=False)
        import os
        configured = args.model or os.getenv("MODEL_ID")
        if not configured or not os.getenv("ANTHROPIC_API_KEY"):
            parser.error("真实模型评测需要 MODEL_ID（或 --model）和 ANTHROPIC_API_KEY")
    else:
        configured = None

    started = time.monotonic()
    rows = evaluate(args.live, args.repeat, configured, args.jobs)
    mode = "model" if args.live else "scripted"
    summary = {
        "suite": SUITE_VERSION, "mode": mode, "model": configured, "repeats": args.repeat,
        "jobs": args.jobs, "wall_seconds": round(time.monotonic() - started, 2),
        "tasks": len(rows), "solved": sum(row["solved"] for row in rows),
        "regression_passes": sum(row["regression"] for row in rows),
        "acceptance_passes": sum(row["acceptance"] for row in rows),
        "median_seconds": round(statistics.median(row["seconds"] for row in rows), 2),
        "mean_turns": round(statistics.mean(row["turns"] for row in rows), 2),
        "usage": benchmark_usage(rows),
        "runs": [row["run_id"] for row in rows], "results": rows,
    }
    path = RUNS / f"benchmark-{mode}.json"
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{summary['solved']}/{summary['tasks']} · {path}", flush=True)
    return int(summary["solved"] != summary["tasks"])


if __name__ == "__main__":
    sys.exit(main())
