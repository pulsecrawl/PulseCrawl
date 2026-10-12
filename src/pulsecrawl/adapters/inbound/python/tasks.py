"""Cross-thread cancellation of locally owned asyncio execution tasks."""

import threading


class ExecutionTaskRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks = {}

    def register(self, execution_id, task):
        if task is not None:
            with self._lock:
                self._tasks[execution_id] = task

    def unregister(self, execution_id, task):
        with self._lock:
            if self._tasks.get(execution_id) is task:
                self._tasks.pop(execution_id, None)

    def cancel(self, execution_id):
        with self._lock:
            task = self._tasks.get(execution_id)
        if task is not None:
            task.get_loop().call_soon_threadsafe(task.cancel)
