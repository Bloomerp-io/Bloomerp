"""Project-owned Django settings shared by every environment.

Bloomerp project configuration belongs in .bloomerp/project.bloomerp.toml and
is read from .bloomerp/project.bloomerp.toml when settings load.
"""
from .generated.common import MIDDLEWARE

MIDDLEWARE = MIDDLEWARE + ["debug_toolbar.middleware.DebugToolbarMiddleware"]