"""Reproduce stored measurements with their retained checker implementation.

Current checker results must be reported separately: a new evidence requirement
does not manufacture an observation in a previously captured trace.
"""
from dataclasses import fields
import importlib.util
from pathlib import Path
import sys


def recorded_audit(record, intent, study):
    filenames = {'extension': 'frozen-extension-audit.py',
                 'observed': 'frozen-sequential-audit.py'}
    path = Path(__file__).resolve().parents[2] / 'evidence/source-snapshots' / filenames[study]
    name = '_retryscope_retained_' + study
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    names = {field.name for field in fields(module.AuditIntent)}
    config = {key: value for key, value in intent.to_dict().items() if key in names}
    return module.audit(record, module.AuditIntent(**config))
