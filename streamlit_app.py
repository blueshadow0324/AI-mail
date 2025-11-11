import os
import re
import html
import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from transformers import pipeline

st.title("GBS AI")

# Gmail API scope
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# ---------- Summarizer ----------
@st.cache_resource
def load_summarizer():
    pipeline("summarization", model="facebook/bart-large-cnn")


summarizer = load_summarizer()

# ---------- Utility Functions ----------
def clean_text(text):
    """Clean and normalize text, remove HTML entities and Swedish letters."""
    text = html.unescape(text)
    replacements = {"å":"a","ä":"a","ö":"o","Å":"A","Ä":"A","Ö":"O"}
    for k,v in replacements.items():
        text = text.replace(k,v)
    text = re.sub(r"[^a-zA-Z0-9.,!?;:\n ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def split_sentences(text):
    """Split text into sentences using punctuation (no NLTK needed)."""
    sentences = re.split(r'[.!?]\s+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 3]

def generate_bullet_summary(text):
    """Generate simple bullet-point summary without heavy model calls."""
    cleaned = clean_text(text)
    sentences = split_sentences(cleaned)

    # Ignore marketing or filler lines
    ignore_patterns = [
        r"don't take our word", r"look inside", r"unsubscribe",
        r"click here", r"view in your browser", r"follow us",
        r"shop now", r"the tale continues", r"join",
        r"offer", r"discount", r"sale", r"terms and service",
        r"tjanster", r"jobb"
    ]

    filtered = []
    for s in sentences:
        if any(re.search(p, s, re.IGNORECASE) for p in ignore_patterns):
            continue
        if len(s.split()) < 4:
            continue
        filtered.append(s)

    # If no good sentences, return notice
    if not filtered:
        return "- No meaningful content found."

    # Extract likely important sentences
    keywords = ["update", "invite", "security", "order", "jobb", "job", "kund", "client"]
    important = [s for s in filtered if any(k in s.lower() for k in keywords)]

    # If nothing matched, just take first few sentences
    if not important:
        important = filtered[:5]

    bullets = [f"- {s.strip()}" for s in important]
    return "\n".join(bullets)




def get_emails(max_results=10):
    """Fetch latest Gmail messages with cached OAuth token."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save credentials for future use
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    results = service.users().messages().list(userId='me', maxResults=max_results).execute()
    messages = results.get('messages', [])

    emails_text = ""
    for i, msg in enumerate(messages, 1):
        msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
        snippet = msg_data.get('snippet', '')
        emails_text += f"{i}. {snippet}\n"
    return emails_text

# ---------- Streamlit UI ----------
max_emails = st.slider("Number of latest emails to fetch:", 1, 50, 10)
loading = st.empty()

if st.button("Fetch & Generate Bullet Summary"):
    emails_text = get_emails(max_results=max_emails)
    if not emails_text.strip():
        st.info("No emails found.")
    else:
        loading.text("Loading...")
        bullet_summary = generate_bullet_summary(emails_text)
        if not bullet_summary:
            loading.empty()
            st.info("Could not generate bullet summary. Text may be too short or noisy.")
        else:
            loading.empty()
            st.subheader("📌 Important Highlights:")
            st.text(bullet_summary)
