import streamlit as st
import html
import re
from transformers import pipeline
import requests

# -------------------- CONFIG --------------------
st.set_page_config(page_title="GBS AI", page_icon="📝")
st.title("GBS AI")

# Google OAuth PKCE flow
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GOOGLE_CLIENT_ID = st.secrets["google"]["client_id"]
GOOGLE_CLIENT_SECRET = st.secrets["google"]["client_secret"]

# Microsoft Device Code flow
MS_SCOPES = ["Mail.Read"]
MS_CLIENT_ID = st.secrets["microsoft"]["client_id"]
MS_TENANT_ID = st.secrets["microsoft"]["tenant_id"]

login_choice = st.radio("Login with:", ["Google", "Microsoft"])

# -------------------- SUMMARIZER --------------------
@st.cache_resource
def load_summarizer():
    return pipeline("summarization", model="facebook/bart-large-cnn")

summarizer = load_summarizer()

# -------------------- UTILITIES --------------------
def clean_text(text):
    text = html.unescape(text)
    text = text.translate(str.maketrans("åäöÅÄÖ", "aaoAAO"))
    text = re.sub(r"[^a-zA-Z0-9.,!?;:\n ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def split_sentences(text):
    return [s.strip() for s in re.split(r'[.!?]\s+', text) if len(s.strip()) > 3]

def generate_bullet_summary(text):
    cleaned = clean_text(text)
    sentences = split_sentences(cleaned)
    ignore_patterns = [
        r"unsubscribe", r"click here", r"view in your browser",
        r"follow us", r"shop now", r"offer", r"sale", r"terms and service",
        r"jobb", r"tjanster"
    ]
    filtered = [s for s in sentences if not any(re.search(p, s, re.I) for p in ignore_patterns)]
    filtered = [s for s in filtered if len(s.split()) >= 4]
    if not filtered:
        return "- No meaningful content found."
    keywords = ["update", "invite", "security", "order", "jobb", "client"]
    important = [s for s in filtered if any(k in s.lower() for k in keywords)] or filtered[:5]
    bullets = []
    for s in important:
        try:
            summary = summarizer(s, max_length=30, min_length=5, do_sample=False)[0]["summary_text"]
            bullets.append(f"- {summary}")
        except:
            bullets.append(f"- {s.strip()}")
    return "\n".join(bullets)

# -------------------- GOOGLE LOGIN --------------------
if login_choice == "Google":
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if "google_creds" not in st.session_state:
        st.session_state.google_creds = None

    if st.session_state.google_creds is None:
        st.info("Click below to log in with Google")
        if st.button("Login with Google"):
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": GOOGLE_CLIENT_ID,
                        "client_secret": GOOGLE_CLIENT_SECRET,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                scopes=GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)
            st.session_state.google_creds = creds
            st.success("✅ Google login successful!")

    def get_google_emails(creds, max_results=10):
        service = build("gmail", "v1", credentials=creds)
        results = service.users().messages().list(userId="me", maxResults=max_results).execute()
        messages = results.get("messages", [])
        emails_text = ""
        for i, msg in enumerate(messages, 1):
            msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
            snippet = msg_data.get("snippet", "")
            emails_text += f"{i}. {snippet}\n"
        return emails_text

# -------------------- MICROSOFT LOGIN --------------------
elif login_choice == "Microsoft":
    import msal
    import time

    if "ms_access_token" not in st.session_state:
        st.session_state.ms_access_token = None

    if st.session_state.ms_access_token is None:
        st.info("Follow instructions to log in with Microsoft")
        if st.button("Login with Microsoft"):
            app = msal.PublicClientApplication(
                client_id=MS_CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{MS_TENANT_ID}"
            )
            # Device code flow
            device_flow = app.initiate_device_flow(scopes=MS_SCOPES)
            st.write(f"Go to {device_flow['verification_uri']} and enter the code: **{device_flow['user_code']}**")
            st.write("Waiting for login...")
            # Polling
            token_response = app.acquire_token_by_device_flow(device_flow)
            if "access_token" in token_response:
                st.session_state.ms_access_token = token_response["access_token"]
                st.success("✅ Microsoft login successful!")
            else:
                st.error(f"Microsoft login failed: {token_response.get('error_description')}")

    def get_microsoft_emails(max_results=10):
        headers = {"Authorization": f"Bearer {st.session_state.ms_access_token}"}
        url = f"https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages?$top={max_results}&$select=subject,bodyPreview"
        response = requests.get(url, headers=headers)
        emails = response.json().get("value", [])
        emails_text = ""
        for i, e in enumerate(emails, 1):
            emails_text += f"{i}. {e.get('subject','')}: {e.get('bodyPreview','')}\n"
        return emails_text

# -------------------- UI --------------------
max_emails = st.slider("Number of latest emails to fetch:", 1, 50, 10)

if st.button("Fetch & Generate Summary"):
    loading = st.empty()
    loading.text("Fetching emails...")

    if login_choice == "Google" and st.session_state.google_creds:
        emails_text = get_google_emails(st.session_state.google_creds, max_results=max_emails)
    elif login_choice == "Microsoft" and st.session_state.ms_access_token:
        emails_text = get_microsoft_emails(max_results=max_emails)
    else:
        st.warning("Please log in first!")
        st.stop()

    loading.text("Generating bullet summary...")
    summary = generate_bullet_summary(emails_text)
    loading.empty()
    st.subheader("Important Highlights:")
    st.text(summary)
