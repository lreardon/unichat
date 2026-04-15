# Batched Concurrency vs Worker Pool

When you need parallel processing, these two patterns are common:

- Batched concurrency: collect N jobs, run them together, wait for the batch to finish, then start the next batch.
- Worker pool: start a fixed or elastic set of workers that continuously pull jobs from a shared queue.

Both work well. The right choice depends on how your jobs behave and how much control you need.

## Batched concurrency

In a batched model, work happens in rounds. Each round has a clear start and end.

### Pros

- Simple control flow and easier debugging.
- Natural checkpoints between batches.
- Good fit for bulk APIs and rate-limited systems that reset on interval boundaries.

### Cons

- Fast jobs wait for slow jobs in the same batch.
- Throughput can drop if job durations vary a lot.
- Less responsive when new work arrives continuously.

### Best use cases

- ETL jobs that run nightly on fixed datasets.
- Systems where you must commit state after each group.
- Workloads with similar runtime per job.

## Worker pool

In a worker-pool model, workers keep pulling work until the queue is empty.

### Pros

- Better resource utilization for uneven job durations.
- Lower tail latency because workers do not wait for a whole batch to finish.
- Handles continuous streams naturally.

### Cons

- More moving parts: queue management, backpressure, shutdown logic.
- Harder state snapshots if jobs are in flight.
- Needs careful handling of retries, deduplication, and ordering.

### Best use cases

- Crawlers, message consumers, and event processing pipelines.
- APIs with mixed response times.
- High-volume workloads where throughput matters more than strict batch boundaries.

## How to choose

Use this quick checklist:

1. Are jobs similar in runtime, and do you need clean round boundaries? Choose batched concurrency.
2. Are runtimes highly variable, or does work arrive continuously? Choose a worker pool.
3. Do you need easy checkpointing and simple recovery? Batched is usually simpler.
4. Do you need maximum throughput and better latency under mixed workloads? Worker pool is usually better.
5. Do you have strong requirements for ordering by group? Batched can reduce complexity.

A practical approach is to start with batched concurrency for simpler systems, then move to a worker pool when batch waiting or idle time becomes a bottleneck.
