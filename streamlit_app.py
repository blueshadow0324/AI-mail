import streamlit as st
import re
import html
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from transformers import pipeline

st.set_page_config(page_title="GBS", page_icon="")
st.title("GBS AI")

# -------------------- CONFIG --------------------
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# OAuth credentials from Streamlit Secrets
CLIENT_ID = st.secrets["google"]["client_id"]
CLIENT_SECRET = st.secrets["google"]["client_secret"]
REDIRECT_URI = st.secrets["google"]["redirect_uri"]

# -------------------- SUMMARIZER --------------------
@st.cache_resource
def load_summarizer():
    return pipeline("summarization", model="facebook/bart-large-cnn")

summarizer = load_summarizer()

# -------------------- UTILITY FUNCTIONS --------------------
def clean_text(text):
    """Clean text: remove HTML entities and Swedish letters."""
    text = html.unescape(text)
    replacements = {"å":"a","ä":"a","ö":"o","Å":"A","Ä":"A","Ö":"O"}
    for k,v in replacements.items():
        text = text.replace(k,v)
    text = re.sub(r"[^a-zA-Z0-9.,!?;:\n ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def split_sentences(text):
    """Split text into sentences using punctuation."""
    sentences = re.split(r'[.!?]\s+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 3]

def generate_bullet_summary(text):
    """Generate bullet summary using keywords and optional model."""
    cleaned = clean_text(text)
    sentences = split_sentences(cleaned)

    # Ignore marketing/filler lines
    ignore_patterns = [
        r"don't take our word", r"look inside", r"unsubscribe",
        r"click here", r"view in your browser", r"follow us",
        r"shop now", r"the tale continues", r"join",
        r"offer", r"discount", r"sale", r"terms and service",
        r"tjanster", r"jobb"
    ]

    filtered = [s for s in sentences if not any(re.search(p, s, re.IGNORECASE) for p in ignore_patterns)]
    filtered = [s for s in filtered if len(s.split()) >= 4]

    if not filtered:
        return "- No meaningful content found."

    # Filter important sentences based on keywords
    keywords = ["update", "invite", "security", "order", "jobb", "job", "kund", "client"]
    important = [s for s in filtered if any(k in s.lower() for k in keywords)]

    if not important:
        important = filtered[:5]  # fallback to first few sentences

    # Optional: summarize with model (commented if you want faster response)
    bullets = []
    for s in important:
        try:
            result = summarizer(s, max_length=30, min_length=5, do_sample=False)[0]["summary_text"]
            bullets.append(f"- {result}")
        except:
            bullets.append(f"- {s.strip()}")
    return "\n".join(bullets)

# -------------------- GOOGLE OAUTH --------------------
if "creds" not in st.session_state:
    st.session_state.creds = None

if st.session_state.creds is None:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
    st.markdown(f"[Login with Google]({auth_url})")
    code = st.text_input("Enter the code from Google here:")

    if code:
        flow.fetch_token(code=code)
        st.session_state.creds = flow.credentials
        st.success("Login successful!")

# -------------------- EMAIL FETCH --------------------
def get_emails_with_creds(creds, max_results=10):
    """Fetch Gmail snippets using OAuth credentials."""
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = results.get("messages", [])

    emails_text = ""
    for i, msg in enumerate(messages, 1):
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
        snippet = msg_data.get("snippet", "")
        emails_text += f"{i}. {snippet}\n"
    return emails_text

# -------------------- STREAMLIT UI --------------------
if st.session_state.creds:
    max_emails = st.slider("Number of latest emails to fetch:", 1, 50, 10)
    if st.button("Fetch & Generate Bullet Summary"):
        loading = st.empty()
        loading.text("Fetching emails...")
        emails_text = get_emails_with_creds(st.session_state.creds, max_results=max_emails)
        loading.text("Generating bullet summary...")
        bullet_summary = generate_bullet_summary(emails_text)
        loading.empty()
        st.subheader("Important Highlights:")
        st.text(bullet_summary)
