"""Explicit action registration; automatic app discovery is not wired yet."""

from bloomerp.utils.registry import BaseRegistry

from .builtins import BUILTIN_ACTIONS
from .definition import BehaviorActionDefinition

ACTION_REGISTRY = BaseRegistry(BehaviorActionDefinition)
for action in BUILTIN_ACTIONS:
    ACTION_REGISTRY.register(action.id, action)
