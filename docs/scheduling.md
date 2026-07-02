# Scheduling

The standalone `scheduling/` package (`RecurringScheduler`) and
`workflows/scheduler.py` (`WorkflowScheduler`) were deleted: they were never
integrated into the orchestrator loop and had zero production callers.
Recurring 9TO5 runs are launched externally (cron / Task Scheduler +
`python main.py`), and in-run sequencing is owned by the orchestrator itself.
For crash-resilient long runs see
`platform_core.runtime.resilience.run_with_recovery`.
