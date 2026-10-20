"""Serialize calibration state without holding the native admission mutex.

Evidence authentication and native API observation can take many seconds.
Enrollment and reconciliation share one reentrant lane lock: maintained
snapshot reconciliation may enroll its ordinary calibration while holding it.
SQLite transactions and unique keys remain the durable cross-restart guards.
Never acquire the broker admission lock while holding this lock.
"""
import threading

LOCK = threading.RLock()
