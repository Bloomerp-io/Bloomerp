"""Explicit action registration; automatic app discovery is not wired yet."""

from bloomerp.utils.registry import BaseRegistry
from .definition import BehaviorActionDefinition
from .builtins import BUILTIN_ACTIONS

ACTION_REGISTRY = BaseRegistry(BehaviorActionDefinition)
for action in BUILTIN_ACTIONS:
    ACTION_REGISTRY.register(action.id, action)
