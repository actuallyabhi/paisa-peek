# Paisapeek for Android

The app reads bank SMS itself and posts them to your Paisapeek server. You get one notification per SMS and review them in a native inbox. Everything else is your Paisapeek site running inside the app.

- **Bank SMS capture:** only SMS from alphanumeric senders (`VM-HDFCBK`, …) are sent. SMS from personal numbers never leave the phone. If you're offline, the app retries until each message goes through.
- **Notifications:** each captured SMS shows the amount and merchant.
  - **Confirm** saves it as-is. It appears only when a category is already set, or for money in.
  - **Review** opens the inbox when a category still needs picking.
  - **Ignore** drops it.
- **Review inbox (native, Material 3 Expressive):**
  - Spends get a category picker.
  - Money in asks *Income / Borrowed / Repaid to me* and who sent it. The person field suggests people you already have, or adds a new one.
  - Undo works for both confirm and ignore. Pull down to refresh.
- **Everything else** is the regular site. The Inbox tab opens the native screen, and **Edit** on a card opens the web edit page.

It isn't on the Play Store, because Google only allows SMS permissions for default SMS apps. Install the APK from [GitHub Releases](https://github.com/actuallyabhi/paisa-peek/releases).

## Install and set up

1. Download `paisapeek-vX.Y.Z.apk` from the latest release and open it. Allow "Install unknown apps" for your browser or file manager when asked.
2. In Paisapeek on the web, open **More → SMS auto-capture** and copy the URL.
3. Open the app, paste the URL, tap **Save**, then allow SMS and notifications.
   - On Android 13+, if SMS access is greyed out, go to Settings → Apps → Paisapeek → ⋮ → **Allow restricted settings** first.
4. To change the server later, long-press the app icon and choose **SMS setup**.

Push reminders from the website don't work inside the app, because Android's in-app browser doesn't support web push. Keep the PWA installed from Chrome if you use reminders. **More → Notifications → Send a test** still works in the app: it shows a notification from the app itself, to check notifications are allowed.

## Build

You need the Android SDK (platform 36) and JDK 17+.

```bash
./gradlew installDebug      # build + install on a USB-connected phone (USB debugging on)
./gradlew assembleDebug     # just build: app/build/outputs/apk/debug/app-debug.apk
```

Debug builds install as a separate app, **Paisapeek (debug)** (`app.paisapeek.debug`), next to the released one, so you can test without losing your real setup. If both apps are set up with a token, both upload each bank SMS. The server merges the duplicate, but you'll get two notifications.

Material 3 Expressive comes from the `1.5.0` alphas. `alpha18` is the newest that builds with AGP 8.13 and compileSdk 36; later alphas need AGP 9.1 and compileSdk 37.

## Test against a local server

Debug builds allow `http://localhost`, and include a hook that lets adb send a fake bank SMS. You can't fake an incoming SMS on a real phone any other way. Neither is in release builds.

1. Start a dev server with a throwaway database. The `budget-apptest` entry in `.claude/launch.json` does this on port 8001:
   ```bash
   DATA_DIR=/tmp/paisapeek-test DEBUG=1 uv run manage.py runserver 8001
   ```
2. Forward the phone's port 8001 to your computer:
   ```bash
   adb reverse tcp:8001 tcp:8001
   ```
3. In the app's **SMS setup**, enter `http://localhost:8001/api/ingest/sms?token=<token>`. Get the token from that server's **More** page, or with `DATA_DIR=/tmp/paisapeek-test uv run manage.py shell -c "from ledger.models import ApiToken; print(ApiToken.current())"`.
4. Send a fake bank SMS. It goes through the same sender filter, upload and notification as a real one:
   ```bash
   adb shell am broadcast -n app.paisapeek.debug/app.paisapeek.FakeSmsReceiver --es sender VM-HDFCBK --es text "'Spent Rs.450.00 On HDFC Bank Card 5678 At SWIGGY On 2026-10-01'"
   ```

## Releasing

Every version tag `vX.Y.Z` pushed to GitHub triggers [`.github/workflows/android-release.yml`](../.github/workflows/android-release.yml). It builds a signed APK and attaches it to the GitHub release for that tag, creating the release with generated notes if there isn't one yet. The version comes from the tag, so there's nothing to bump by hand: `v1.4.2` becomes versionName `1.4.2` and versionCode `10402`.

### One-time: create the signing key

Every release must be signed with **the same key**. Otherwise phones refuse to install the update over the old app, and users have to uninstall, which loses the app's settings. Back the key and its password up somewhere safe, like a password manager. Never commit it.

```bash
keytool -genkeypair -v -keystore paisapeek-release.jks -alias paisapeek -keyalg RSA -keysize 4096 -validity 10000
```

Then add four repository secrets (GitHub → Settings → Secrets and variables → Actions), or use the `gh` CLI:

```bash
base64 -i paisapeek-release.jks | gh secret set ANDROID_KEYSTORE_BASE64
gh secret set ANDROID_KEYSTORE_PASSWORD
gh secret set ANDROID_KEY_ALIAS --body paisapeek
gh secret set ANDROID_KEY_PASSWORD
```

`gh secret set` without `--body` prompts for the value, so passwords stay out of your shell history. If you didn't set a separate key password, `ANDROID_KEY_PASSWORD` is the same as the keystore password.

### Each release

```bash
git tag v1.0.0
git push origin v1.0.0
```

Or create the release and tag in one step, then let the workflow attach the APK:

```bash
gh release create v1.0.0 --generate-notes
```

Follow the build under the repository's **Actions** tab. When it finishes, `paisapeek-v1.0.0.apk` is on the release page.

To build a signed release APK locally instead, set the same variables (with `ANDROID_KEYSTORE` as the path to the `.jks` file) and run:

```bash
ANDROID_KEYSTORE=paisapeek-release.jks ANDROID_KEY_ALIAS=paisapeek ANDROID_KEYSTORE_PASSWORD=… ANDROID_KEY_PASSWORD=… \
  ./gradlew assembleRelease -PversionName=1.0.0 -PversionCode=10000
```
