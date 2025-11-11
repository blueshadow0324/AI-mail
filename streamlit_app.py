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
    return pipeline("summarization", model="t5-small")

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
    """Generate bullet-point summary from cleaned email text, ignoring filler sentences."""
    cleaned = clean_text(text)
    sentences = split_sentences(cleaned)

    # Filter out meaningless sentences
    ignore_patterns = [
        r"don't take our word",
        r"look inside \d+",
        r"the tale continues",
        r"join \d+",
        r"see what",
        r"click here",
        r"view in your browser"
    ]

    filtered_sentences = []
    for s in sentences:
        if any(re.search(pattern, s, re.IGNORECASE) for pattern in ignore_patterns):
            continue
        if len(s.split()) < 4:  # skip very short fragments
            continue
        filtered_sentences.append(s)

    bullets = []
    for s in filtered_sentences:
        try:
            result = summarizer("summarize: " + s, max_length=30, min_length=5, do_sample=False)
            bullet = result[0]['summary_text']
            bullets.append(f"- {bullet}")
        except:
            continue
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

if st.button("Fetch & Generate Bullet Summary"):
    emails_text = get_emails(max_results=max_emails)
    if not emails_text.strip():
        st.info("No emails found.")
    else:
        bullet_summary = generate_bullet_summary(emails_text)
        if not bullet_summary:
            st.info("Could not generate bullet summary. Text may be too short or noisy.")
        else:
            st.subheader("📌 Important Highlights:")
            st.text(bullet_summary)
