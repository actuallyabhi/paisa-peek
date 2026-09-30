<p align="center"><img src="ledger/static/ledger/icon.svg" width="96" alt="Paisapeek logo: a gold coin with an eye"></p>

# Paisapeek

> *Peek at your paisa. Keep more of it.*

Paisapeek is a self-hosted money diary for people who want to know where every penny goes, without handing their bank SMS to a cloud app.

- **Tell it what you spent.** Type or dictate *"450 petrol, 200 chai with Rohan, lent 500 to Priya"* and review the cards before adding them.
- **Bank SMS turn into transactions automatically.** Duplicates are merged and you confirm each one in an inbox.
- **People and companies.** Track who owes you and whom you owe, with each person's history.
- **Accounts.** Savings, cards, credit lines and cash, with real balances and card statement and due-date reminders.
- **Recurring income and bills,** with push reminders and one-tap Paid / Received.
- **Installable on your phone (PWA),** with light and dark themes. It works on mobile first.
- **English, हिन्दी and Hinglish.** Adding a language is one `.po` file.
- **Full JSON backup and restore, plus CSV import and export.**

Built with Django, Django Ninja, HTMX and Tailwind, on SQLite. It's a single Docker volume.

## Screenshots

<sub>Phone-sized, with made-up demo data.</sub>

<table>
<tr><td align="center" valign="top"><img src="docs/screenshots/01-home.webp" width="240" alt="Home: say or type what you spent"><br><sub>Home: say or type what you spent</sub></td><td align="center" valign="top"><img src="docs/screenshots/02-ramble.webp" width="240" alt="Ramble → review cards before adding"><br><sub>Ramble → review cards before adding</sub></td><td align="center" valign="top"><img src="docs/screenshots/03-charts.webp" width="240" alt="Day by day + spent vs came in"><br><sub>Day by day + spent vs came in</sub></td></tr>
<tr><td align="center" valign="top"><img src="docs/screenshots/04-people.webp" width="240" alt="People: who owes whom"><br><sub>People: who owes whom</sub></td><td align="center" valign="top"><img src="docs/screenshots/05-person.webp" width="240" alt="A person's ledger over time"><br><sub>A person's ledger over time</sub></td><td align="center" valign="top"><img src="docs/screenshots/06-accounts.webp" width="240" alt="Accounts, cards & balances"><br><sub>Accounts, cards & balances</sub></td></tr>
<tr><td align="center" valign="top"><img src="docs/screenshots/07-recurring.webp" width="240" alt="Recurring income, bills & transfers"><br><sub>Recurring income, bills & transfers</sub></td><td align="center" valign="top"><img src="docs/screenshots/08-inbox.webp" width="240" alt="Bank SMS waiting for review"><br><sub>Bank SMS waiting for review</sub></td><td align="center" valign="top"><img src="docs/screenshots/09-search.webp" width="240" alt="Search everything"><br><sub>Search everything</sub></td></tr>
<tr><td align="center" valign="top"><img src="docs/screenshots/10-more.webp" width="240" alt="More: language, charts, notifications, backup"><br><sub>More: language, charts, notifications, backup</sub></td><td align="center" valign="top"><img src="docs/screenshots/11-home-dark.webp" width="240" alt="Dark mode"><br><sub>Dark mode</sub></td><td align="center" valign="top"><img src="docs/screenshots/12-home-hindi.webp" width="240" alt="हिन्दी"><br><sub>हिन्दी</sub></td></tr>
<tr><td align="center" valign="top"><img src="docs/screenshots/13-people-hinglish.webp" width="240" alt="Hinglish"><br><sub>Hinglish</sub></td></tr>
</table>

## Docs

- **[Deploy it on your server](DEPLOY.md)**: Docker, automatic HTTPS, your own reverse proxy, phone install, backups.
- **[Features guide](docs/FEATURES.md)**: Ramble, SMS auto-capture, accounts, people, notifications, CSV import, backup & restore.
- **[Languages & translating](docs/TRANSLATING.md)**: switching language, adding a new one.

## Develop

```bash
uv sync
uv run manage.py migrate
uv run manage.py createsuperuser
DEBUG=1 uv run manage.py runserver
uv run manage.py test ledger
uv run tailwindcss -i ledger/tailwind.css -o ledger/static/ledger/app.css --minify   # after changing classes
```

Data (the SQLite database and a generated secret key) is stored in `./data`, or wherever `DATA_DIR` points.

Adding a bank's SMS format or a new language? See [Auto-capture from SMS](docs/FEATURES.md#auto-capture-from-sms-android) and [TRANSLATING.md](docs/TRANSLATING.md).

## Roadmap

**Done**
- [x] Transactions, accounts, categories, login
- [x] SMS ingest, bank templates, dedupe, review inbox
- [x] Ramble mode (voice/typed multi-transaction entry) + tags
- [x] People & companies ledger (lent/borrowed/repaid) + CSV import
- [x] Week/month home, mobile UI + installable PWA, accounts with balances, recurring income/bills/transfers, push reminders
- [x] Full backup/restore, CSV export, Caddy HTTPS and own-proxy Docker setups
- [x] Charts, global search, pagination, English/हिन्दी/Hinglish, dark mode

**Next**
- [ ] Rules engine + merchant memory ("always categorize X as Y")
- [ ] Screenshot share target (PWA) + OCR + optional LLM fallback
- [ ] Budgets per category
- [ ] Bank/credit card statement upload with matching against existing entries
- [ ] Interest on savings accounts: rate and credit frequency per account, with a scheduled job that adds the interest

**Future**
- [ ] Native **Android** client app (reads bank SMS directly, no forwarder app needed)
- [ ] Native **iOS** client app
