# Quality guardrail — `gemma-4-31B-it-oQ4e-mtp`

Final config: MTP on at adaptive depth, KV quant off, native context, thinking off,
temperature 0.2 / top_p 0.95 / top_k 64, `force_sampling: false`.

Methodology §7 requires three fixed coding prompts — a pure function, a bug fix, and
a small refactor — with output a human would accept. The methodology names the
categories but does not ship literal prompt text, so the three prompts below are
fixed here and reproduced verbatim with the model's actual output.

All three passed: correct code, no reasoning leakage, `finish_reason: stop`.
Streaming, `max_tokens: 700` (the methodology's floor is 350; a thinking model with a
smaller budget spends it all on `reasoning_content` and returns empty `content`).

## pure-function

**Prompt**

```text
Write a Python function `merge_intervals(intervals)` that takes a list of [start, end] pairs, merges all overlapping or adjacent intervals, and returns the result sorted by start. Include a docstring. Output only the code.
```

**Output** — TTFT 248.9 ms, 4519.2 ms elapsed, `finish_reason: stop`, 0 reasoning chars

```python
def merge_intervals(intervals):
    """
    Merges all overlapping or adjacent intervals and returns them sorted by start.
    
    Args:
        intervals (list[list[int]]): A list of [start, end] pairs.
        
    Returns:
        list[list[int]]: A list of merged intervals.
    """
    if not intervals:
        return []

    # Sort intervals by start time
    intervals.sort(key=lambda x: x[0])

    merged = [intervals[0]]

    for current in intervals[1:]:
        prev_start, prev_end = merged[-1]
        curr_start, curr_end = current

        # If current interval overlaps or is adjacent to the previous one
        if curr_start <= prev_end:
            # Update the end of the last interval to the maximum end value
            merged[-1][1] = max(prev_end, curr_end)
        else:
            # No overlap, add the current interval to the list
            merged.append(current)

    return merged
```

**Verdict: pass.** Correct merge, correct adjacency handling (`<=`), correct sort,
docstring present, empty-input guard present. Mutates the input list via `sort` —
acceptable for the prompt as written.

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

**Output** — TTFT 243.8 ms, 1043.4 ms elapsed, `finish_reason: stop`, 0 reasoning chars

```python
def average(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

**Verdict: pass.** Fixes the empty-list crash. The "wrong value for integers" half of
the prompt is a red herring in the original code (Python 3 `/` is true division, so
integers are already correct) and the model correctly did not invent a change for it.

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

**Output** — TTFT 717.7 ms, 1513.7 ms elapsed, `finish_reason: stop`, 0 reasoning chars

```python
def proc(d, k):
    return [(key, d[key]) for key in k if d.get(key) is not None]
```

**Verdict: pass.** Behaviour-preserving: `d.get(key) is not None` is exactly
`key in d and d[key] != None`, and the comprehension preserves order and duplicates.
Idiomatic and shorter.

## Summary

| Prompt | TTFT | Elapsed | Finish | Reasoning | Verdict |
|---|---|---|---|---|---|
| pure-function | 248.9 ms | 4519.2 ms | stop | 0 chars | pass |
| bug-fix | 243.8 ms | 1043.4 ms | stop | 0 chars | pass |
| refactor | 717.7 ms | 1513.7 ms | stop | 0 chars | pass |

**3/3 pass.** No reasoning leakage, no truncation, no empty `content`.

Raw output: [`tuning/quality-raw.json`](tuning/quality-raw.json). The card-sampler
run is in [`tuning/quality-card.json`](tuning/quality-card.json) — also 3/3, which is
why the sampler choice was made on determinism rather than on quality.
