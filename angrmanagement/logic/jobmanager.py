from __future__ import annotations

import ctypes
import itertools
import logging
import sys
import time
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING

from angrmanagement.logic import GlobalInfo
from angrmanagement.logic.threads import gui_thread_schedule, gui_thread_schedule_async

if TYPE_CHECKING:
    from collections.abc import Callable

    from angrmanagement.data.jobs.job import Job
    from angrmanagement.ui.workspace import Workspace


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class JobContext:
    """JobContext is a context object that is passed to each job to allow it to
    report progress and other information back to the JobManager.
    """

    _job_manager: JobManager
    _job: Job

    def __init__(self, job_manager: JobManager, job: Job):
        self._job_manager = job_manager
        self._job = job

    def set_progress(self, percentage: float, text: str | None = None) -> None:
        self._job_manager.callback_job_set_progress(self._job, percentage, text)


class Worker(Thread):
    """Worker is a thread that runs jobs in the background."""

    job_manager: JobManager
    id_: int

    current_job: Job | None

    def __init__(self, job_manager: JobManager, id_: int):
        super().__init__(name=f"angr-management Worker Thread {id_}", daemon=True)
        self.job_manager = job_manager
        self.id_ = id_
        self.current_job = None

    def run(self) -> None:
        while True:
            if self.job_manager.jobs_queue.empty():
                gui_thread_schedule(GlobalInfo.main_window.progress_done, args=())

            if (
                any(job.blocking for job in self.job_manager.jobs)
                and GlobalInfo.main_window is not None
                and GlobalInfo.main_window.workspace
            ):
                gui_thread_schedule(GlobalInfo.main_window._progress_dialog.hide, args=())

            job = self.job_manager.jobs_queue.get()
            gui_thread_schedule_async(GlobalInfo.main_window.progress, args=("Working...", 0.0, True))

            if any(job.blocking for job in self.job_manager.jobs) and GlobalInfo.main_window.isVisible():
                gui_thread_schedule(GlobalInfo.main_window._progress_dialog.show, args=())

            try:
                self.current_job = job
                ctx = JobContext(self.job_manager, job)
                ctx.set_progress(0)

                log.info('Job "%s" started', job.name)
                job.start_at = time.time()
                result = job.run(ctx)
                now = time.time()
                duration = now - job.start_at
                log.info('Job "%s" completed after %.2f seconds', job.name, duration)

                self.current_job = None
            except (Exception, KeyboardInterrupt) as e:  # pylint: disable=broad-except
                sys.last_traceback = e.__traceback__
                self.current_job = None
                log.exception('Exception while running job "%s":', job.name)
                if self.job_manager.job_worker_exception_callback is not None:
                    self.job_manager.job_worker_exception_callback(job, e)
            else:
                self.job_manager.jobs.remove(job)
                gui_thread_schedule_async(job.finish, args=(result,))

    def keyboard_interrupt(self) -> None:
        """Called from the GUI thread when the user presses Ctrl+C or presses a cancel button"""
        # lol. lmao even.
        if self.ident is not None:
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_long(self.ident), ctypes.py_object(KeyboardInterrupt)
            )
            if res != 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(self.ident), 0)
                log.error("Failed to interrupt thread")


class JobManager:
    """JobManager is responsible for managing jobs and running them in a separate thread."""

    workspace: Workspace

    jobs: list[Job]
    jobs_queue: Queue[Job]
    worker_thread: Worker | None

    job_worker_exception_callback: Callable[[Job, BaseException], None] | None
    _job_id_counter: itertools.count

    _gui_last_updated_at: float
    _last_text: str | None

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

        self.jobs = []
        self.jobs_queue = Queue()
        self.worker_thread = None
        self.job_worker_exception_callback = None
        self._job_id_counter = itertools.count()
        self._gui_last_updated_at = 0.0
        self._last_text = None

        self._start_worker()

    def add_job(self, job: Job) -> None:
        self.jobs.append(job)
        self.jobs_queue.put(job)

    def cancel_job(self, job: Job) -> None:
        if job in self.jobs:
            self.jobs.remove(job)
        if self.worker_thread is not None and self.worker_thread.current_job == job:
            self.worker_thread.keyboard_interrupt()

    def interrupt_current_job(self) -> None:
        """Notify the current running job that the user requested an interrupt. The job may ignore it."""
        # Due to thread scheduling, current_job reference *must* first be saved on the stack. Accessing self.current_job
        # multiple times will lead to a race condition.
        if self.worker_thread is not None:
            current_job = self.worker_thread.current_job
            if current_job:
                self.worker_thread.keyboard_interrupt()

    def join_all_jobs(self, wait_period: float = 2.0) -> None:
        """
        Wait until self.jobs is empty for at least `wait_period` seconds.

        This is because one job may add another job upon completion. We cannot simply wait until self.jobs becomes
        empty.
        """

        last_has_job = time.time()
        while time.time() - last_has_job <= wait_period:
            while self.jobs:
                last_has_job = time.time()
                time.sleep(0.05)

    def _start_worker(self) -> None:
        self.worker_thread = Worker(self, next(self._job_id_counter))
        self.worker_thread.start()

    # Job callbacks

    def callback_job_set_progress(self, job: Job, percentage: float, text: str | None) -> None:
        delta = percentage - job.progress_percentage

        if (delta > 0.02 or self._last_text != text) and time.time() - self._gui_last_updated_at >= 0.1:
            self._gui_last_updated_at = time.time()
            job.progress_percentage = percentage
            status_text = f"{job.name}: {text}" if text else job.name
            gui_thread_schedule_async(GlobalInfo.main_window.progress, args=(status_text, percentage))

    # Private methods
