import streamlit as st
import re
import html
import requests
from datetime import datetime, timedelta
from transformers import pipeline
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import msal
import time

# ----------------- Page Config -----------------
st.set_page_config(page_title="GBS AI", page_icon="")
st.title("GBS AI")

# ----------------- Config -----------------
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

login_choice = st.radio("Login with:", ["Google"])

# ----------------- Session Initialization -----------------
if "google_creds" not in st.session_state:
    st.session_state.google_creds = None
if "ms_token" not in st.session_state:
    st.session_state.ms_token = None
if "msal_app" not in st.session_state:
    st.session_state.msal_app = None
if "google_flow" not in st.session_state:
    st.session_state.google_flow = None

# ----------------- Summarizer -----------------
@st.cache_resource
def load_summarizer():
    return pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
summarizer = load_summarizer()

# ----------------- Utils -----------------
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
    ignore_patterns = [r"unsubscribe", r"click here", r"view in your browser",
                       r"follow us", r"shop now", r"offer", r"sale", r"terms and service",
                       r"jobb", r"tjanster"]
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
        except Exception:
            bullets.append(f"- {s.strip()}")
    return "\n".join(bullets)

# ----------------- Google OAuth -----------------
if login_choice == "Google":
    CLIENT_ID = st.secrets["google"]["client_id"]
    CLIENT_SECRET = st.secrets["google"]["client_secret"]
    REDIRECT_URI = st.secrets["google"]["redirect_uri"]

    if st.session_state.google_flow is None:
        st.session_state.google_flow = Flow.from_client_config(
            {"web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }},
            scopes=GOOGLE_SCOPES,
            redirect_uri=REDIRECT_URI
        )
    flow = st.session_state.google_flow

# ----------------- Show Login Buttons -----------------
if login_choice == "Google" and st.session_state.google_creds is None:
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true",
        state="google"
    )
    st.markdown(f"[Login with Google]({auth_url})")

# ----------------- Email Fetching -----------------
def get_google_emails(max_results=10):
    creds = st.session_state.google_creds
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = results.get("messages", [])
    emails_text = ""
    for i, msg in enumerate(messages, 1):
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
        snippet = msg_data.get("snippet", "")
        emails_text += f"{i}. {snippet}\n"
    return emails_text


from datetime import datetime, timedelta
from googleapiclient.discovery import build
import streamlit as st

# Check if logged in
if st.session_state.get("google_creds"):
    t = st.text("Loading...")

    # Gmail service
    service = build("gmail", "v1", credentials=st.session_state.google_creds)

    # Today and tomorrow for Gmail search
    today = datetime.utcnow().strftime("%Y/%m/%d")
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y/%m/%d")

    # Fetch messages from today
    results = service.users().messages().list(
        userId='me',
        q=f"after:{today} before:{tomorrow}"
    ).execute()

    messages = results.get("messages", [])

    # Fetch snippets
    email_texts = []
    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
        snippet = msg_data.get("snippet", "")
        email_texts.append(snippet)

    # Join all snippets into one text
    all_text = "\n".join(email_texts)

    # Generate bullet summary (your function)
    summary = generate_bullet_summary(all_text)

    t.empty()  # remove loading text
    st.subheader("Today's Email Summary")
    st.text_area("Summary", value=summary, height=300)
