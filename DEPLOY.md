# Put the Parlay app on your phone (free, private, about 20 minutes)

You will end up with a web app that only opens with your password. It builds parlays, shows the tracker, grades slips and
logs your own bets. It runs on **Streamlit Community Cloud** (free). Your ledger is saved in a **private GitHub repository**
(free), because the free server forgets files when it restarts. A small daily job on GitHub grades the slips at 9 AM Eastern.

You need: an email address, the Odds API key you already use, and a password you choose for the app.
Nothing here costs money. Never paste your keys or tokens anywhere except the places named below.

---

## Step 1 - Create a GitHub account (skip if you have one)
1. Go to https://github.com/signup and follow the steps (email, password, username). Verify your email.

## Step 2 - Create a PRIVATE repository
1. Signed in to GitHub, open https://github.com/new
2. **Repository name:** `parlays` (any name works; remember it).
3. Choose **Private**. Do NOT tick "Add a README" (the folder already has one).
4. Click **Create repository**. Your repo name is now `YOUR-USERNAME/parlays`; this is your **GH_REPO** value.

## Step 3 - Put the app code in the repository
The ready-to-upload folder is `parlays_app_repo` (it already contains your ledger history and no secrets).
- **Easiest:** ask Grok Bot to push it for you ("push /workspace/parlays_app_repo to YOUR-USERNAME/parlays"). It will ask you to
  connect GitHub once.
- **Or by hand with GitHub Desktop** (https://desktop.github.com): File -> Add local repository -> choose the `parlays_app_repo`
  folder -> Publish repository -> keep "Keep this code private" ticked -> pick your `parlays` repo name.
- **Or in the browser:** on your new repo page click "uploading an existing file" and drag in *everything inside* the folder.
  The folders `.streamlit` and `.github` are hidden on a Mac (press Cmd+Shift+. in Finder to show them) and must be uploaded too.
  Click **Commit changes**.

Check: on GitHub you should see `app`, `ledger`, `parlay_builder.py`, `requirements.txt`, `.streamlit`, `.github`.

## Step 4 - Make a GitHub token so the app can save your data (GITHUB_TOKEN)
1. Open https://github.com/settings/personal-access-tokens/new (GitHub -> your photo -> Settings -> Developer settings ->
   Personal access tokens -> Fine-grained tokens -> Generate new token).
2. **Token name:** `parlay app`. **Expiration:** the longest offered (put a reminder in your calendar to renew it).
3. **Repository access:** "Only select repositories" -> choose `parlays`.
4. **Permissions -> Repository permissions -> Contents:** set to **Read and write** (Metadata: Read-only is added automatically).
5. Click **Generate token** and copy it (starts with `github_pat_`). This is your **GITHUB_TOKEN**. You will not see it again;
   if you lose it, just make a new one.

## Step 5 - Let the daily grading job save results
1. In your repo: **Settings -> Actions -> General**.
2. Under "Actions permissions" keep **Allow all actions**. Under "Workflow permissions" choose **Read and write permissions**. Save.
3. Optional test: **Actions** tab -> "Grade slips daily" -> **Run workflow**. After a minute it shows a green tick, and a branch named
   `ledger-data` appears (that branch is where your ledger lives from now on).
The job runs every day at 13:00 UTC = 9:00 AM Eastern in summer time (8:00 AM in winter). It uses no Odds API credits.

## Step 6 - Create a Streamlit Community Cloud account and deploy
1. Go to https://share.streamlit.io and click **Continue with GitHub**. Approve the access it asks for, including **private
   repositories** (otherwise it cannot see `parlays`).
2. Click **Create app** -> "Deploy a public app from GitHub" (the password still protects it; see the privacy note below).
3. Fill in: **Repository** `YOUR-USERNAME/parlays`, **Branch** `main`, **Main file path** `app/streamlit_app.py`.
   Optionally pick an **App URL** such as `yourname-parlays`.
4. Click **Advanced settings**: Python version **3.12**. In **Secrets** paste this, with your real values between the quotes:
   ```
   APP_PASSWORD = "a long password only you know"
   ODDS_API_KEY = "your Odds API key"
   GITHUB_TOKEN = "github_pat_... from step 4"
   GH_REPO = "YOUR-USERNAME/parlays"
   ```
5. Click **Save**, then **Deploy**. The first start takes 2-4 minutes. You then see a password box: type your APP_PASSWORD.

To change a secret later: share.streamlit.io -> your app -> the three dots -> **Settings -> Secrets**.

## Step 7 - Add it to your home screen
- **iPhone (Safari):** open your app link, log in, tap the **Share** button (square with arrow) -> **Add to Home Screen** -> Add.
- **Android (Chrome):** open the link, tap the **three dots** menu -> **Add to Home screen** (or **Install app**) -> Add.
You'll be asked for the password again each time the app restarts or you open a fresh session.

---

## Using the app
- **Build:** pick sports, tap **Build parlays**. The top shows how many Odds API credits are left and what a fresh run can cost
  (about 25 on a normal day; 0 if you built in the last 15 minutes because the odds are cached). Each slip card shows the legs, the
  book, and a price-shop row: the green 🏆 chip is the book that pays the most for the same legs. "Show flagged slips" adds the red,
  risky slips (off by default). "Last snapshot" re-shows the last data for free.
- **Tracker:** records by strategy, book, odds target, sport and list; red = flagged slips, blue = your own bets; closing-line value.
  **Grade now** settles finished games immediately (the daily job does it anyway).
- **Log my bet:** won/lost/push, book, sport, odds (like +250), net $ (+ won, - lost), date.

## Good to know
- **Credits:** the free Odds API plan has 500 credits a month, about 20 fresh builds. Building again within 15 minutes is free.
  To lower the per-build cap, add a secret `ODDS_MAX_CREDITS_PER_RUN = "30"`.
- **Sleeping app:** free Streamlit apps go to sleep when nobody opens them for a while; tap "Yes, get this app back up" and wait a minute.
- **Privacy:** only someone with your password can use the app. Your data sits in your private repo. If Streamlit offers sharing
  settings (app -> Settings -> Sharing), you can additionally limit viewers to your own email; that adds a Streamlit sign-in step on
  the phone.
- **Where your data is:** the `ledger-data` branch of your repo (`ledger/slips.jsonl`, `ledger/user_results.jsonl`,
  `ledger/grades.json`, `ledger/page_contents.tsx.txt`). Saving data there never restarts the app.
- **Using the chat assistant as well:** the assistant's copy of the ledger and the app's copy are separate. Pick one as the place
  you build and log, or ask the assistant to pull the `ledger-data` branch first.
- **Problems?** "This app is locked" = APP_PASSWORD secret missing. "GitHub save failed" = token expired or lacks Contents
  read/write on this repo (make a new one, update the GITHUB_TOKEN secret). "Credits left: -" = ODDS_API_KEY missing or wrong.
