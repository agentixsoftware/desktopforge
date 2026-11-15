"""Privileged-helper core: grants, evidence, journal, handle-based file operations.

Standard library only, relative imports only, so the same files can be installed
root-owned outside the user's checkout. Nothing in the GUI or CLI calls this
package, and it does not enable installation. Currently exercised only by the
disposable-VM lab helper (see docs/LAB_HELPER.md).
"""
