# School Bot - GitHub edition

Runs on GitHub for free. **No server, no PC that has to stay on.**
GitHub sends your Telegram messages on a schedule, and you control everything by editing one file.

**Sends automatically**
- Every **Monday**: study week (e.g. *Week 3 of 18 - Semester 1, Year 3*), this week's **projector team**, and this week's exams/holidays.
- On the **1st of each month**: that month's exams and holidays.
- Any time you press **Run workflow**: the weekly message, any month, or the class schedule.

**Your admin website = GitHub itself:** a private repository only you can open (protected by your password + 2-step login),
every change is saved in the history (who, when, what - that is your log), and you can undo any mistake.

> **What this edition cannot do:** answer button presses in Telegram (like "Choose a month") the moment someone taps.
> GitHub can't listen 24/7. Instead, use **Run workflow** to post a month or the schedule to the chat when people need it.
> For a bot with live buttons, use the Python version (needs a computer that stays on).

## Setup (about 15 minutes)

**1. GitHub account.** Sign up at github.com (free). Then Settings -> Password and authentication -> turn on two-factor authentication.

**2. Create the repository.** Click **+ -> New repository**. Name: `school-bot`. Choose **Private**. Click **Create**.

**3. Upload these files.** In the new repository click **uploading an existing file**. Unzip this project, then drag in **everything inside the folder**,
including the `.github` folder, `data` folder, `bot.py`, `requirements.txt`. Click **Commit changes**.
Open the **Actions** tab: you should see *Send message*, *Check data file* and *Find chat IDs*.
(If Actions shows nothing, the `.github` folder was not uploaded. Use **Add file -> Create new file**, type `.github/workflows/send.yml` as the name, and paste the file's text. Repeat for the other two.)

**4. Bot token.** In Telegram open **@BotFather** -> `/newbot` (or `/token` to get a new one for your bot). Copy the token.
In GitHub: **Settings -> Secrets and variables -> Actions -> New repository secret**. Name: `BOT_TOKEN`, Secret: your token. Save.
*Never put the token in a file or a chat.*

**5. Connect your group.** Add your bot to the Telegram group (or open the bot and press Start). Send `/start` in that chat.
In GitHub: **Actions -> Find chat IDs -> Run workflow**. Open the finished run and read the list. Copy the number for your group (groups start with `-`).

**6. Save the chat ID.** Add a second secret named `CHAT_IDS` with that number. Several chats? Separate with commas: `-1001234567,-1007654321`.

**7. Fill in your data.** Open `data/school.yml` -> pencil icon -> replace the example semester, teams, exams/holidays and schedule -> **Commit changes**.
Watch the **Actions** tab: **green tick = OK**, **red cross = typing mistake** (click it to see which line).

**8. Test.** **Actions -> Send message -> Run workflow**. Tick **Preview only** first and read the text in the log. Then run again with it unticked to really send.

Done. From now on it runs by itself.

## Everyday use
- Change data: edit `data/school.yml` on github.com -> Commit.
- Post a month: **Actions -> Send message -> Run workflow** -> what = `month`, month = `10` (or `2026-10`).
- Post the timetable: what = `schedule`.
- Projector team is automatic, one team per week in order. To change one week add a line under `overrides:`.
- More admins: Settings -> Collaborators.
- See who changed what: the **Commits** history.

## Change the times
Open `.github/workflows/send.yml`. The times are in **UTC**. `0 0 * * 1` = Monday 00:00 UTC = 07:00 in UTC+7.
Different country: change the hour (07:00 local minus your UTC offset).

## Good to know
- GitHub's timer is **not exact**: messages can arrive several minutes late, and rarely much later.
- Keep the repository **Private**. Private repos get free monthly minutes and this uses about 1 minute per message.
- This uses GitHub Actions only for a small weekly job. GitHub's rules say Actions is meant for building and testing code,
  so don't add frequent polling or heavy jobs - accounts that do can be restricted.
- If the bot was running somewhere else (your PC), stop it before step 5, or "Find chat IDs" will show a *Conflict* error.
