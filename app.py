import streamlit as st
import re
import html
import requests
from transformers import pipeline
import msal

st.set_page_config(page_title="GBS AI", page_icon="")
st.title("GBS AI")

# ---------------- CONFIG ----------------
MS_SCOPES = ["https://graph.microsoft.com/Mail.Read"]

# ----------------- SESSION INITIALIZATION -----------------
if "ms_token" not in st.session_state:
    st.session_state.ms_token = None

# ----------------- SUMMARIZER -----------------
@st.cache_resource
def load_summarizer():
    return pipeline("summarization", model="facebook/bart-large-cnn")
summarizer = load_summarizer()

# ----------------- UTILS -----------------
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
        r"follow us", r"shop now", r"offer", r"sale",
        r"terms and service", r"jobb", r"tjanster"
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
        except Exception:
            bullets.append(f"- {s.strip()}")
    return "\n".join(bullets)

# ----------------- MICROSOFT LOGIN -----------------
CLIENT_ID = st.secrets["microsoft"]["client_id"]
CLIENT_SECRET = st.secrets["microsoft"]["client_secret"]
REDIRECT_URI = st.secrets["microsoft"]["redirect_uri"]
AUTHORITY = "https://login.microsoftonline.com/common"

msal_app = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

query_params = st.experimental_get_query_params()
if "code" in query_params and st.session_state.ms_token is None:
    code = query_params["code"][0]
    token_result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=MS_SCOPES,
        redirect_uri=REDIRECT_URI
    )
    if "access_token" in token_result:
        st.session_state.ms_token = token_result["access_token"]
        st.success("Microsoft login successful!")
        st.experimental_set_query_params()  # clear code
    else:
        st.error(f"Microsoft login failed: {token_result.get('error_description')}")
        st.stop()

if st.session_state.ms_token is None:
    auth_url = msal_app.get_authorization_request_url(MS_SCOPES, redirect_uri=REDIRECT_URI)
    st.markdown(f"[Login with Microsoft]({auth_url})")

def get_microsoft_emails(max_results=10):
    token = st.session_state.get("ms_token")
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/messages?$top={max_results}&$select=subject,bodyPreview"
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        st.error(f"Microsoft Graph error ({response.status_code}): {response.text}")
        return None
    data = response.json()
    emails = [m.get("bodyPreview", "") for m in data.get("value", [])]
    return "\n".join(emails)

# ----------------- UI -----------------
max_emails = st.slider("Number of latest emails to fetch:", 1, 50, 10)

if st.button("Fetch & Generate Summary"):
    loading = st.empty()
    loading.text("Fetching emails...")

    emails_text = get_microsoft_emails(max_results=max_emails)
    if not emails_text:
        st.warning("Please log in first or something went wrong!")
        st.stop()

    loading.text("Generating bullet summary...")
    summary = generate_bullet_summary(emails_text)
    loading.empty()
    st.subheader("Important Highlights:")
    st.text(summary)
