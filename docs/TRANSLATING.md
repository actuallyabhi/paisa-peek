# Languages & translating

Paisapeek ships in English, हिन्दी and **Hinglish** (`hi-latn`, Hindi in Latin letters). Switch under **More → Language**; until you pick one, your browser's language is used.

It's standard Django i18n:
- UI text is marked with `{% translate %}` / `gettext` in the code.
- `makemessages` extracts it into one `.po` file per language, at `ledger/locale/<code>/LC_MESSAGES/django.po`.
- `compilemessages` builds the `.mo` that Django loads.

**Add a language**, e.g. Marathi:

1. Add `("mr", "मराठी")` to `LANGUAGES` in `config/settings.py`.
2. Extract the strings:
   ```bash
   cd ledger && uv run ../manage.py makemessages -l mr --ignore tests.py
   ```
3. Translate the `msgstr` lines in `ledger/locale/mr/LC_MESSAGES/django.po`, using any `.po` editor (Poedit, Weblate, or a text editor).
4. Compile:
   ```bash
   uv run manage.py compilemessages
   ```
   Then run the tests; `test_catalog_is_complete` fails if a string is untranslated or not compiled.

A few notes:
- Default category names are translated for display. Names you create stay as you typed them.
- Dates, AM/PM and common form errors are also in our catalogs (`ledger/i18n_data.py`). That fixes Django's Hindi spellings, and stops Devanagari leaking into Hinglish, because gettext falls back from `hi_Latn` to `hi`.
- CSV column names stay in English.
