import streamlit as st
import re
import html
import requests
from transformers import pipeline
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import msal

# ----------------- Page Config -----------------
st.set_page_config(page_title="GBS AI", page_icon="")
st.title("GBS AI")

# ----------------- Config -----------------
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MS_SCOPES = ["Mail.Read"]

login_choice = st.radio("Login with:", ["Google", "Microsoft"])

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

# ----------------- Microsoft OAuth -----------------
if login_choice == "Microsoft":
    CLIENT_ID = st.secrets["microsoft"]["client_id"]
    CLIENT_SECRET = st.secrets["microsoft"]["client_secret"]
    REDIRECT_URI = st.secrets["microsoft"]["redirect_uri"]
    AUTHORITY = "https://login.microsoftonline.com/common"

    if st.session_state.msal_app is None:
        st.session_state.msal_app = msal.ConfidentialClientApplication(
            client_id=CLIENT_ID,
            authority=AUTHORITY,
            client_credential=CLIENT_SECRET
        )
    msal_app = st.session_state.msal_app

# ----------------- Handle OAuth Redirect -----------------
query_params = st.experimental_get_query_params()
if "code" in query_params and "state" in query_params:
    state = query_params.get("state", [None])[0]

    # -------- Google --------
    if state == "google" and st.session_state.google_creds is None:
        try:
            flow.fetch_token(code=query_params["code"][0])
            st.session_state.google_creds = flow.credentials
            st.experimental_set_query_params()  # Clear ?code=... from URL
            st.success("Google login successful!")
        except Exception as e:
            st.error(f"Google login failed: {e}")

    # -------- Microsoft --------
    elif state == "microsoft" and st.session_state.ms_token is None:
        try:
            code = query_params["code"][0]
            token_result = msal_app.acquire_token_by_authorization_code(
                code,
                scopes=MS_SCOPES,
                redirect_uri=REDIRECT_URI
            )
            if "access_token" in token_result:
                st.session_state.ms_token = token_result["access_token"]  # Store immediately
                st.experimental_set_query_params()
                st.success("Microsoft login successful!")
            else:
                st.error(f"Microsoft login failed: {token_result.get('error_description')}")
        except Exception as e:
            st.error(f"Microsoft login error: {e}")

# ----------------- Show Login Buttons -----------------
if login_choice == "Google" and st.session_state.google_creds is None:
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true",
        state="google"
    )
    st.markdown(f"[Login with Google]({auth_url})")

elif login_choice == "Microsoft" and st.session_state.ms_token is None:
    auth_url = msal_app.get_authorization_request_url(
        MS_SCOPES,
        redirect_uri=REDIRECT_URI,
        state="microsoft"
    )
    st.markdown(f"[Login with Microsoft]({auth_url})")

# ----------------- Email Fetching Functions -----------------
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

def get_microsoft_emails(max_results=10):
    token = st.session_state.get("ms_token")
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/messages?$top={max_results}&$select=subject,bodyPreview"
    response = requests.get(url, headers=headers)
    if response.status_code == 401:
        st.warning("Microsoft token expired. Please log in again.")
        return None
    elif response.status_code != 200:
        st.error(f"Microsoft Graph error ({response.status_code}): {response.text}")
        return None
    data = response.json()
    emails = [m.get("bodyPreview", "") for m in data.get("value", [])]
    return "\n".join(emails)

# ----------------- UI: Fetch & Summarize -----------------
max_emails = st.slider("Number of latest emails to fetch:", 1, 50, 10)

if st.button("Fetch & Generate Summary"):
    loading = st.empty()
    loading.text("Fetching emails...")

    emails_text = None

    # -------- Google --------
    google_creds = st.session_state.get("google_creds")
    if google_creds:
        try:
            if google_creds.expired and google_creds.refresh_token:
                google_creds.refresh(Request())
            if google_creds.valid:
                emails_text = get_google_emails(max_results=max_emails)
        except Exception as e:
            st.error(f"Error fetching Google emails: {e}")
            emails_text = None

    # -------- Microsoft --------
    ms_token = st.session_state.get("ms_token")
    if emails_text is None and ms_token:
        try:
            emails_text = get_microsoft_emails(max_results=max_emails)
        except Exception as e:
            st.error(f"Error fetching Microsoft emails: {e}")
            emails_text = None

    if emails_text is None or emails_text.strip() == "":
        st.warning("Please log in first or something went wrong!")
        st.stop()

    loading.text("Generating bullet summary...")
    try:
        summary = generate_bullet_summary(emails_text)
        loading.empty()
        st.subheader("Important Highlights:")
        st.text(summary)
    except Exception as e:
        loading.empty()
        st.error(f"Error generating summary: {e}")
