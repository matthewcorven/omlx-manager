# Quality guardrail — `Ornith-1.0-35B-oQ4e`

Final config: native context 262144, thinking off, no speculative decoding, KV
quant off, temperature 1.0 / top_p 0.95 / top_k 20, `force_sampling: true`.

Methodology §7 requires three fixed coding prompts — a pure function, a bug fix,
and a small refactor — with output a human would accept. The prompt text is
reused verbatim from `results/Qwen3.8-27B-oQ4e-mtp/tuning/quality.py` so results
are comparable across models.

All three passed: correct code, no reasoning leakage, `finish_reason: stop`.

## pure-function

**Prompt**

```text
Write a Python function `merge_intervals(intervals)` that takes a list of [start, end] pairs, merges all overlapping or adjacent intervals, and returns the result sorted by start. Include a docstring. Output only the code.
```

**Output**

```python
def merge_intervals(intervals):
    """Merge overlapping or adjacent intervals and return sorted result.
    
    Args:
        intervals: A list of [start, end] pairs.
        
    Returns:
        A list of merged intervals sorted by start time.
    """
    if not intervals:
        return []
    
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1][1] = max(last_end, end)
        else:
            merged.append([start, end])
    
    return merged
```

**PASS.** Correct. Sorts by start, merges on `start <= last_end` (so adjacent
intervals merge, as asked), uses `max()` on the end so a fully-contained interval
cannot shrink the result, and handles the empty list. Mutates the input list via
`sort()` — acceptable for this prompt, worth noting.

`finish_reason: stop` · completion tokens: 162 · reasoning tokens: 0

## bug-fix

**Prompt**

```text
This function should return the average of a list of numbers, but it crashes on an empty list and returns the wrong value for integers. Find the bug and give the corrected function.

```python
def average(nums):
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

Output only the corrected code.
```

**Output**

```python
def average(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

**PASS.** Correct on the real bug: the empty-list `ZeroDivisionError` is guarded.
It returns `0` rather than raising, which is a defensible choice for an average
helper (Qwen3.8-27B chose `ValueError` instead — both are acceptable, and this is
the only behavioural difference between the two models on this prompt). The
prompt's second complaint ("wrong value for integers") is not a real bug in the
original — `/` already returns a float — and the model correctly did not invent a
fix for it.

`finish_reason: stop` · completion tokens: 46 · reasoning tokens: 0

## refactor

**Prompt**

```text
Refactor this into something more readable without changing behaviour. Output only the refactored code.

```python
def proc(d, k):
    r = []
    for i in range(len(k)):
        if k[i] in d:
            if d[k[i]] != None:
                r.append((k[i], d[k[i]]))
    return r
```
```

**Output**

```python
def proc(d, k):
    return [(key, value) for key in k if key in d and d[key] is not None]
```

**PASS.** Correct. Collapses to a single list comprehension, replaces `!= None`
with `is not None`, and preserves order and behaviour exactly.

`finish_reason: stop` · completion tokens: 35 · reasoning tokens: 0

## Summary

| prompt | verdict | completion tokens | reasoning tokens |
| --- | --- | --- | --- |
| pure-function | PASS | 162 | 0 |
| bug-fix | PASS | 46 | 0 |
| refactor | PASS | 35 | 0 |

No reasoning leakage in any run, which confirms `enable_thinking: false` is
actually in effect at the final config.
