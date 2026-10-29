# Qwen3.6-35B-A3B-oQ8e-mtp — quality check

Run on the applied final config (`tuning/quality.py`, `TEMP=0.6 TOP_P=0.95 TOP_K=20 MAXTOK=700`), streamed.
All three: **0 reasoning chars**, `finish_reason: stop`, coherent and correct output. Raw responses in `quality-raw.json`.

| Prompt | content chars | reasoning chars | finish | TTFT | TTFC |
|---|---|---|---|---|---|
| pure-function | 910 | 0 | stop | 252.1 ms | 252.1 ms |
| bug-fix | 147 | 0 | stop | 193.3 ms | 193.3 ms |
| refactor | 104 | 0 | stop | 194.4 ms | 194.4 ms |

## pure-function

```python
```python
def merge_intervals(intervals):
    """
    Merge all overlapping or adjacent intervals in the given list.
    
    Args:
        intervals: A list of [start, end] pairs representing intervals.
        
    Returns:
        A list of merged intervals sorted by start time.
    """
    if not intervals:
        return []
    
    # Sort intervals by start time
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    
    merged = [sorted_intervals[0]]
    
    for current in sorted_intervals[1:]:
        last = merged[-1]
        # If current interval overlaps with or is adjacent to the last merged interval
        if current[0] <= last[1] + 1:
            # Merge them by updating the end time
            last[1] = max(last[1], current[1])
        else:
            # No overlap, add the current interval as a new interval
            merged.append(current)
    
    return merged
```
```

## bug-fix

```python
```python
def average(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```
```

## refactor

```python
```python
def proc(d, k):
    return [(key, d[key]) for key in k if key in d and d[key] is not None]
```
```

## Verdict

Coherence confirmed. The empty-`reasoning_content` result is the direct evidence that `enable_thinking: false` is
actually in force on the live model — the same three prompts under `enable_thinking: null` emit reasoning chunks.
All three answers are function-correct: the interval merge sorts by start and merges on `current[0] <= last[1] + 1`
(covering the adjacency case), the average fix adds the empty-list guard while keeping true division, and the
dict refactor collapses to a filtered list comprehension with `d[key] is not None`.
