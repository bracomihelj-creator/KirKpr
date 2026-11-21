"""Povezave v spletni Minimax (WebUI seja + CommonWeb)."""
from __future__ import annotations

MINIMAX_COMMONWEB_BASE = "https://moj.minimax.si/SI/CommonWeb/"
MINIMAX_ZACETEK_URL = "https://moj.minimax.si/SI/VA/WebUI/Zacetek/Zacetek.aspx"
# Seznam »Moje organizacije« (RepeaterMojeOrganizacije) — primarni URL z login=1.
MINIMAX_ORG_LIST_URL = f"{MINIMAX_ZACETEK_URL}?login=1"
MINIMAX_ORG_SELECT_URL = "https://moj.minimax.si/SI/VA/WebUI/Zacetek/ZacetekOrganizacije.aspx"
MINIMAX_LOGIN_URL = "https://moj.minimax.si/SI/VA/WebUI/login/login.aspx"
MINIMAX_RECEIVED_INVOICES_HASH = "#/received-invoices"
MINIMAX_CUSTOMERS_HASH = "#/customers"
MINIMAX_PREJET_RACUN_VIEW_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/PrejetRacun/PrejetRacunViewBeta.aspx"
)
MINIMAX_PREJET_RACUN_LIST_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/PrejetRacun/PrejetRacunBeta.aspx"
)
MINIMAX_PREJET_RACUN_EDIT_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/PrejetRacun/PrejetRacunEditBeta.aspx"
)
MINIMAX_PLACILNI_NALOG_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/PlacilniNalog/PlacilniNalog.aspx"
)
MINIMAX_PLACILNI_NALOG_MASOVNO_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/PlacilniNalog/MasovneObdelave.aspx"
)
MINIMAX_STRANKA_VIEW_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/Stranka/StrankaView.aspx"
)
MINIMAX_STRANKA_EDIT_URL = (
    "https://moj.minimax.si/SI/VA/WebUI/Stranka/StrankaEdit.aspx"
)


def minimax_url_with_organisation(base: str, org_id: str) -> str:
    """Doda ?OrganisationId= — deluje v klasičnem WebUI (Zacetek, ObracunDDV …)."""
    url = (base or MINIMAX_COMMONWEB_BASE).strip() or MINIMAX_COMMONWEB_BASE
    org = str(org_id or "").strip()
    if not org.isdigit():
        return url
    if "organisationid=" in url.casefold():
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}OrganisationId={org}"


def minimax_client_zacetek_url(org_id: str) -> str:
    """Preklop stranke — klasični WebUI (nastavi sejo)."""
    return minimax_url_with_organisation(MINIMAX_ZACETEK_URL, org_id)


def minimax_client_commonweb_url(org_id: str) -> str:
    """Alias: preklop stranke prek Zacetek (CommonWeb ?OrganisationId ne deluje)."""
    if str(org_id or "").strip().isdigit():
        return minimax_client_zacetek_url(org_id)
    return MINIMAX_COMMONWEB_BASE


def minimax_customers_spa_url(org_id: str = "") -> str:
    """Šifrant strank (CommonWeb SPA). Org iz seje (Zacetek)."""
    _ = org_id
    return f"{MINIMAX_COMMONWEB_BASE.rstrip('/')}{MINIMAX_CUSTOMERS_HASH}"


def minimax_received_invoices_url(org_id: str = "") -> str:
    """
    Prejeti računi (CommonWeb SPA).
    OrganisationId NE gre v query — seja mora biti že nastavljena prek Zacetek.
    """
    _ = org_id
    return f"{MINIMAX_COMMONWEB_BASE.rstrip('/')}{MINIMAX_RECEIVED_INVOICES_HASH}"


def minimax_received_invoice_list_url(org_id: str = "") -> str:
    """Seznam prejetih računov (WebUI Beta). Org iz aktivne seje (param se ignorira)."""
    _ = org_id
    return MINIMAX_PREJET_RACUN_LIST_URL


def minimax_received_invoice_view_url(received_invoice_id: str, org_id: str = "") -> str:
    """
    Pregled osnutka PR (WebUI Beta): ?pr_id=...&pgat=pgatv.
    Deluje, ko je aktivna seja na pravi organizaciji (sicer »Sistemska napaka«).
    """
    _ = org_id
    rid = str(received_invoice_id or "").strip()
    if not rid.isdigit():
        return minimax_received_invoices_url()
    return f"{MINIMAX_PREJET_RACUN_VIEW_URL}?pr_id={rid}&pgat=pgatv"


def minimax_client_org_select_url() -> str:
    """Seznam podjetij — ročna izbira, če Zacetek ne preklopi."""
    return MINIMAX_ORG_LIST_URL


def minimax_org_list_urls() -> tuple[str, ...]:
    """URL-ji s seznamom firm — ZacetekOrganizacije.aspx pogosto prazen."""
    return (
        MINIMAX_ORG_LIST_URL,
        MINIMAX_ZACETEK_URL,
    )


def minimax_payment_order_from_received_url(received_invoice_id: str) -> str:
    """Ustvari plačilni nalog iz prejetega računa (WebUI): ?pgat=pgatdr&prkn=."""
    rid = str(received_invoice_id or "").strip()
    if not rid.isdigit():
        return MINIMAX_PLACILNI_NALOG_URL
    return f"{MINIMAX_PLACILNI_NALOG_URL}?pgat=pgatdr&prkn={rid}"


def minimax_payment_order_mass_export_url() -> str:
    """Množični izvoz neplačanih plačilnih nalogov (SEPA XML)."""
    return (
        f"{MINIMAX_PLACILNI_NALOG_MASOVNO_URL}?pgat=pgate"
        "&obfi=DatumZapadlosti&obft=obft_a&appMFV=,&Operacija=Izvoz&StatusPlacila=Neplacani"
    )


def minimax_stranka_view_url(st_id: str) -> str:
    """Pregled vnosa v šifrantu strank (WebUI klasično) — st_id = CustomerId v org stranke."""
    sid = str(st_id or "").strip()
    if not sid.isdigit():
        return MINIMAX_STRANKA_VIEW_URL
    return f"{MINIMAX_STRANKA_VIEW_URL}?st_id={sid}&pgat=pgatv"


def minimax_stranka_edit_url(st_id: str) -> str:
    """Urejanje vnosa v šifrantu strank — enako kot klik «Uredi» na StrankaView."""
    sid = str(st_id or "").strip()
    if not sid.isdigit():
        return MINIMAX_STRANKA_EDIT_URL
    return f"{MINIMAX_STRANKA_EDIT_URL}?st_id={sid}&pgat=pgate"
