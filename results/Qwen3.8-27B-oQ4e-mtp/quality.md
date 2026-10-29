# Quality guardrail — `Qwen3.8-27B-oQ4e-mtp`

Final config: ctx 32768, MTP depth 6, KV quant 4-bit + skip_last, thinking off,
temperature 0.2 / top_p 0.95 / top_k 20, `force_sampling: true`.

Methodology §7 requires three fixed coding prompts — a pure function, a bug fix,
and a small refactor — with output a human would accept. The methodology names the
categories but does not ship literal prompt text, so the three prompts below are
fixed here and reproduced verbatim with the model's actual output.

All three passed: correct code, no reasoning leakage, `finish_reason: stop`.

## pure-function

**Prompt**

```text
Write a Python function `merge_intervals(intervals)` that takes a list of [start, end] pairs, merges all overlapping or adjacent intervals, and returns the result sorted by start. Include a docstring. Output only the code.
```

**Output**

```python
def merge_intervals(intervals):
    """
    Merge all overlapping or adjacent intervals.
    
    Args:
        intervals: A list of [start, end] pairs.
        
    Returns:
        A list of merged intervals, sorted by start.
    """
    if not intervals:
        return []
    
    # Sort intervals by start time
    intervals.sort(key=lambda x: x[0])
    
    merged = [intervals[0]]
    
    for current in intervals[1:]:
        last = merged[-1]
        # If current interval overlaps or is adjacent to the last merged interval
        if current[0] <= last[1]:
            # Merge by updating the end of the last interval
            merged[-1][1] = max(last[1], current[1])
        else:
            # No overlap, add the current interval
            merged.append(current)
    
    return merged
```

**PASS.** Correct. Sorts by start, merges on `current[0] <= last[1]` (so adjacent intervals merge, as asked), uses `max()` on the end so a fully-contained interval cannot shrink the result, and handles the empty list. Mutates the input list via `sort()` — acceptable for this prompt, worth noting.

`finish_reason: stop` · completion tokens: 205 · reasoning tokens: 0

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
        raise ValueError("Cannot compute average of an empty list")
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

**PASS.** Correct. Identifies the empty-list crash and raises a clear `ValueError` instead of `ZeroDivisionError`. The prompt's second complaint ("wrong value for integers") is not a real bug in the original — `/` already returns a float — and the model correctly did not invent a fix for it.

`finish_reason: stop` · completion tokens: 54 · reasoning tokens: 0

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
    return [(key, d[key]) for key in k if key in d and d[key] is not None]
```

**PASS.** Correct. Collapses to a single list comprehension, replaces `!= None` with `is not None`, and preserves order and behaviour exactly.

`finish_reason: stop` · completion tokens: 36 · reasoning tokens: 0
