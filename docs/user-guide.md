# InternTrack desktop tester guide

## Install and start

Use the candidate installer provided for your test session. The current release candidate is unsigned; a signed public download is still pending. If Windows blocks an installer, report the exact message to the maintainer rather than changing Windows security settings.

Launch InternTrack and create a local account. This account and its password hash live on this computer. It is not a cloud login, and a local account does not provide cloud password recovery.

### If the workspace will not open

The startup screen waits up to a minute for the local service and database. If it cannot open, the screen explains the problem and shows an error code. Use **Retry startup** to restart InternTrack, or **Quit InternTrack** to stop the desktop app and its local service. Retrying does not delete your account or records.

For `port-unavailable`, close another copy of InternTrack or the application using local port 8765, then retry. For `service-stopped` or `startup-timeout`, retry once; if it happens again, include the code when reporting the issue. A startup failure opens a visible window even when InternTrack was launched in the background at sign-in. If the buttons cannot respond, choose **Quit** from the tray menu and reopen the app.

## Track your first application

1. Select **Add application**.
2. Enter a company, role, status, and application date.
3. Optionally set a deadline, next-step text and date, source link, location, and notes.
4. Save, then use the search, status filter, and sort controls to find the record.
5. Select **Edit** as the application progresses.

Dates are calendar dates; a next-step date needs accompanying next-step text.

## Reminders and background behavior

Open **Account settings → Local reminders**, enable notifications, and choose the deadline window. Notifications require Windows permission and InternTrack to be running. Closing the window leaves it in the system tray; choose **Quit** from the tray menu to stop it. **Start with Windows** is optional.

## Export and protect your data

- **Export CSV** produces a spreadsheet copy of your records.
- **Export calendar** downloads a one-time .ics snapshot of dated deadlines and actions. Later edits do not automatically update another calendar.
- **Account settings → Portable backup** downloads a JSON backup for moving records and reminder preferences. It excludes passwords, sessions, API keys, and email connections. Keep the file private.
- Preview a backup before restoring. Merge skips duplicates; Replace asks for explicit confirmation before replacing the current account's records.
- **Automatic recovery** restores a whole local database snapshot at the next restart and requires password confirmation. It affects all local accounts in that workspace; keep the session secret and database together.

Desktop data lives in the application's per-user Windows local app-data directory. Upgrading the app should preserve that data; make a portable backup before testing an upgrade.

## Optional integrations

AI import uses your own OpenAI API key. The key is encrypted for your Windows user. Text you choose to import is sent to the provider, and you review the draft before saving.

Gmail and Outlook connections are optional and require the configured tester OAuth application. Review suggestions before applying them. The tracker works without either connection.

## Report a problem

Open **Account settings → About & support**, note the version, and optionally download diagnostics. Use **Report an issue** to describe the steps, expected result, and actual result. Review screenshots and attachments for private information before sharing them.

