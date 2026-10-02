# Paisapeek features

A tour of what Paisapeek does and how to set each part up. For installing it, see [DEPLOY.md](../DEPLOY.md).

- [On your phone (PWA)](#on-your-phone-pwa)
- [Ramble: say several transactions at once](#ramble-say-several-transactions-at-once)
- [Auto-capture from SMS (Android)](#auto-capture-from-sms-android)
- [Accounts](#accounts)
- [People & companies (lent / borrowed)](#people--companies-lent--borrowed)
- [Notifications](#notifications)
- [Import CSV](#import-csv)
- [Backup, restore & export](#backup-restore--export)

## On your phone (PWA)

Paisapeek is built for the phone:
- a bottom tab bar
- the Ramble box at the top of Home
- Home can show a week or a month, with spending grouped by day

**Install it:**
- **Android (Chrome):** menu ⋮ → *Install app*.
- **iPhone (Safari):** Share → *Add to Home Screen*.

Installing needs **HTTPS**. Put Caddy or Tailscale Serve in front of the server, and set `CSRF_TRUSTED_ORIGINS` (see [`.env.example`](../.env.example)).

## Ramble: say several transactions at once

Use the box at the top of **Home** and dictate with your keyboard's mic, or type, e.g. *"yesterday 450 petrol, 200 chai with Rohan for Goa trip and 1.2k swiggy on HDFC card. Got 5000 from Kabir last Friday."*

You get one editable card per transaction, with date, amount, type, description, category, account and tags filled in. Then choose **Add selected** or **Add just this** on each card.

A card that matches something already recorded (e.g. the same ₹450 that came in by SMS) is flagged and starts unticked.

**Built-in parser (default)** needs no setup:
- It understands amounts (`1.2k`, `Rs. 450`), today, yesterday, "3 days ago" and weekdays.
- A date said once carries on to the following items.
- Categories come from what you used last time for similar descriptions, then from keywords.

**Local LLM (optional)**, for messier speech:
- Set `LLM_MODEL` (and `LLM_BASE_URL`) to any OpenAI-compatible endpoint. Ollama is the default (see [`.env.example`](../.env.example)).
- Its output is still checked:
  - categories and accounts must exist
  - future dates are clamped to today
  - a tag must already exist or be said in the text
- If the LLM is unreachable, the built-in parser takes over.

## Auto-capture from SMS (Android)

**With the Paisapeek Android app (easiest):**
1. Download the APK from [GitHub Releases](https://github.com/actuallyabhi/paisa-peek/releases) and install it. It isn't on the Play Store, because Google only allows SMS permissions for default SMS apps.
2. Open it, paste the URL shown under **More → SMS auto-capture**, tap **Save**, then allow SMS and notifications.

Each bank SMS becomes a notification. Tap **Confirm** to save it as-is, **Review** to pick a category in the app's inbox, or **Ignore**. The app's Inbox tab is a native screen: spends get a category picker, and money in asks what it was and who sent it, with your existing people suggested as you type. If you're offline, the app retries until the SMS goes through.
- Only SMS from alphanumeric senders (`VM-HDFCBK`, …) are sent. SMS from personal numbers never leave the phone.
- To change the server, long-press the app icon and choose **SMS setup**.
- Push reminders don't work inside the app. Keep the PWA installed from Chrome if you use them.
- Building it yourself, testing, and releases: [android/README.md](../android/README.md).

**With a forwarder app instead:**
1. Install an SMS forwarder, for example **SMS to URL Forwarder** (F-Droid), MacroDroid or Tasker.
2. Filter by your banks' sender IDs (`HDFCBK`, `ICICIB`, `AXISBK`, `SBI`, `KOTAKB`, …).
3. POST to the URL shown under **More → SMS auto-capture**, `https://<host>/api/ingest/sms?token=<token>`, with this JSON body:
   ```json
   {"sender": "%from%", "text": "%text%", "ts": "%receivedStamp%"}
   ```
   Placeholder syntax depends on the app; `ts` is optional (unix seconds or ms).

**iPhone:** iOS doesn't let apps read SMS, but a Shortcuts automation can forward them:
1. Shortcuts → **Automation** → **+** → **Message**. Set *Message Contains* to `Rs` (add another automation for `INR`), then choose **Run Immediately**.
2. Add **Get Contents of URL** with the URL from **More → SMS auto-capture**, *Method* `POST` and *Request Body* `JSON`. Add the fields `sender` = *Shortcut Input → Sender* and `text` = *Shortcut Input → Content*.

Interactive API docs are at `/api/docs`.

Parsed transactions land in **Inbox** as *pending*: confirm them with a category, or ignore them.
- OTP, offer and due-reminder messages are dropped.
- Duplicates are merged: the same UPI ref, or the same message sent again.
- Unknown card or account numbers create a placeholder account.

**Add support for another bank:** add a template in Admin, a regex with named groups `amount`, `merchant`, `last4`, `date` and `ref`. To ship it as a default for everyone, see [Adding SMS templates](SMS_TEMPLATES.md).

## Accounts

Under **More → Accounts** you can add savings/current accounts, credit cards, credit lines, loans, cash and wallets.

- **Current balance:** enter what your bank shows now (for cards and loans, the amount you owe). The app works out the rest from your transactions, and you can re-enter it at any time to reconcile.
- **Default account:** one account is pre-selected for manual entries, Ramble and CSV rows.
- **Cash:** a **Cash** wallet account is there from the start. Log cash spends against it, by picking it on the form or by saying "cash" in Ramble ("80 cash chai"). An ATM withdrawal SMS arrives in the Inbox as a *Transfer* from your bank account to Cash, and a cash deposit SMS as a Transfer from Cash to the bank. Neither counts as spending or income: the spending is counted when you log what you bought with the cash. Re-enter Cash's current balance whenever you count your wallet.
- **Card bill payments:** record paying a card as a *Transfer* from savings to the card. Both balances move, and it doesn't count as spending.
- **Savings interest:** on a savings account, set the interest rate (% a year), how often it's credited (monthly, quarterly, half-yearly or yearly) and the next credit date. If you leave the date blank, it defaults to the end of the current period, for example 30 Sep for quarterly. On each credit date the scheduler works out interest on the account's daily closing balance, the way banks do. The estimate goes to the Inbox as income, so you can match it to your bank's figure and confirm it, and a push notification tells you. Turn on **More → Notifications → Auto-confirm savings interest** to have it added straight to the account instead. If the scheduler was down over a credit date, the missed entries are added on its next run.

## People & companies (lent / borrowed)

Every transaction can be linked to a person or company. Type a name in the **Person / company** field; a new name is created on save.

Four types track money between you and them:

| Type | Effect on what they owe you |
|---|---|
| **Lent** | + |
| **Repaid to me** | − |
| **Borrowed** | − |
| **Repaid by me** | + |

- **People** is the dashboard: total owed to you, total you owe, the net, and a balance per person. Settled people are hidden.
- Each person's page shows their full ledger with a running balance, and has a quick form to record a new entry.
- Ramble understands phrases like *"lent 500 to Rohan"*, *"Priya paid back 2000"* and *"borrowed 1500 from Chacha ji"*.

## Notifications

Enable them under **More → Notifications** on each device. These are Web Push notifications, so the phone needs the installed PWA over HTTPS.

What you can get:
- a daily *"Log today's spending"* reminder, at a time you choose
- recurring income (salary, stipend) and bills/subscriptions, on the date or N days before (the **Recurring** tab, where **Received**/**Paid** logs the transaction and moves the date on)
- credit card **statement day** and **payment due day** reminders, set on each card

The `scheduler` service in [`docker-compose.yml`](../docker-compose.yml) sends them (`python manage.py reminders --loop`). Set `VAPID_SUBJECT=mailto:you@example.com` in `.env`; Apple's push service rejects placeholder addresses.

## Import CSV

**More → Import CSV** takes a CSV and shows every row on the same review cards as Ramble, so nothing is saved until you add it. Rows that already exist are flagged and unticked, so importing the same file twice is safe.

```csv
date,type,amount,description,party,category,account,tags,notes
2026-01-24,expense,500,Pizzahut,,Food & Outings,,JAN 24-25 Outing,
,lent,3000 + 1800,Lent,Arjun,,,,
2026-02-10,repaid_to_me,2000,Paid back via UPI,Arjun,,HDFC xx1234,,
```

Only `amount` is required.

| Column | Accepts |
|---|---|
| `date` | `YYYY-MM-DD` or `DD/MM/YYYY`; blank uses the date you pick on upload |
| `type` | `expense` (default), `income`, `transfer`, `lent`, `borrowed`, `repaid_to_me`, `repaid_by_me` |
| `amount` | `450`, `1,23,456.50`, or an Excel-style breakdown `720 + 775 + 380` (summed; the breakdown goes into notes) |
| `party` | a name; required for loan types, created if new |
| `category`, `account` | an existing name; the account can also be its last 4 digits. A blank category is guessed. |
| `tags` | separated by `;` |

[`ledger/static/ledger/import-sample.csv`](../ledger/static/ledger/import-sample.csv) is a small example to start from.

## Backup, restore & export

**More → Backup & restore**, or the welcome card on a fresh install, offers three things.

**Export full backup (.json)** holds everything:
- accounts and balances
- people and companies with their lent/borrowed history
- transactions with tags and times
- recurring bills
- categories and SMS templates
- notification settings and the SMS token

It restores on any Paisapeek install. The `data` inside is Django's standard serialization, so `manage.py loaddata` reads it, and the Restore button accepts plain `manage.py dumpdata ledger` output too. Login users and push-enabled devices aren't included. The file contains your SMS token, so keep it private.

**Restore** replaces all current data in one step: if anything in the file is bad, nothing changes. Before overwriting, it saves the current data to `DATA_DIR/backups/before-restore-*.json`.

**Export transactions (.csv)** is for Excel/Sheets and uses the same columns as Import CSV, so it imports back. The JSON backup is the one that keeps everything; CSV import skips `time`, `to_account` and `status`.
