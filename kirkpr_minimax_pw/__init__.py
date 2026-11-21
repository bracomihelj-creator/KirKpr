"""Vgrajena Minimax Playwright avtomatizacija (brez odvisnosti od Fakturiranje*).

Modul je kopija iz Fakturiranje_ChatGPT/domain (playwright + cdp + web links),
prilagojena za lokalni paket ``kirkpr_minimax_pw``.
"""

from __future__ import annotations

from kirkpr_minimax_pw import minimax_playwright as playwright

__all__ = ["playwright"]
