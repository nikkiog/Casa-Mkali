# CM Secure Assistant — Standard Operating Procedure

## What is CM Secure Assistant?

CM Secure Assistant is Casa Mkali's internal Slack bot. It indexes all team conversations across Slack channels and emails sent to projects@casamkali.com, then helps the team quickly find information, get personalized digests, and review client status reports.

The bot is read-only — it never sends emails, deletes messages, or modifies anything. It only reads and responds.

---

## Getting Started

### For Team Members

The bot is already installed in the Casa Mkali Slack workspace. To use it:

1. The bot must be invited to any channel you want it to read. An admin types `/invite @mkali_ai_assistant` in the channel.
2. Once invited, the bot silently indexes all messages in that channel.
3. You can then ask it questions, request digests, or get client reports.

### For Admins

The bot runs on Railway (cloud hosting) and connects to Slack via Socket Mode. No public URLs or server management needed.

**Environment variables required on Railway:**
- `SLACK_BOT_TOKEN` — Bot User OAuth Token (xoxb-...)
- `SLACK_APP_TOKEN` — App-Level Token (xapp-...)
- `ANTHROPIC_API_KEY` — Claude API key
- `GMAIL_CREDENTIALS_B64` — Base64-encoded Google OAuth credentials
- `GMAIL_TOKEN_B64` — Base64-encoded Google OAuth token

**Slack app scopes required:**
- `channels:read`, `channels:history` — read public channels
- `groups:read`, `groups:history` — read private channels
- `im:read`, `im:history` — receive DMs
- `chat:write` — send responses
- `reactions:read`, `reactions:write` — feedback tracking
- `users:read` — resolve user names and profiles

**Event subscriptions required:**
- `app_mention` — respond to @mentions
- `message.channels` — index public channel messages
- `message.groups` — index private channel messages
- `message.im` — receive DMs
- `reaction_added` — track feedback

---

## How to Ask Questions

### @Mention in any channel

Type `@mkali_ai_assistant` followed by your question in any channel where the bot is a member. The bot replies in a thread to keep the channel clean.

**Examples:**
- `@mkali_ai_assistant what did we decide about the Thursday schedule?`
- `@mkali_ai_assistant has anyone mentioned the Roofing Source deadline?`
- `@mkali_ai_assistant what emails came in about the Monarch project?`

### /ask slash command

Type `/ask` followed by your question in any channel. The bot posts your question visibly and responds in a thread.

**Examples:**
- `/ask what's the latest on the Skoop deliverables?`
- `/ask who is handling the Ron Perkins content this week?`

### DM the bot

Send a direct message to the bot with your question. Useful for private queries.

**Examples:**
- "What did Sarah say about the client review?"
- "Are there any emails about the Focal project?"

---

## How to Get Your Personal Digest

The digest gives you a personalized summary of what happened in the last 24 hours across your channels, plus any emails that came in. It includes suggested responses you can copy and adapt.

### Trigger phrases (any of these work):

| Phrase | Where it works |
|--------|---------------|
| "update me" | @mention, DM |
| "what did i miss" | @mention, DM |
| "catch me up" | @mention, DM |
| "digest" | @mention, DM |
| "hi" / "hey" / "hello" | DM only |
| `/updateme` | Any channel (slash command) |

### What's in your digest:

- **Needs your attention:** Messages where you're @mentioned or a response is expected
- **Key updates:** Important discussions in your channels (3-5 bullets)
- **Team updates:** Status updates submitted by team members
- **Recent emails:** Relevant emails from projects@casamkali.com
- **Suggested responses:** Draft replies you can copy/paste or adapt

### Privacy:

Your digest only includes messages from channels YOU are a member of. You will never see another team member's digest content, and the bot will never reveal whether someone else responded to something.

---

## How to Get Client Status Reports

The bot can process weekly status report emails and generate structured summaries for each client.

### How to request:

| Trigger | How |
|---------|-----|
| `@mkali_ai_assistant client reports` | @mention |
| `@mkali_ai_assistant status reports` | @mention |
| `@mkali_ai_assistant weekly reports` | @mention |
| `/clientreports` | Slash command |

### What you get for each client:

- **Status:** Green/yellow/red with a one-sentence explanation
- **Key developments this week:** 2-3 bullets
- **Risks or blockers:** Anything flagged in the report
- **What was promised for next week:** Commitments made
- **In Progress items:** Flagged as requiring follow-up action
- **Suggested next actions:** Prioritized recommendations
- **Missed commitments:** If something promised last week wasn't mentioned this week

### Email format required:

For the bot to find and process reports, emails to projects@casamkali.com should have subject lines like:
- "Weekly Status Report - Roofing Source - April 03"
- "Weekly Status Report - Monarch Athletic Club - April 03"

Items listed under "In Progress" in the email body are flagged as needing additional action.

---

## How to Submit Updates

When the bot gives you a digest or answers a question, you can reply in the thread with an update. The bot saves it and includes it in future digests for the whole team.

### How it works:

1. Bot posts a response (digest, answer, or report) in a thread
2. You reply in that same thread with your update
3. Bot responds: "Got it, saved your update. This will be included in future digests."

### Good update examples:

- "Done — shipped the new schedule to the team"
- "FYI we moved the Focal meeting to Thursday"
- "Roofing Source signed off on the design, we're good to proceed"
- "Blocked — waiting on client approval before we can move forward"

---

## How to Give Feedback

After the bot answers a question, it adds thumbs up and thumbs down reactions to its own message.

- Click :thumbsup: if the answer was helpful
- Click :thumbsdown: if it wasn't useful or was wrong

This feedback helps track accuracy and identify knowledge gaps. Questions that get thumbs down are flagged for review.

---

## When to CC projects@casamkali.com

Include projects@casamkali.com on emails when you want the bot to have access to that information. Common use cases:

- **Weekly status reports** — forward or CC so the bot can process them via `/clientreports`
- **Client communications** — CC on important client emails so the team can search them later
- **Vendor updates** — forward notable vendor communications
- **Meeting summaries** — forward recap emails after external meetings

**Do NOT send to projects@casamkali.com:**
- Sensitive HR or personnel matters
- Personal emails
- Anything with passwords, credentials, or financial account details
- Confidential legal communications

The bot reads ALL emails in that inbox. Treat it as a shared team resource — anything you send there is searchable by the whole team.

---

## Security and Privacy

### What the bot CAN access:
- Messages in public and private Slack channels it's been invited to
- Emails in the projects@casamkali.com inbox
- Your Slack profile (name, title, status) for personalizing digests

### What the bot CANNOT access:
- Direct messages between team members (never)
- Your personal email
- Any Slack channel it hasn't been invited to
- Files, images, or attachments (text only)

### Privacy rules:
- Your digest only shows messages from YOUR channels
- The bot never reveals what's in another person's digest
- The bot never tells you if someone else did or didn't respond to something
- Your profile data is only used in your own prompts, never shared
- The bot never compares your activity to anyone else's

### Data storage:
- All data is stored in a database on Railway (cloud hosting)
- Channel messages, emails, questions, and feedback are indexed
- No data is shared outside the Casa Mkali workspace
- The bot uses Claude (Anthropic) to generate responses — message content is sent to the API for processing

### Bot permissions:
- **Read-only** for Slack channels and Gmail
- **Write** only to post responses in Slack
- Cannot delete, edit, or forward messages
- Cannot send emails
- Cannot access anything outside the Casa Mkali workspace

---

## Quick Reference

| Action | Command |
|--------|---------|
| Ask a question | `@mkali_ai_assistant <question>` or `/ask <question>` |
| Get your digest | `@mkali_ai_assistant catch me up` or `/updateme` |
| Get client reports | `@mkali_ai_assistant client reports` or `/clientreports` |
| Submit an update | Reply in a thread under a bot message |
| Give feedback | Click :thumbsup: or :thumbsdown: on bot's answer |

---

## Troubleshooting

**Bot isn't responding:**
- Make sure the bot is invited to the channel (`/invite @mkali_ai_assistant`)
- Check if the bot is online in Railway

**Bot doesn't know about a conversation:**
- The bot can only read channels it's been invited to
- Recent messages may take up to 5 minutes to be indexed

**Bot doesn't know about an email:**
- Make sure the email was sent to or forwarded to projects@casamkali.com
- Emails are polled every 60 seconds — wait a moment and try again

**Client reports show no results:**
- Email subject must contain "Weekly Status Report"
- The email must be in the projects@casamkali.com inbox

**Need help?**
Contact your workspace admin or ask in #casageneral.
