# Quality guardrails — gemma-4-26B-A4B-it-oQ8e-mtp

Final config: MTP on with `mtp_fixed_depth: 4`, KV quant off, native context,
coding sampler (temp 0.2 / top_p 0.95 / top_k 64), `force_sampling: false`,
`enable_thinking: false`.

All three prompts were **streamed** with `max_tokens: 700`. Raw outputs and
timings are in `quality-raw.json`.

| prompt | content | reasoning | finish_reason | ttft | ttfc |
|---|---|---|---|---|---|
| pure-function | 1189 chars | 0 chars | stop | 231.2 ms | 231.2 ms |
| bug-fix | 147 chars | 0 chars | stop | 217.8 ms | 217.8 ms |
| refactor | 95 chars | 0 chars | stop | 179.7 ms | 179.7 ms |

`ttft == ttfc` on every prompt: there is no hidden reasoning phase, which is the
expected consequence of `enable_thinking: false`.

## pure-function

```python
def merge_intervals(intervals):
    """
    Merges all overlapping or adjacent intervals in a list of [start, end] pairs.
    ...
    """
    if not intervals:
        return []

    intervals.sort(key=lambda x: x[0])

    merged = []
    for interval in intervals:
        if not merged or interval[0] > merged[-1][1]:
            merged.append(interval)
        else:
            merged[-1][1] = max(merged[-1][1], interval[1])

    return merged
```

Correct: sorts by start, merges on `<=` adjacency via the `>` inverse test,
takes `max` of the end bound, handles the empty list, docstring present.
Verdict: **pass**.

## bug-fix

```python
def average(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

Fixes the empty-list crash. It does not "fix" the integer claim beyond what
Python 3 already does — `total / len(nums)` is already true division in Python 3,
so the original prompt's premise about integers was itself wrong, and the model
correctly left the division alone instead of inventing an `int()` cast. That is
the right call. Verdict: **pass**.

## refactor

```python
def proc(d, k):
    return [(key, d[key]) for key in k if d.get(key) is not None]
```

Behaviour-preserving: iterates `k` in order, keeps keys present in `d` with a
non-None value, returns `(key, value)` tuples, and replaces the `!= None`
anti-pattern with `is not None`. Verdict: **pass**.

## Corruption check

No output was word salad, no prompt produced an empty `content` with
`finish_reason: length`, and no request exceeded 3 s. `~/.omlx/cache` was 16G
throughout, far under the limit, so cache saturation is not implicated. The one
"large speedup" seen in this session (MTP on vs off, +47% decode) was verified by
reading the streamed text, not by trusting the number.
