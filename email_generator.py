import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime

def send_email(to_email, subject, body):
    from_email = "prishabadwaik812@gmail.com"
    password = "yljkxbxtfkdjboli"  # App password, NOT your Gmail password

    message = MIMEMultipart()
    message["From"] = from_email
    message["To"] = to_email
                            #to_email= row['email']
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_email, password)
            server.sendmail(from_email, to_email, message.as_string())
        return True
    except Exception as e:
        print("Failed to send email: ", e)
        return False
                        
def check_missing_info(row):
    missing_fields = []
    # Treat empty strings or 'N/A' (case-insensitive) as missing
    def is_missing(value):
        return pd.isna(value) or str(value).strip().lower() in ["", "n/a"]

    if is_missing(row.get("name", "")):
        missing_fields.append("name")
    if is_missing(row.get("email", "")):
        missing_fields.append("email")
    
    # If you want phone number excluded for now, keep it commented
    if is_missing(row.get("phone", "")):
         missing_fields.append("phone number")

    return missing_fields

    
def send_missing_info_email(to_email, name, missing_fields):
    sender_email = "prishabadwaik812@gmail.com"
    sender_password = "yljkxbxtfkdjboli"  # Use Gmail App Password
    subject = "Additional Information Required for Application"
    
    missing_str = ", ".join(missing_fields).title()
    body = f"""
    Dear {name or 'Candidate'},

    Thank you for submitting your resume for the position.

    However, we noticed that the following information is missing from your application: {missing_str}.

    Kindly reply to this email with the missing details so we can continue processing your application.

    Best regards,  
    Recruitment Team
    """

    message = f"Subject: {subject}\n\n{body}"

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, message)
            print(f"✅ Missing info email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send missing info email to {to_email}: {e}")

# def schedule_interview(name, email, date_time, duration_minutes=30):
#     SCOPES = ['https://www.googleapis.com/auth/calendar']
#     SERVICE_ACCOUNT_FILE = 'credentials.json'

#     credentials = service_account.Credentials.from_service_account_file(
#         SERVICE_ACCOUNT_FILE, scopes=SCOPES)

#     service = build('calendar', 'v3', credentials=credentials)

#     start = date_time.isoformat()
#     end = (date_time + datetime.timedelta(minutes=duration_minutes)).isoformat()

#     event = {
#         'summary': f'Interview with {name}',
#         'description': f'Interview with {name} for the open position.',
#         'start': {'dateTime': start, 'timeZone': 'Asia/Kolkata'},
#         'end': {'dateTime': end, 'timeZone': 'Asia/Kolkata'},
#         'attendees': [{'email': email}],
#         'conferenceData': {
#             'createRequest': {
#                 'requestId': f"{name}-{email}".replace(" ", "_"),
#                 'conferenceSolutionKey': {'type': 'hangoutsMeet'}
#             }
#         }
#     }

#     created_event = service.events().insert(
#         calendarId='primary',
#         body=event,
#         conferenceDataVersion=1,
#         sendUpdates='all'
#     ).execute()

#     return created_event.get('hangoutLink')
# email_generator.py

from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'  # Ensure this file exists

def schedule_interview(email, name, date_str, time_str):
    try:
        print(f"Scheduling interview for {name} ({email}) at {date_str} {time_str}")

        # Convert date and time strings into RFC3339 datetime strings
        interview_date = datetime.datetime.strptime(date_str, "%Y/%m/%d")
        interview_time = datetime.datetime.strptime(time_str, "%H:%M").time()
        interview_start = datetime.datetime.combine(interview_date, interview_time)
        interview_end = interview_start + datetime.timedelta(minutes=30)

        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build("calendar", "v3", credentials=credentials)

        event = {
            'summary': f'Interview with {name}',
            'location': 'Online',
            'description': f'Interview for {name}. Email: {email}',
            'start': {
                'dateTime': interview_start.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': interview_end.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'attendees': [{'email': email}],
            'conferenceData': {
                'createRequest': {
                    'requestId': f"{email}-{int(datetime.datetime.now().timestamp())}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
        }

        created_event = service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1
        ).execute()

        meet_link = created_event.get('hangoutLink') or created_event.get('htmlLink')
        print("✅ Event created:", meet_link)
        return meet_link

    except Exception as e:
        print("❌ Failed to schedule interview:", e)
        raise
