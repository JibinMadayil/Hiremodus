HireModus Outlook Connector
===========================

This small program lets HireModus send email and meeting invites from YOUR desktop Outlook,
read free/busy for interviewers, and pick up candidates' replies.

Every 5 minutes it looks through your Inbox for emails sent by candidates you work with, and passes only
those to HireModus (with their attachments, up to 15 MB each). Nothing else in your mailbox is read or sent.
The first time, it looks back 30 days. Replies you send from HireModus go out from this Outlook, in the same
thread when the candidate's email is in your Inbox.

1. Keep this folder somewhere permanent (for example Documents\HireModusConnector).
2. Install Python 3 for Windows from python.org if you don't have it. Tick "Add python.exe to PATH".
3. Make sure Outlook is open.
4. Double-click start_connector.bat. Leave the window open.

To start it with Windows: press Win+R, type shell:startup, and put a shortcut to start_connector.bat there.

config.json holds your personal connector key. Don't share it. If it leaks, click "New key" on the
My Outlook page in HireModus and download the connector again.

connector.log in this folder records what was sent, which helps if something goes wrong.
