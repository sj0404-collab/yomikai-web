"""Переехало: эта задумка теперь в `ownocr/ideas/archaeologist.py`.

Оставлен тонкий переходник, чтобы старые вызовы не падали. В работе не участвует:
см. docs/ЗАДУМКИ.md.
"""
from .ideas.archaeologist import *                                        # noqa: F401,F403
from .ideas.archaeologist import (Library, build_library, cut_line,        # noqa: F401
                                  glyphs_of_line, read_line, read_line_dp)
