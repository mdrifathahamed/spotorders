# Phone setup

You do this once. After that, you only press buttons during shifts.

## 1. One-time GitHub setup (on a computer or the phone browser)

**a) Two repos.** `spotorders` (public) and `spotorders-data` (private).

**b) A fine-grained access token** for the app and the workflow:

1. github.com → profile picture → **Settings** → **Developer settings** → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
2. Name: `spotorders-phone`. Expiration: 1 year (set a reminder to renew it).
3. Repository access: **Only select repositories** → `spotorders` and `spotorders-data`.
4. Permissions → Repository permissions → **Contents: Read and write**. Leave everything else as is.
5. Generate and copy the token (it starts with `github_pat_`). GitHub shows it only once.

**c) Give the workflow the token.** In the `spotorders` repo: **Settings** → **Secrets and variables** →
**Actions** → **New repository secret**. Name: `DATA_REPO_TOKEN`, value: the token. Save.

## 2. Install the app

1. On your Android phone, open
   **https://github.com/mdrifathahamed/spotorders/releases/latest/download/Spotorders.apk**
   (or the repo's **Releases** page → latest → `Spotorders.apk`).
2. When Android asks, allow your browser to **install unknown apps** (Settings → Apps → Chrome →
   Install unknown apps → Allow). Android shows this because the app is not from the Play Store.
3. Open the APK and tap **Install**. If Play Protect warns about an unknown developer, choose
   **More details → Install anyway**. It's your own app, built from this repo by GitHub Actions.

Updates: install the newest `Spotorders.apk` the same way. It installs over the old version and keeps your data.

## 3. First start

1. Open **Spotorders**, allow **location** (choose *While using the app*, *Precise*) and **notifications**.
2. Open **GitHub settings**: username `mdrifathahamed`, private repo `spotorders-data`,
   public repo `spotorders`, paste the token. **Save**.
3. Battery: Settings → Apps → Spotorders → Battery → **Unrestricted**. Otherwise some phones stop GPS
   logging when the screen is off.

## 4. During a shift

| When | Press |
|---|---|
| You go online in the Wolt Partner app | **Start shift** (in Spotorders) |
| You accept an order | **Got order** (in the notification) |
| You hand over the food and are free again | **Free again** (in the notification) |
| You go offline | **End shift** (in Spotorders) |

Pull down the notification shade to see the buttons. Press them when you have stopped, never while riding.
Forgot one? No problem: the pipeline skips waits it can't measure.

## 5. Check that it works

- The app shows **"All uploaded"**, or the number of presses waiting for internet.
- In `spotorders-data` on GitHub, `live/events.csv` gets a new line for each press.
- In `spotorders` → **Actions**, an *Update dataset* run starts within about a minute of each order,
  and `data/sample/` and `figures/` update.

## Troubleshooting

| Message in the app | Fix |
|---|---|
| `HTTP 401` | Token wrong or expired: make a new one, paste it in the app and in `DATA_REPO_TOKEN` |
| `HTTP 403` / `404` | The token doesn't include `spotorders-data`, or Contents isn't set to Read and write |
| *Update dataset* run fails at checkout | The `DATA_REPO_TOKEN` secret is missing in the `spotorders` repo |
| GPS stops when the screen is off | Set battery to *Unrestricted* (step 3.3) |
