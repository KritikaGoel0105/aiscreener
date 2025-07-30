 # app.py

import streamlit as st
import pandas as pd
import base64
import asyncio
from datetime import datetime
from io import BytesIO
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
datetime.now()
import datetime
from datetime import timedelta

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
from constants import AZURE_CONFIG
from utils import (
    parse_resume,
    get_text_chunks,
    get_embedding_cached,
    get_cosine_similarity,
    upload_to_blob,
    extract_contact_info,
    save_summary_to_blob,
    save_csv_to_blob
)
from backend import get_resume_analysis_async, extract_role_from_jd
from pdf_utils import generate_summary_pdf
from email_generator import send_email, check_missing_info, send_missing_info_email, schedule_interview
# flow = InstalledAppFlow.from_client_secrets_file(
#     'credentials.json', SCOPES
# )
# creds = flow.run_local_server(port=0)


# At the top of your Streamlit app
if "candidate_df" not in st.session_state:
    st.session_state["candidate_df"] = None
if "analysis_done" not in st.session_state:
    st.session_state["analysis_done"] = False

st.set_page_config(layout="wide", page_title="AI Resume Screener")
st.markdown("<h1 style='text-align:center;'>🤖 AI Resume Screener</h1>", unsafe_allow_html=True)
st.markdown("---")

# ========== Sidebar Inputs ==========
with st.sidebar:
    jd = st.text_area("📄 Paste Job Description", height=200)
    role = "N/A"
    if jd:
        role = extract_role_from_jd(jd)
        st.markdown(f"🧠 **Extracted Role:** `{role}`")

    domain = st.text_input("🏢 Preferred Domain", "")
    skills = st.text_area("🛠️ Required Skills (comma separated)", "")
    exp_range = st.selectbox("📈 Required Experience", ["0–1 yrs", "1–3 yrs", "2–4 yrs", "4+ yrs"])

    st.markdown("### 🎚️ Thresholds")
    jd_thresh = st.slider("JD Similarity", 0, 100, 50)
    skill_thresh = st.slider("Skills Match", 0, 100, 50)
    domain_thresh = st.slider("Domain Match", 0, 100, 50)
    exp_thresh = st.slider("Experience Match", 0, 100, 50)
    score_thresh = st.slider("Final Score Threshold", 0, 100, 50)
    top_n = st.number_input("🎯 Top-N Candidates", 0, value=0)

    uploaded_files = st.file_uploader("📤 Upload Resumes (PDF)", type=["pdf"], accept_multiple_files=True)
    analyze = st.button("🚀 Analyze")

# ========== Processing ==========
if jd and uploaded_files and analyze and not st.session_state["analysis_done"]:
    progress = st.progress(0, text="Starting Analysis...")
    total = len(uploaded_files)
    results = []
    jd_embedding = get_embedding_cached(jd)
    

    async def process_all():
        tasks = []
        for idx, file in enumerate(uploaded_files):
            file_bytes = file.read()
            file_name = file.name.replace(".pdf", "")
            upload_to_blob(file_bytes, file_name + ".pdf", AZURE_CONFIG["resumes_container"])

            resume_text = parse_resume(file_bytes)
            contact = extract_contact_info(resume_text)

            chunks = get_text_chunks(resume_text)
            resume_embedding = get_embedding_cached(" ".join(chunks))
            jd_sim = round(get_cosine_similarity(resume_embedding, jd_embedding) * 100, 2)

            task = get_resume_analysis_async(
                jd=jd,
                resume_text=resume_text,
                contact=contact,
                role=role,
                domain=domain,
                skills=skills,
                experience_range=exp_range,
                jd_similarity=jd_sim,
                resume_file=file_name
            )
            tasks.append(task)

        return await asyncio.gather(*tasks)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for i in range(len(uploaded_files)):
        progress.progress(i / total, text=f"Processing {i+1} of {total}...")

    results = loop.run_until_complete(process_all())
    loop.close()

    for r in results:
        r["recruiter_notes"] = ""
        if r["score"] < score_thresh and r["verdict"] != "reject":
            r["verdict"] = "reject"
            r.setdefault("reasons_if_rejected", []).append(
                f"Score below threshold {r['score']} < {score_thresh}"
            )

    st.success("✅ All resumes processed!")
    df = pd.DataFrame(results).fillna("N/A")
    df.replace("n/a", "N/A", regex=True, inplace=True)
    missing_info = df[df.apply(lambda row: not row.get("contact", {}).get("email"), axis=1)]
    for _, row in missing_info.iterrows():
        email = row.get("contact", {}) or {}
        #email= contact.get('email')
        if email:
            send_missing_info_email(email=email, name=row.get("name", "Candidate"))

    #df = df[~df.index.isin(missing_info_df.index)]
    df["has_missing_info"] = df.apply(lambda row: not row.get("contact", {}).get("email") or not row.get("contact", {}).get("phone"), axis=1)

    for _, row in df[df["has_missing_info"]].iterrows():
        email = row.get("contact", {}).get("email")
        if email:
            send_missing_info_email(email=email, name=row["name"])

    # Verdict Logic
    def verdict_logic(row):
        #if row["has_missing_info"]:
            #return "review"
        if row["verdict"] == "reject":
            return "reject"
        elif (
            row["jd_similarity"] < jd_thresh or
            row["skills_match"] < skill_thresh or
            row["domain_match"] < domain_thresh or
            row["experience_match"] < exp_thresh
        ):
            return "review"
        return "shortlist"

    df["verdict"] = df.apply(verdict_logic, axis=1)

    # Top-N Shortlisting
    if top_n > 0:
        sorted_df = df.sort_values("score", ascending=False)
        top = sorted_df.head(top_n).copy()
        top["verdict"] = "shortlist"
        rest = sorted_df.iloc[top_n:].copy()
        rest["verdict"] = rest["verdict"].apply(lambda v: v if v == "reject" else "review")
        df = pd.concat([top, rest], ignore_index=True)
    st.session_state["candidate_df"] = df
    st.session_state["analysis_done"] = True

    # ========== Display Tabs ==========
if st.session_state["candidate_df"] is not None:
    df = st.session_state.get("candidate_df", pd.DataFrame())  # fetch safely
    tabs = st.tabs(["✅ Shortlisted", "🟨 Under Review", "❌ Rejected", "📊 Analytics"])
    REQUIRED_FIELDS = ["email", "name", "phone"]  # Add or remove as per your needs
    # def get_missing_fields(row):
    #     missing = []
    #     for field in REQUIRED_FIELDS:
    #         if pd.isna(row.get(field)) or str(row.get(field)).strip() == "":
    #             missing.append(field)
    #     return missing
    under_review = []
    shortlisted = []
    rejected = []
    

    for idx, row in df.iterrows():
        missing_fields = check_missing_info(row)
        if missing_fields:
            row["verdict"] = "under review"  # Store what is missing
            under_review.append(row)
        elif row["verdict"] == "shortlisted":
            shortlisted.append(row)
        elif row["verdict"] == "rejected":
            rejected.append(row)
    def send_missing_info_email(email, missing_fields):
        missing_str = ', '.join(missing_fields)
        subject = "Missing Information for Job Application"
        body = f"Dear Candidate,\n\nWe noticed that the following information is missing from your profile: {missing_str}.\nPlease reply with the necessary details at your earliest convenience.\n\nRegards,\nRecruitment Team"
        send_email(email, subject, body)

    
    # tab_under_review, tab_shortlisted, tab_rejected = st.tabs(["Under Review", "Shortlisted", "Rejected"])

    for verdict, tab in zip(["shortlist", "review", "reject"], tabs[:3]):
        
        with tab:
            filtered = df[df["verdict"] == verdict]
            st.markdown(f"### {verdict.title()} Candidates ({len(filtered)})")
            if verdict == "reject":
                if len(filtered) > 0:
                    st.markdown("#### ✉️ Bulk Rejection Email")
                    if st.button("📬 Send Rejection Emails to All"):
                        seen_emails = set()
                        for i, row in filtered.iterrows():
                            contact = row.get("contact") or {}
                            email = contact.get("email", "")
                            if email in seen_emails:
                                continue
                            seen_emails.add(email)

                            if email:
                                subject = "Application Update"
                                body = f"Dear {row['name']},\n\nThank you for your interest in the role. Unfortunately, we will not be proceeding with your application at this time.\n\nWe wish you success in your future endeavors.\n\nRegards,\nRecruitment Team"
                                success = send_email(email, subject, body)
                                if success:
                                    st.success(f"Email sent to {row['name']} at {email}")
                                else:
                                    st.error(f"Failed to send email to {row['name']}")
                            rejected_candidates = df[df['verdict'] == 'reject']
                            if not rejected_candidates.empty:
                                for _, row in rejected_candidates.iterrows():
                                    if pd.notna(row.get('email', '')) and row['email'].strip():
                                        subject = "Application Status"
                                        body = f"Dear {row['name']},\n\nThank you for applying. Unfortunately, we are not proceeding with your application at this time.\n\nBest regards,\nRecruitment Team"
                                        send_email(row['email'], subject, body)
                                st.success("Bulk rejection emails sent.")
                            else:
                                st.warning("No rejected candidates to email.")
                            # print(f"Bulk rejection button clicked")
                            # print("Rejected Candidates:")
                            # print(rejected_candidates)
                else:
                    st.info("No rejected candidates to email.")

        
            for i, row in filtered.iterrows():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"#### 👤 {row['name']}")
                    st.markdown(f"📧 **Email:** {row['email']} | 📞 **Phone:** {row['phone']}")
                    st.markdown(f"📌 **Fitment:** {row['fitment']}")
                    st.markdown(f"🔢 **Scores:** JD: {row['jd_similarity']} | Skills: {row['skills_match']} | Domain: {row['domain_match']} | Exp: {row['experience_match']} | Final: {row['score']}")
                    
                    contact = row.get("contact", {}) or {}
                    email = contact.get("email", "")
                    email_part = row['email'] if pd.notna(row.get('email', '')) and row.get('email', '').strip() else f"noemail_{i}"
                    # note_key = f"note_{i}_{row['name']}_{email_part}"
                    note_key = f"note_{i}_{row['name']}_{row['email']}_{uuid.uuid4().hex}"

                    #note_key = f"note_{i}_{row.get('name', '')}_{email}"
                    verdict_key = f"verdict_{i}"

                    if note_key not in st.session_state:
                        st.session_state[note_key] = row["recruiter_notes"]
                    if verdict_key not in st.session_state:
                        st.session_state[verdict_key] = row["verdict"]
                    new_note = st.text_area("📝 Recruiter Notes", value=st.session_state.get(note_key, ""), key=note_key)
                    new_verdict = st.selectbox("🔁 Override Verdict", ["shortlist", "review", "reject"], index=["shortlist", "review", "reject"].index(st.session_state[verdict_key]), key=verdict_key)

                    df.at[i, "recruiter_notes"] = new_note
                    df.at[i, "verdict"] = new_verdict

                with col2:
                    pdf_bytes = generate_summary_pdf(row)
                    summary_name = f"{row['name'].replace(' ', '_')}_{row['verdict'].capitalize()}.pdf"
                    save_summary_to_blob(pdf_bytes, summary_name, AZURE_CONFIG["summaries_container"])
                    to_email = (row.get("contact") or {}).get("email", "")
                    with tabs[1]:
                        # st.header("🕵️ Candidates Under Review")
                        if not under_review:
                            st.info("No candidates with missing information.")
                        for i, row in enumerate(under_review):
                            st.subheader(f"{row['name']}")

                            missing = row.get("missing_info", [])
                            if missing:
                                st.warning(f"❗ Missing: {', '.join(missing)}")

                            # Email logic
                            if st.button(f"✉️ Send Request for Info - {row['email']}", key=f"underreview_{i}"):
                                send_missing_info_email(row['email'], missing)  # You must define this function
                                st.success("Email sent.")
                    


                    if st.button(f"✉️ Send Email to {row.get('name', 'Candidate')}", key=f"email_button_{i}_{email}"):
                            if verdict == "shortlist":
                                subject = "Congratulations! You have been shortlisted"
                                body = f"Dear {row['name']},\n\nYou have been shortlisted for the role based on your profile. We will be in touch with next steps.\n\nBest,\nRecruitment Team"
                                success = send_email(row['email'], subject, body)
                                if success:
                                    st.success(f"Email sent to {row['name']}")
                                else:
                                    st.error("Failed to send email.")
                                    # === Schedule Interview (Only for shortlisted candidates) ===
                                shortlisted_df = df[df["verdict"] == "shortlist"]
                                for i, row in shortlisted_df.iterrows():
                                    st.subheader(f"{row['name']} - {row['email']}")
                                    default_dt = datetime.datetime.now() + datetime.timedelta(days=1)

                                    # Interview date input (default = tomorrow)
                                    interview_date = st.text_input(
                                        f"Interview Date for {row["name"]}",
                                        value=(datetime.datetime.now() + timedelta(days=1)).date().isoformat()
                                    )

                                    # Interview time input (dropdown, 30 min intervals)
                                    interview_time = st.selectbox(
                                        f"Interview Time for {row["name"]}",
                                        [f"{hour:02d}:{minute:02d}" for hour in range(9, 18) for minute in (0, 30)]
                                    )

                                    if st.button(f"📅 Schedule Interview - {email}"):
                                        st.write("🔄 Scheduling interview...")

                                        if not interview_date or not interview_time:
                                            st.warning("⚠️ Please enter both interview date and time.")
                                        else:
                                            try:
                                                meet_link = schedule_interview(email, row["name"], interview_date.replace("-", "/"), interview_time)
                                                if meet_link:
                                                    st.success(f"✅ Interview Scheduled! Google Meet: {meet_link}")
                                                    st.markdown(f"[Join Meet]({meet_link})", unsafe_allow_html=True)
                                                else:
                                                    st.warning("⚠️ Schedule function ran but did not return a meeting link.")
                                            except Exception as e:
                                                st.error(f"❌ Failed to schedule interview: {e}")


                            elif verdict== "review":
                                subject= "Information Required for your job application."
                                missing_list = ", ".join(missing_info)
                                body = f"""Dear {row['name']},\n\nThank you for your interest in the position.\n\nTo proceed with your application, we need the following missing information: {missing_list}.Please reply to this email with the required details at your earliest convenience.\n\nBest regards,\n\nRecruitment Team"""

                                success = send_email(row['email'], subject, body)
                                if success:
                                    st.success(f"Missing info email sent to {row['name']}")
                                else:
                                    st.error(f"❌ Failed to send email to {row['name']}")
                            else:
                                subject = "Application Update"
                                body = f"Dear {row['name']},\n\nThank you for your interest. At this time, we will not be moving forward with your application. We wish you the best in your future endeavors.\n\nRegards,\nRecruitment Team"
        
                                success = send_email(row['email'], subject, body)
                                if success:
                                    st.success(f"Email sent to {row['name']}")
                                else:
                                    st.error("Failed to send email.")

                    b64 = base64.b64encode(pdf_bytes).decode()
                    st.markdown(f'<a href="data:application/octet-stream;base64,{b64}" download="{summary_name}">📥 Download Summary</a>', unsafe_allow_html=True)

            # CSV Export (no reprocessing)
            export_df = filtered.drop(columns=["resume_text"], errors="ignore")
            csv_name = f"{verdict}_export_{datetime.datetime.now().strftime('%Y-%m-%d')}.csv"
            save_csv_to_blob(export_df, csv_name, AZURE_CONFIG["csv_container"])
            st.download_button("📤 Download CSV", export_df.to_csv(index=False), file_name=csv_name)

    # ========== Analytics Tab ==========
    with tabs[3]:
        st.dataframe(df.drop(columns=["resume_text", "embedding"], errors="ignore"))
        st.subheader("📊 Analytics Dashboard")
        st.markdown("#### Verdict Breakdown")
        st.bar_chart(df["verdict"].value_counts())

        st.markdown("#### Score Distribution")
        st.line_chart(df[["jd_similarity", "skills_match", "domain_match", "experience_match", "score"]])

        flagged = df[df["fraud_detected"] == True]
        if not flagged.empty:
            st.markdown("#### 🚨 Fraud/Red Flags")
            st.dataframe(flagged[["name", "red_flags", "missing_gaps"]])
        else:
            st.success("✅ No fraud or red flags.")

