# HireModus

The Novamodus hiring app.

Everything is a setting you can change on screen: departments and their CC lists, pipeline stages, email wording, interviewers, interview rules (length, days, hours, how far out to search, the ERP-EPM "two required plus a rotating trio" rule), training modules, holidays and users. It also adds a locked-down test portal for candidates.

## What's in the box

| Folder | What it is |
|---|---|
| `backend/` | The server (Python, FastAPI). One database holds every candidate, so every recruiter sees the same pipeline. |
| `frontend/` | The web app staff and candidates use. `frontend/dist` is already built. |
| `connector/` | The HireModus Outlook Connector. Each recruiter runs it on their own PC so emails and invites go out from their own desktop Outlook. |

## Try it on your PC (5 minutes)

1. Install Python 3 for Windows from python.org (tick "Add python.exe to PATH").
2. Double-click `start_hiremodus_windows.bat`. It installs what it needs the first time and opens http://localhost:8000.
3. Sign in as `admin@novamodus.com` / `ChangeMe123!` and set your own password.
4. Go to **Import from Excel** and upload the tracker workbook. Every sheet is mapped automatically (Master, AI Sent, No AI, department sheets, Hired, Rejected, Withdrawn, Module Selection). Rows with a Round 1 or Round 2 date and an Outlook interview ID become real interview records you can reschedule.

The app starts with **Outlook simulation on**: emails and invites are recorded in the Outbox but not sent, and calendar availability is invented. That lets you click through everything safely. Turn it off in **Settings > General** once people have the connector running.

Workbooks with a Microsoft sensitivity label are encrypted and can't be read. Save a copy with the label set to General/Public first.

## Where HireModus runs

HireModus is one server that everyone connects to with a browser: staff and candidates. Pick one of these:

**Option A: an always-on office PC (office network only).** Run `start_hiremodus_windows.bat` on a PC that stays on. Everyone on the office network or VPN opens `http://<that PC's name>:8000`. Candidates taking the test in the office connect their laptop to the office Wi-Fi and open `http://<that PC's name>:8000/portal`. This is free and quick, but it only works inside the office network, and stops when that PC is off.

**Option B: a web host (works from anywhere).** Run the Docker container on Azure App Service, an Azure VM or any Linux server, behind a company address such as `https://hire.novamodus.com`. Recruiters can use it from home, and candidates can reach the portal on any network. This is the setup to use long term. See "Putting it on the web" below.

Either way, set **Settings > General > Test portal address** to the address candidates will actually use. It's the link printed in their test login email.

The candidate test portal and the staff app are the same server, so no separate hosting is needed for the test.

## How the pieces fit

```
 Recruiter's browser ──► HireModus server (one shared database) ◄── Candidate's browser (/portal)
                                ▲
                                │ "send this email / book this invite / check these calendars"
                                ▼
                 HireModus Outlook Connector on the recruiter's PC ──► their desktop Outlook
```

- Clicking **Send** or **Send invite** creates an item in that person's Outbox.
- Their connector picks it up within a few seconds and does it through Outlook: real Sent Items, real calendar invites, real free/busy checks.
- If the PC is off, items wait in the Outbox and go out when the connector is back.
- Reschedules update the original Outlook invite. Only the person who booked an invite can move it.

Each recruiter sets this up once from **My Outlook**: download the connector (the zip already holds their personal key), unzip, double-click `start_connector.bat`.

## The candidate test

1. An interview type marked **Includes a test** creates a username and password for the candidate. They go into the invite through the `{{test_block}}` placeholder. You can also assign a standalone test from the candidate page.
2. On the day, the candidate signs in at `/portal`. They see only the test portal; it has no links into the staff app, and their login can only reach test endpoints.
3. The recruiter running the interview clicks **Give start code** (candidate page or Tests page) and reads out the 6-digit code. It works once and expires after 30 minutes by default.
4. Entering the code starts the timer and puts the page in full screen. Leaving full screen, switching tabs or windows, copy, paste, cut, right-click, print and developer-tool keys are blocked where a browser allows it, and always logged.
5. Answers save as the candidate types. When time runs out the test submits itself, on the server too, even if the browser was closed.
6. Multiple choice is marked automatically. Written answers and Dev file uploads are graded on the results page, next to an integrity log of every warning.

If a candidate's browser crashes mid-test, give them a new start code. The test reopens and the timer keeps its original deadline.

A browser page can't fully stop someone using a second device or a screen-capture tool. HireModus makes it hard, records everything it can see and flags what looks wrong, but nothing it flags is proof on its own.

### Screen sharing rules

- The test only runs in **Google Chrome or Microsoft Edge** on a computer. Other browsers can't confirm what's being shared, so they get a message asking them to switch.
- The candidate must share their **Entire screen**. Sharing a tab or a window is refused, and so is a share where the browser doesn't say what was shared. The same check runs if they have to turn sharing back on mid-test.
- **One monitor.** If a second monitor is connected, screen sharing won't start. If one is plugged in during the test, the test is covered until it's removed, and the integrity log records it.

### Phone and distraction checks

During tests that record the camera, the candidate's browser checks the camera about once a second for:

- a **phone** the camera can see
- **nobody** in front of the camera (5 seconds by default)
- **more than one person** in view
- **looking away** from the screen, including looking down towards a lap or desk (5 seconds by default)

Each check only flags. The candidate sees a short warning, the integrity log gets an entry, and a camera snapshot is saved for the panel (deleted at midnight with the recordings). The results page shows the snapshots with a "Watch this moment" button. Turn the checks on or off, change the timings, or hide the warning from candidates in Settings > Test integrity. The check models are served by HireModus itself, so nothing about the candidate's camera leaves for any other service.

## Recording the test

Each test can record the candidate's entire screen, camera and microphone (Tests > Edit > "Record the candidate"; all three are on by default).

- Before starting, the candidate sees what will be recorded and that it's deleted at midnight. They tick a consent box and allow the camera and screen sharing. The test won't start unless they share the entire screen.
- While the test runs, a small camera preview with a red "Recording" badge stays on screen. Video uploads every 10 seconds, so nothing is lost if the browser closes.
- If the camera or screen sharing stops, the test is covered with a "Recording stopped" screen until they turn it back on. The timer keeps running, and the integrity log records the gap.
- On the results page the panel can play the screen and camera side by side. Each warning in the integrity log has a "Watch this moment" button that jumps both videos to it. You can also watch a test that's still in progress, up to the last 10 seconds.
- Recordings are deleted automatically at midnight (office time) on the day of the test. If the server is off at midnight, they're deleted within a minute of it starting again.
- **Quality** is set in Settings > Test integrity: High (Full HD at 10 frames a second, the default), Standard (720p) or Low (for slow connections). At High, a 45-minute test can use up to about 1 GB, mostly screen; still images like a test page usually use far less. None of it is kept past that midnight.

## Setting up the test laptop

Use a Novamodus laptop for tests instead of the candidate's own. IT can set it up in about an hour:

1. **Separate Windows account** (for example "HireModus Test") with no access to email, files or other company systems.
2. **Kiosk browser**: make that account's only shortcut `msedge.exe --kiosk http://<server>:8000/portal --edge-kiosk-type=fullscreen`, or use Windows Assigned Access with Microsoft Edge. The candidate can then only use the test portal.
3. **Allow camera and microphone without prompts** for the HireModus address through Edge or Chrome policy (`VideoCaptureAllowedUrls` and `AudioCaptureAllowedUrls`). The candidate still chooses "Entire screen" once when the test starts.
4. **Block other websites** for that account with the `URLBlocklist` policy set to `*`, and `URLAllowlist` set to the HireModus address.
5. **One screen only.** Unplug any external monitor. HireModus refuses to start screen sharing while a second monitor is connected.
6. **Phones** stay at reception during the test.

Try a full test once on the laptop after setup, to confirm the screen-share prompt works in kiosk mode on your Edge version.

## Roles and access

Each user can hold several roles. Settings > Roles lets an admin tick exactly what each role can do, and every change to a role or to a user's roles is written to the audit log (Settings > Audit log).

- **Admin**: every department, settings, users, roles and the audit log, but not question papers or answers (they still see test scores and recordings).
- **Admin + Recruiter**: everything.
- **Recruiter**: works only in their own departments, which are the ones ticked on their user plus any department whose CC list contains their email. In those departments they handle candidates, emails, interviews, test papers and results, hiring, rejections and withdrawals. They can't delete candidates or change settings.
- **Associate**: adds candidates, works them through the AI interview stages and Screening (AI interview invites, rejections, withdrawals), and hands them over to a department. After the hand-off, that department's recruiters take over.
- **Candidates** only ever see their own test on the portal.

Everyone can see where every candidate is (stage and department) on the Candidates list, with **My departments / Everyone** at the top; it opens on My departments. Candidates in other departments are read-only: name, stage, department, days since contact and next interview, but no contact details, emails or tests.

### Moving a candidate to another department

A recruiter can move candidates freely within their own departments. To send one to a department they don't work in, they use **Transfer** (or Move and pick that department) and must add a note saying why. The receiving department's recruiters get an alert, and the request shows on the candidate's page and their dashboard.

- **Accept**: the candidate moves to that department.
- **Decline**: the candidate is moved to Rejected and, after you confirm, the rejection email goes out. The person who asked is told either way.
- The person who asked can cancel the request while it's waiting.

Associates handing over a new candidate don't need a transfer: picking the department hands them over and tells that department.

Tests belong to one or more departments too. Recruiters see only their departments' tests, questions and results.

Changing a candidate's Date added needs the "Change a candidate's Date added" permission, which only Admin has by default.

## Aging rules (30-day alert, 45-day automatic rejection)

HireModus counts the days since each candidate was last contacted in the stages that count. By default those are AI Interview Pending, AI Interview Sent, Screening and Department Review.

- The clock restarts at day 1 whenever HireModus sends the candidate an email or invite, or someone clicks **Mark as contacted** on their page.
- A booked interview in the future pauses the clock. After the interview date passes, it counts again from the interview day.
- **Day 30:** the candidate is highlighted in amber and appears in the alert. Every morning at the set time, the alert email goes from Anitha's Outlook to Anitha, one email per area. Each email CCs that department's recruiters (the emails on the department in Settings > Departments) and whoever last contacted the candidate. The same alert appears in the bell at the top of the app.
- **Day 45:** the candidate is moved to Rejected, and the rejection email goes out from Anitha's Outlook with the usual department CCs.
- **Keep (don't auto-reject)** on a candidate's page excludes them.
- **Imported candidates** start from the latest date in the spreadsheet: Date Added, Preliminary Interview or Second Round. Anyone imported already past day 45 gets 7 days' grace before being rejected, so they appear in an alert first.
- **Everything is a setting** in Settings > Aging rules: the day limits (also per stage), recipients, sender, time of day, CCs, grace period, daily or new-only alerts, and whether a stage move also restarts the clock.
- The Candidates list has a "Days since contact" column and a filter for over 30 days or due for rejection. The dashboard shows the counts and a chart by area.

## Making HireModus your own

- **Dashboard**: each user picks and orders their own number tiles (Customize).
- **Candidates list**: switch between list and board (drag a card to another stage), choose and order columns, and save filters as named views.
- **Custom fields**: Settings > Custom fields adds your own candidate fields (text, number, date, dropdown, yes/no). They appear on the candidate page and can be list columns.
- **Branding**: Settings > Branding sets the app name, line under the logo, colours, or an uploaded logo. It's used on the sign-in page, sidebar and candidate portal.
- **Notifications**: Settings > Notifications chooses who is told when a test is submitted or candidates are rejected automatically.
- **Tests**: question pools (each candidate gets a random subset of choice and written questions) and shuffled answer options, per test. Questions can have a section (for example Aptitude) and pictures, on the question and on each answer option.

## Test papers from Excel

Tests > **Download Excel template** gives a ready-to-fill workbook with sample questions of every kind, including an aptitude question with pictures.

- **Test details** sheet: name, department(s), time limit, instructions, shuffle options and pool sizes.
- **Questions** sheet, one row per question: Section, Type (Single choice, Multiple choice, Short answer, Long answer, File upload), the question, options A to F, the correct letter(s) such as `B` or `A, C`, and points.
- **Pictures**: copy a picture and paste it onto the picture cell of that row (its top-left corner inside the cell). Excel's "Place in Cell" works too. An option can be text, a picture or both.

Tests > **Upload test paper** reads the file and shows a preview with any problems listed by row before saving anything. Then choose: create a new test, add the questions to an existing test, or replace an existing test's questions. Results already taken are never changed.

## Candidate replies

Every 5 minutes, each recruiter's and CC person's Outlook connector (or Microsoft 365 mailbox, see below) is checked for emails from candidates they work with. Only emails from an address on a candidate's record are copied into HireModus; nothing else in the mailbox is read or stored. The first check looks back 30 days (Settings > Email and Microsoft 365).

- The candidate's **Emails and invites** card shows a preview of each reply with **View reply** (full text and attachments up to 15 MB) and **Reply**.
- A reply stored in several inboxes is kept once. It alerts the department, shows as New per person (Candidates list, dashboard), and restarts the aging clock from when the candidate wrote. Replies older than a day found by the first look-back are stored without alerts.
- **Replying from HireModus** sends from your own mailbox. If the candidate's email is in your inbox it goes out as a real reply in the same thread; otherwise it goes out as a new "RE:" email with their message quoted. You can CC the department and start from an email template.

## Department dashboards

The dashboard has a department picker (All my departments, then each department you work in). Every tile and list follows it: stage counts, aging, interviews, tests, transfers and new replies. The choice is remembered on that browser.

## Interview feedback (optional)

After an interview has started, anyone who works in the candidate's department can fill in a short feedback form on the interview: by default an overall rating from 1 to 5, a recommendation (Hire, Maybe, No hire), strengths, concerns and notes. Each person has one entry per interview and can edit it. It's never required to move a candidate on. People outside the department only see that feedback exists. Edit the questions in Settings > Interview feedback.

## Clearing out old candidate data

Off until an admin turns it on in Settings > Clearing old data. When on, Rejected and Withdrawn candidates have their personal details removed 12 months (changeable) after they reached that stage: name, contact details, notes, custom fields, emails and replies with attachments, test answers and files, interview feedback, and the addresses in their invites. Department, stage, dates, position and source stay, so counts keep working; the candidate shows as "Removed candidate #123".

- Admins get an alert 14 days (changeable) before each batch, and the settings page lists who's coming up in the next 60 days.
- Tick **Keep details** on a candidate (or in that list) to exclude them.
- Every clear-out is in the audit log. It can't be undone.
- Imported candidates count from the date they were imported, because the spreadsheet doesn't say when they were rejected.

## Microsoft 365 (Entra ID sign-in and Graph email)

Off until an admin fills in Settings > Email and Microsoft 365. It runs alongside the Outlook connector: each person's mail goes through **Microsoft 365** or their **Outlook connector**. Admins set the company default and can change it per person; each person can also choose on the My Outlook page. Microsoft 365 works with the new Outlook and keeps working when the person's PC is off.

**What IT sets up in Microsoft Entra ID**

1. **App registration**: Entra admin center > App registrations > New registration. Name it HireModus, single tenant.
2. **Redirect URI**: Authentication > Add a platform > Web, and paste the redirect address shown on the HireModus settings page (it ends in `/api/auth/microsoft/callback`). Microsoft only accepts `https://` addresses, or `http://localhost` for the PC running HireModus.
3. **Client secret**: Certificates & secrets > New client secret. Paste the secret **value** into HireModus with the Directory (tenant) ID and Application (client) ID from the Overview page. Note the expiry date; when it expires, create a new one and paste it in.
4. **API permissions** (Microsoft Graph), then **Grant admin consent**:
   - Delegated: `User.Read` (sign-in)
   - Application: `Mail.Send`, `Mail.Read`, `Calendars.ReadWrite` (sending, candidate replies, invites and free/busy)
5. **Limit the mailboxes**: application permissions cover every mailbox until limited. Put the recruiters and department CC people in a mail-enabled security group and restrict the app to it with an Exchange Online application access policy (`New-ApplicationAccessPolicy -AccessRight RestrictAccess -AppId <client id> -PolicyScopeGroupId <group>`) or RBAC for Applications.
6. **Network**: the HireModus server needs outbound HTTPS to `login.microsoftonline.com` and `graph.microsoft.com`.

Then in HireModus: save the details, use **Test connection**, and switch on **Sign in with Microsoft** and/or **Email and invites through Microsoft 365**.

**How sign-in works**: only people already added in Settings > Users get in, matched by email the first time and by their Microsoft account ID after that. Roles and departments still come from HireModus. You can keep password sign-in for everyone or only for admins (as a backup). Refused attempts are in the audit log.

**Things to know**: a meeting booked through the connector has to be rescheduled or cancelled through the connector, and the same for Microsoft 365. A Microsoft 365 send that fails stays in the Outbox with the reason and is never retried by itself, so nothing goes out twice.

## Putting it on the web

Candidates must reach `/portal` from outside, so production needs a public HTTPS address.

```
docker compose up -d --build
```

Before going live, edit `docker-compose.yml`:

- `HIREMODUS_SECRET_KEY`: a long random string. Sessions are signed with it.
- `HIREMODUS_PORTAL_URL`: the public address of `/portal`. It's printed in test emails, and you can also change it in Settings.
- `HIREMODUS_ADMIN_PASSWORD`: used only for the very first start.

The default database is SQLite in the `/data` volume, which is fine for one company. For Azure Database for PostgreSQL, set `HIREMODUS_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/hiremodus`. On Azure App Service (Linux container), mount persistent storage at `/data` and put it behind the App Service's HTTPS address.

## Placeholders for email and invite text

`{{first_name}} {{last_name}} {{full_name}} {{company}} {{department}} {{interview_date}} {{interview_time}} {{location}} {{round}} {{module}} {{module_web_link}} {{module_training_link}} {{instance_link}} {{ai_interview_link}} {{resume_line}} {{sender_name}} {{due_date}} {{test_block}}`

Settings shows the full list with descriptions.

## Running the tests

```
cd backend
pip install -r requirements.txt pytest httpx
HM_WORKBOOK=path/to/tracker.xlsm python -m pytest tests -q
```
