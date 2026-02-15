# Google Docs Integration Setup

This guide walks through setting up Google Docs as a content review hub for Wiz.
When enabled, blog drafts and social post companions are created as Google Docs
(with image generation prompts appended) instead of saving to local files.

**Time:** ~10 minutes for first-time setup, then fully headless.

---

## Prerequisites

- A Google account (Gmail or Workspace)
- A Google Cloud project (free tier is fine — Docs/Drive APIs have generous quotas)
- Python environment with Wiz installed (`pip3 install -e ".[dev]"`)

---

## Step 1: Create or Select a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. If you already have a project, select it from the dropdown at the top
3. If not, click **Select a project** > **New Project**:
   - Name: anything (e.g., "Wiz" or "Personal Tools")
   - Click **Create**
4. Note your **Project ID** (visible on the dashboard, e.g., `my-project-12345`)

## Step 2: Enable APIs

Enable both **Google Docs API** and **Google Drive API**:

**Option A — Direct links** (replace `PROJECT_ID`):
- `https://console.cloud.google.com/apis/library/docs.googleapis.com?project=PROJECT_ID`
- `https://console.cloud.google.com/apis/library/drive.googleapis.com?project=PROJECT_ID`

Click **Enable** on each page.

**Option B — Manual navigation:**
1. In Cloud Console, go to **APIs & Services** > **Library**
2. Search for "Google Docs API", click it, click **Enable**
3. Search for "Google Drive API", click it, click **Enable**

**Verification:** Both should show Status: **Enabled** on their detail pages.

## Step 3: Configure OAuth Consent Screen

Google requires a consent screen before you can create OAuth credentials.

1. Go to **APIs & Services** > **OAuth consent screen**
   (or: Google Auth Platform > Audience)
2. If prompted for user type, select **External** (unless you have a Workspace org)
3. Fill in required fields:
   - **App name:** Wiz (or anything)
   - **User support email:** your email
   - **Developer contact email:** your email
4. Click **Save and Continue** through the remaining steps (Scopes, Test Users, Summary)
5. The app will be in **Testing** mode

### Add Yourself as a Test User

While in Testing mode, only listed test users can authorize. **This step is critical.**

1. Go to **Google Auth Platform** > **Audience** (or OAuth consent screen > Test users)
2. Under **Test users**, click **+ Add users**
3. Enter your Google email address (the one you'll authorize with)
4. Click **Save**

> **Troubleshooting:** If you see "Ineligible accounts not added" but your email
> still appears in the test users table below, it usually still works. The warning
> can be misleading. If auth still fails with 403, try clicking **Publish app**
> on the Audience page to remove the test-user restriction entirely (safe for
> personal-use apps — it just means any Google account could authorize, but only
> you have the credentials file).

## Step 4: Create OAuth Desktop Credentials

1. Go to **APIs & Services** > **Credentials**
   (`https://console.cloud.google.com/apis/credentials?project=PROJECT_ID`)
2. Click **+ Create credentials** > **OAuth client ID**
3. Application type: **Desktop app**
4. Name: **Wiz** (or anything)
5. Click **Create**
6. A dialog appears with your Client ID and Client Secret
7. Click **Download JSON** to download the credentials file
8. **Important:** You won't be able to download this again after closing the dialog.
   (You can always create a new client if you lose it.)

## Step 5: Install the Credentials File

Move the downloaded JSON to `~/.wiz/google-credentials.json`:

```bash
mkdir -p ~/.wiz
cp ~/Downloads/client_secret_*.json ~/.wiz/google-credentials.json
```

The file should look like:
```json
{
  "installed": {
    "client_id": "XXXX.apps.googleusercontent.com",
    "project_id": "your-project",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_secret": "GOCSPX-...",
    ...
  }
}
```

The key thing is the top-level `"installed"` key — this identifies it as a Desktop
app credential. Web app credentials have `"web"` instead and won't work.

## Step 6: Authorize (One-Time Browser Flow)

```bash
wiz google-auth
```

This will:
1. Open your default browser to Google's consent page
2. Ask you to sign in and grant Wiz access to create/edit Docs and Drive files
3. Redirect to `localhost` to capture the auth code
4. Save the refresh token to `~/.wiz/google-token.json`

You should see:
```
Google Docs authorization successful.
```

**After this, all subsequent runs are headless.** The refresh token is used
automatically. It only expires if you revoke access or don't use it for 6 months.

### Common Auth Errors

| Error | Cause | Fix |
|-------|-------|-----|
| **403 Access denied** | Email not in test users list | Add your email in Step 3, or Publish the app |
| **redirect_uri_mismatch** | Wrong credential type (Web vs Desktop) | Create a new Desktop app credential (Step 4) |
| **Credentials file not found** | Wrong path | Verify `~/.wiz/google-credentials.json` exists |
| **invalid_grant** | Token expired/revoked | Delete `~/.wiz/google-token.json` and re-run `wiz google-auth` |

## Step 7: Enable in Config

Edit `config/wiz.yaml`:

```yaml
google_docs:
  enabled: true
  credentials_file: "~/.wiz/google-credentials.json"
  token_file: "~/.wiz/google-token.json"
  folder_id: ""  # Optional: Google Drive folder ID
```

### Optional: Set a Drive Folder

To have all docs created in a specific Google Drive folder:

1. Create a folder in Google Drive (or use an existing one)
2. Open the folder — the URL will be `https://drive.google.com/drive/folders/FOLDER_ID`
3. Copy the `FOLDER_ID` portion
4. Set it in config: `folder_id: "1aBcDeFgHiJkLmNoPqRsTuVwXyZ"`

Without a folder_id, docs are created in the root of your Drive.

## Step 8: Verify

Quick test from Python:

```python
from wiz.config.schema import GoogleDocsConfig
from wiz.integrations.google_docs import GoogleDocsClient

config = GoogleDocsConfig(enabled=True)
client = GoogleDocsClient.from_config(config)
result = client.create_document(
    title="Test Doc",
    body="# Hello\n\nThis is a **test**.",
    image_prompt="A sunset over mountains, oil painting style",
)
print(result.url)  # Opens in Google Docs
```

Or run the full content cycle:
```bash
wiz run content-cycle
```

Blog drafts and social posts will appear as Google Docs with image prompts appended.

---

## How It Works

When `google_docs.enabled` is `true` in the config:

1. **Content pipeline** creates a single `GoogleDocsClient` and passes it to both
   the blog writer and social manager agents
2. **Blog writer** creates one Google Doc per article, with the full markdown body
   and image generation prompt appended under a "---" separator
3. **Social manager** creates one Google Doc per social draft, with all post text
   and the image prompt appended
4. **Image prompts skip disk** — when Google Docs is enabled, image prompts are
   embedded in the doc instead of saved to `~/Documents/image-prompts/`
5. **Typefully still works** — social drafts are still pushed to Typefully for
   scheduling; the Google Doc is a companion for review

When `google_docs.enabled` is `false` (default), everything works as before —
blog drafts save to `~/Documents/blog-drafts/` and image prompts save to
`~/Documents/image-prompts/`.

## Markdown Conversion

The integration converts markdown to native Google Docs formatting:

| Markdown | Google Docs |
|----------|-------------|
| `# Heading` | Heading 1 |
| `## Heading` | Heading 2 |
| `### Heading` | Heading 3 |
| `**bold**` | Bold text |
| `` ```code``` `` | Courier New monospace |
| `- item` | Bullet list |
| `[text](url)` | Hyperlink |

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.wiz/google-credentials.json` | OAuth client credentials (from Cloud Console) |
| `~/.wiz/google-token.json` | Refresh token (created by `wiz google-auth`) |
| `src/wiz/integrations/google_docs.py` | Client implementation |
| `config/wiz.yaml` | Enable/configure via `google_docs` section |

## Security Notes

- The credentials file contains your OAuth client secret — don't commit it
- The token file contains a refresh token that can create Docs on your behalf
- Both files should be readable only by your user (`chmod 600`)
- The `drive.file` scope only allows access to files created by Wiz, not your
  entire Drive
- To revoke access: [Google Account Permissions](https://myaccount.google.com/permissions)
