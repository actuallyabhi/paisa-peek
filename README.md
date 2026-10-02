<p align="center"><img src="ledger/static/ledger/icon.svg" width="96" alt="Paisapeek logo: a gold rupee coin"></p>

# Paisapeek

> *Peek at your paisa. Keep more of it.*

Paisapeek is a self-hosted money diary for people who want to know where every penny goes, without handing their bank SMS to a cloud app.

- **Tell it what you spent.** Type or dictate *"450 petrol, 200 chai with Rohan, lent 500 to Priya"* and review the cards before adding them.
- **Bank SMS turn into transactions automatically.** Duplicates are merged and you confirm each one in an inbox.
- **People and companies.** Track who owes you and whom you owe, with each person's history.
- **Accounts.** Savings, cards, credit lines and cash, with real balances and card statement and due-date reminders.
- **Recurring income and bills,** with push reminders and one-tap Paid / Received.
- **Android app** that reads bank SMS itself (no forwarder app needed). It notifies you about each one, so you can confirm or ignore it from the notification, and has a native review inbox. The rest of the site runs inside the app.
- **Installable on your phone (PWA),** with light and dark themes. It works on mobile first.
- **English, हिन्दी and Hinglish.** Adding a language is one `.po` file.
- **Full JSON backup and restore, plus CSV import and export.**

Built with Django, Django Ninja, HTMX and Tailwind, on SQLite. It's a single Docker volume. The Android app is Kotlin, with Jetpack Compose and Material 3 Expressive for the review inbox.

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
- **[Adding SMS templates](docs/SMS_TEMPLATES.md)**: teach Paisapeek a new bank's SMS format.
- **[Android app](android/README.md)**: install, build, test with fake SMS, and publish a release.

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

Android app (needs the Android SDK and JDK 17+; details in [android/README.md](android/README.md)):

```bash
cd android && ./gradlew installDebug   # build and install on a USB-connected phone
```

Adding a bank's SMS format or a new language? See [SMS_TEMPLATES.md](docs/SMS_TEMPLATES.md) and [TRANSLATING.md](docs/TRANSLATING.md).

## Roadmap

**Done**
- [x] Transactions, accounts, categories, login
- [x] SMS ingest, bank templates, dedupe, review inbox
- [x] Ramble mode (voice/typed multi-transaction entry) + tags
- [x] People & companies ledger (lent/borrowed/repaid) + CSV import
- [x] Week/month home, mobile UI + installable PWA, accounts with balances, recurring income/bills/transfers, push reminders
- [x] Full backup/restore, CSV export, Caddy HTTPS and own-proxy Docker setups
- [x] Charts, global search, pagination, English/हिन्दी/Hinglish, dark mode
- [x] **Android app**: reads bank SMS directly; a notification per SMS with Confirm / Review / Ignore; a native review inbox in Material 3 Expressive (suggests people as you type, Undo); the rest of the site runs inside the app; signed APKs built by GitHub Actions on every release
- [x] Savings interest: rate and credit frequency per account; the scheduler estimates interest on daily balances on each credit date (to the Inbox, or auto-confirmed)
- [x] Category detection from merchant names: keywords for every category (salon → Personal Care, tuition → Education…), matched inside UPI/card names, the rest of the SMS and manual entries; your rules and past choices still come first
- [x] **iOS**: SMS capture through a Shortcuts automation ([guide](docs/FEATURES.md#auto-capture-from-sms-android)); iOS doesn't let apps read SMS

**Next**
- [ ] Rules engine + merchant memory ("always categorize X as Y"). SMS ingest should also guess categories, so most SMS notifications can be confirmed in one tap.
- [ ] Screenshot share target (PWA + App) + OCR + optional LLM fallback
- [ ] Budgets per category
- [ ] Bank/credit card statement upload with matching against existing entries
- [ ] Multiple user support on single server.
- [ ] **Cashback on transactions.** An optional "Cashback" field on an expense, filled in by hand, in ₹ or % (e.g. ₹50 or 5%). Plan:
  - It appears on the add/edit form, in the review inbox for SMS transactions (web and Android), and in Ramble ("₹500 at Swiggy, 10% cashback"). It stays collapsed and empty unless you open it.
  - Store the result in ₹ (`cashback` on the transaction). A percentage is worked out from the amount when you save, and recalculated if the amount changes.
  - The full amount still leaves the account; spend, category totals and budgets use the net cost (amount − cashback). The transaction shows "₹500 · ₹50 back".
  - Home and month views show "Cashback earned this month". CSV import and export get a `cashback` column.

**Future**
- [ ] **On-device LLM in the Android app.** Download a small model (around 1–3B parameters, quantized) and run it on the phone to read bank SMS: amount, merchant, account, category and kind. SMS text would then never need to leave the phone. A setting picks the parser:
  - **On-device model:** private, works offline, and costs nothing per message.
  - **LLM via API:** the server's configured `LLM_MODEL` (Ollama or any OpenAI-compatible endpoint).
  - **Built-in templates:** today's regex templates. This stays the fallback when a model is unavailable or unsure.
- [ ] More native Android: a month-spend home-screen widget, a native mic for Ramble, native translations for the review inbox (it is English for now)
