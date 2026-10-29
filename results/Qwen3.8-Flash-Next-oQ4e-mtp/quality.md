# Quality checks — Qwen3.8-Flash-Next-oQ4e-mtp

Run with `tuning/quality.py` on the applied final config (`enable_thinking: false`, `qwen4_ple_ssd_offload: true`, MTP adaptive, KV quant off, native context) at `TEMP=0.6 TOP_P=0.95 TOP_K=20 MAXTOK=700`, streaming. Raw record: `quality-raw.json`.

**Summary: 3/3 correct, 0 reasoning chars in all three, `finish_reason: stop` in all three.** Content lengths 790 / 153 / 104 chars.

| Prompt | content chars | reasoning chars | finish | TTFT | TTFC | elapsed |
|---|---|---|---|---|---|---|
| pure-function | 790 | 0 | `stop` | 407.6 ms | 407.6 ms | 2322.5 ms |
| bug-fix | 153 | 0 | `stop` | 531.2 ms | 531.2 ms | 1021.6 ms |
| refactor | 104 | 0 | `stop` | 504.0 ms | 504.0 ms | 941.0 ms |

---

## pure-function

**Prompt**

```text
Write a Python function `merge_intervals(intervals)` that takes a list of [start, end] pairs, merges all overlapping or adjacent intervals, and returns the result sorted by start. Include a docstring. Output only the code.
```

**Generated text (verbatim)**

```text
```python
def merge_intervals(intervals):
    """
    Merge all overlapping or adjacent intervals.

    Args:
        intervals: A list of [start, end] pairs.

    Returns:
        A sorted list of merged [start, end] pairs.
    """
    if not intervals:
        return []
    
    # Sort intervals by start time
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    
    merged = [sorted_intervals[0]]
    
    for current in sorted_intervals[1:]:
        last = merged[-1]
        # If current interval overlaps or is adjacent to the last merged interval
        if current[0] <= last[1]:
            # Merge them by updating the end of the last interval
            last[1] = max(last[1], current[1])
        else:
            merged.append(current)
    
    return merged
```
```

`reasoning_content`: `''` — empty, as expected with `enable_thinking: false`. `finish_reason`: `stop`. Sampler: {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "max_tokens": 700}.

---

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

**Generated text (verbatim)**

```text
```python
def average(nums):
    if len(nums) == 0:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```
```

`reasoning_content`: `''` — empty, as expected with `enable_thinking: false`. `finish_reason`: `stop`. Sampler: {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "max_tokens": 700}.

---

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

**Generated text (verbatim)**

```text
```python
def proc(d, k):
    return [(key, d[key]) for key in k if key in d and d[key] is not None]
```
```

`reasoning_content`: `''` — empty, as expected with `enable_thinking: false`. `finish_reason`: `stop`. Sampler: {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "max_tokens": 700}.
