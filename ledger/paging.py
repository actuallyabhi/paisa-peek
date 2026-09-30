from django.core.paginator import Paginator


def paginate(request, items, per_page=25):
    """Django's Paginator + an elided page range ("1 … 4 5 6 … 12") for ledger/_pagination.html.
    Bad or out-of-range ?page= values fall back gracefully (get_page)."""
    page = Paginator(items, per_page).get_page(request.GET.get("page"))
    page.elided = list(page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1))
    return page
