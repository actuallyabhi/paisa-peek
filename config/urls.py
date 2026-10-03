from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from ledger import views
from ledger.api import api

urlpatterns = [
    path("", views.home, name="home"),
    path("txns/", RedirectView.as_view(pattern_name="home", query_string=True)),
    path("sw.js", views.service_worker),
    path("favicon.ico", RedirectView.as_view(url="/static/ledger/favicon-32.png", permanent=True)),  # browsers ask for it
    path("txns/<int:pk>/", views.txn_edit, name="txn_edit"),
    path("txns/<int:pk>/split/", views.txn_split, name="txn_split"),
    path("txns/<int:pk>/delete/", views.txn_delete, name="txn_delete"),
    path("txns/<int:pk>/status/", views.txn_status, name="txn_status"),
    path("inbox/", views.inbox, name="inbox"),
    path("share/", views.share, name="share"),
    path("categories/", views.categories, name="categories"),
    path("search/", views.search, name="search"),
    path("ramble/", RedirectView.as_view(pattern_name="home")),
    path("ramble/parse/", views.ramble_parse, name="ramble_parse"),
    path("ramble/save/", views.ramble_save, name="ramble_save"),
    path("ramble/add/<int:i>/", views.ramble_add_one, name="ramble_add_one"),
    path("people/", views.people, name="people"),
    path("people/<int:pk>/", views.party, name="party"),
    path("import/", views.import_csv, name="import_csv"),
    path("accounts/", views.accounts, name="accounts"),
    path("accounts/new/", views.account_edit, name="account_new"),
    path("accounts/<int:pk>/", views.account_edit, name="account_edit"),
    path("recurring/", views.recurring, name="recurring"),
    path("recurring/<int:pk>/", views.recurring_edit, name="recurring_edit"),
    path("recurring/<int:pk>/done/", views.recurring_done, name="recurring_done"),
    path("settings/", views.settings_page, name="settings"),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("backup/export/", views.backup_export, name="backup_export"),
    path("backup/export.csv", views.backup_export_csv, name="backup_export_csv"),
    path("backup/restore/", views.backup_restore, name="backup_restore"),
    path("push/test/", views.push_test, name="push_test"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("i18n/", include("django.conf.urls.i18n")),  # POST /i18n/setlang/ — the language switcher
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
