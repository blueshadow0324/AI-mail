import streamlit as st
import re
import html
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from transformers import pipeline
import requests

st.set_page_config(page_title="GBS", page_icon="")
st.title("GBS AI")

# -------------------- CONFIG --------------------
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MS_SCOPES = ["https://graph.microsoft.com/Mail.Read"]

login_choice = st.radio("Login with:", ["Google", "Microsoft"])

scopes = GOOGLE_SCOPES if login_choice == "Google" else MS_SCOPES


CLIENT_ID = st.secrets["google"]["client_id"]
CLIENT_SECRET = st.secrets["google"]["client_secret"]
REDIRECT_URI = st.secrets["google"]["redirect_uri"]
TENANT_ID = st.secrets["microsoft"]["tenant_id"]  # or "common"

# -------------------- SUMMARIZER --------------------
@st.cache_resource
def load_summarizer():
    return pipeline("summarization", model="facebook/bart-large-cnn")

summarizer = load_summarizer()

# -------------------- UTILITY --------------------
def clean_text(text):
    text = html.unescape(text)
    replacements = {"å":"a","ä":"a","ö":"o","Å":"A","Ä":"A","Ö":"O"}
    for k,v in replacements.items():
        text = text.replace(k,v)
    text = re.sub(r"[^a-zA-Z0-9.,!?;:\n ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def split_sentences(text):
    sentences = re.split(r'[.!?]\s+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 3]

def generate_bullet_summary(text):
    cleaned = clean_text(text)
    sentences = split_sentences(cleaned)
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
    keywords = ["update", "invite", "security", "order", "jobb", "job", "kund", "client"]
    important = [s for s in filtered if any(k in s.lower() for k in keywords)]
    if not important:
        important = filtered[:5]
    bullets = []
    for s in important:
        try:
            result = summarizer(s, max_length=30, min_length=5, do_sample=False)[0]["summary_text"]
            bullets.append(f"- {result}")
        except:
            bullets.append(f"- {s.strip()}")
    return "\n".join(bullets)

# -------------------- GOOGLE OAUTH --------------------
if "google_creds" not in st.session_state:
    st.session_state.google_creds = None

if login_choice == "Google" and st.session_state.google_creds is None:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        prompt="consent", access_type="offline", include_granted_scopes="true"
    )
    st.markdown(f"[Login with Google]({auth_url})")

    query_params = st.experimental_get_query_params()
    if "code" in query_params:
        code = query_params["code"][0]
        try:
            flow.fetch_token(code=code)
            st.session_state.google_creds = flow.credentials
            st.success("✅ Google login successful!")
        except Exception as e:
            st.error(f"⚠️ Google login failed: {e}")
            st.stop()


def get_emails_with_creds(creds, max_results=10):
    service = build("gmail", "v1", credentials=creds)
    results = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = results.get("messages", [])
    emails_text = ""
    for i, msg in enumerate(messages, 1):
        msg_data = service.users().messages().get(userId="me", id=msg["id"]).execute()
        snippet = msg_data.get("snippet", "")
        emails_text += f"{i}. {snippet}\n"
    return emails_text

# -------------------- MICROSOFT OAUTH --------------------
if "ms_access_token" not in st.session_state:
    st.session_state.ms_access_token = None

if login_choice == "Microsoft" and st.session_state.ms_access_token is None:
    from msal import ConfidentialClientApplication
    msal_app = ConfidentialClientApplication(
        CLIENT_ID, authority=f"https://login.microsoftonline.com/{TENANT_ID}", client_credential=CLIENT_SECRET
    )
    auth_url = msal_app.get_authorization_request_url(scopes, redirect_uri=REDIRECT_URI)
    st.markdown(f"[Login with Microsoft]({auth_url})")
    query_params = st.experimental_get_query_params()
    if "code" in query_params and st.session_state.ms_access_token is None:
        code = query_params["code"][0]
        result = msal_app.acquire_token_by_authorization_code(code, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        if "access_token" in result:
            st.session_state.ms_access_token = result["access_token"]
            st.success("✅ Microsoft login successful!")
        else:
            st.error(f"Login failed: {result.get('error_description')}")

def get_microsoft_emails(max_results=10):
    headers = {"Authorization": f"Bearer {st.session_state.ms_access_token}"}
    url = f"https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages?$top={max_results}&$select=subject,bodyPreview"
    response = requests.get(url, headers=headers)
    emails = response.json().get("value", [])
    emails_text = ""
    for i, e in enumerate(emails, 1):
        emails_text += f"{i}. {e.get('subject','')}: {e.get('bodyPreview','')}\n"
    return emails_text

# -------------------- STREAMLIT UI --------------------
max_emails = st.slider("Number of latest emails to fetch:", 1, 50, 10)

if st.button("Fetch & Generate Bullet Summary"):
    loading = st.empty()
    loading.text("Fetching emails...")

    if login_choice == "Google" and st.session_state.google_creds:
        emails_text = get_emails_with_creds(st.session_state.google_creds, max_results=max_emails)
    elif login_choice == "Microsoft" and st.session_state.ms_access_token:
        emails_text = get_microsoft_emails(max_results=max_emails)
    else:
        st.warning("Please log in first!")
        emails_text = ""

    if emails_text:
        loading.text("Generating bullet summary...")
        bullet_summary = generate_bullet_summary(emails_text)
        loading.empty()
        st.subheader("📌 Important Highlights:")
        st.text(bullet_summary)
