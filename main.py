import os
import re
import smtplib
import pandas as pd
import random
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Google API imports
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import BatchHttpRequest


# ===== FIXED NOTIFY EMAILS =====
NOTIFY_EMAILS = [email.strip()
                 for email in os.environ.get("NOTIFY_EMAILS", "").split(",")
                 if email.strip()
                ]


# ===== CONFIG =====
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")
TIMEZONE = os.environ.get("TZ", "Africa/Lagos")

# ===== TODAY & TOMORROW =====
now = dt.datetime.now()
today_date = now.date()
tomorrow_date = today_date + dt.timedelta(days=1)

# ===== BIRTHDAY FILE =====
birthday_info = pd.read_csv("Birthdays.csv")

# ===== GOOGLE CALENDAR SETUP =====
creds = Credentials(
    None,
    refresh_token=GOOGLE_REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    scopes=["https://www.googleapis.com/auth/calendar"]
)
service = build("calendar", "v3", credentials=creds)

# ===== LOAD LETTER TEMPLATES =====
subject = [
    "Guess whose special day it is today? 🎉",
    "A special birthday note just for you, [Name] 💌",
    "🥳 It’s your birthday, [Name]! Let’s celebrate!"
]

letter_templates = [
    {
        "Subject": subject[i-1],
        "file": open(f"letter_templates/letter_{i}.txt", encoding="utf-8").read()
    }
    for i in range(1, 4)
]

# ===== EMAIL HELPER =====
def send_email(connection, subject, body, to_email, from_email=EMAIL_ADDRESS, from_name="TACSFONOAU Publicity Team"):
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Auto-Submitted"] = "auto-generated"

    html_body = body.replace("\n", "<br>")

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8"))

    connection.sendmail(from_email, to_email, msg.as_string())

def generate_event_id(firstname, lastname, date):
    # 1. Create a raw string (removed hyphens and "birthday" prefix to keep it short)
    # We use 'bd' as a prefix to ensure it starts with a letter
    raw = f"bd{firstname}{lastname}{date.year}"
    
    # 2. Base32hex filtering: Only allow 0-9 and a-v
    # This removes hyphens, spaces, and letters w, x, y, z
    clean_id = re.sub(r"[^a-v0-9]", "", raw.lower())
    
    # 3. Google IDs must be at least 5 characters
    if len(clean_id) < 5:
        clean_id = clean_id.ljust(5, '0')
        
    return clean_id


def event_exists(service, event_id):
    try:
        service.events().get(calendarId="primary", eventId=event_id).execute()
        return True
    except:
        return False



# ===== FILTER DATA =====
today_mask = (
    (birthday_info["day"] == today_date.day) &
    (birthday_info["month"] == today_date.month)
)

tomorrow_mask = (
    (birthday_info["day"] == tomorrow_date.day) &
    (birthday_info["month"] == tomorrow_date.month)
)

todays_birthdays_df = birthday_info[today_mask]
tomorrow_birthdays_df = birthday_info[tomorrow_mask]


# ===== MAIN =====
todays_birthdays = []

with smtplib.SMTP("smtp.gmail.com", 587) as connection:
    connection.starttls()
    connection.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)

    def callback(request_id, response, exception):
        if exception is not None:
            print(f"Error: {exception}")
        else:
            print(f"Event created/updated successfully! ID: {request_id}")

    batch = BatchHttpRequest(
        batch_uri="https://www.googleapis.com/batch/calendar/v3",
        callback=callback
    )

    # =========================
    # 🎉 TODAY'S BIRTHDAYS (EMAIL ONLY)
    # =========================
    for row in todays_birthdays_df.itertuples(index=False):
        firstname = row.firstname
        lastname = row.lastname
        bd_email = row.email
        bd_number = row.number

        chosen_template = random.choice(letter_templates)
        message = chosen_template["file"].replace("[Name]", firstname)
        subject_line = chosen_template["Subject"].replace("[Name]", firstname)

        if row.gender == "Male":
            message = message.replace("[Brother/Sister]", "Brother")
        else:
            message = message.replace("[Brother/Sister]", "Sister")

        send_email(connection, subject_line, message, bd_email)

        todays_birthdays.append(f"- {lastname} {firstname} ({bd_email}) {bd_number}")

    # =========================
    # 📅 TOMORROW'S BIRTHDAYS (CALENDAR EVENTS)
    # =========================
    BIRTHDAY_CALENDAR_ID = os.environ.get("BIRTHDAY_CALENDAR_ID")
    for row in tomorrow_birthdays_df.itertuples(index=False):
        firstname = row.firstname
        lastname = row.lastname
        event_id = generate_event_id(firstname, lastname, tomorrow_date)
        event = {
            "id": event_id,
            "summary": f"🎂 {firstname} {lastname}'s Birthday",
            "description": f"Birthday of {firstname} {lastname}.",
            "start": {"dateTime": f"{tomorrow_date}T08:00:00", "timeZone": TIMEZONE},
            "end": {"dateTime": f"{tomorrow_date}T09:00:00", "timeZone": TIMEZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 840}  # 6PM today
                ],
            },
        }

        # ✅ INSERT OR UPDATE (prevents duplicates forever)
        if event_exists(service, event_id):
            batch.add(
                service.events().update(
                    calendarId= BIRTHDAY_CALENDAR_ID,
                    eventId=event_id,
                    body=event
                )
            )
        else:
            batch.add(
                service.events().insert(
                    calendarId= BIRTHDAY_CALENDAR_ID,
                    body=event
                )
            )


    # ===== EXECUTE CALENDAR BATCH =====
    batch.execute()

    # =========================
    # 📩 MORNING REPORT
    # =========================
    if todays_birthdays:
        report_message = "Good morning! 🎉\n\nHere are today's birthdays:\n\n"
        report_message += "\n".join(todays_birthdays)
        report_message += "\n\nTomorrow's birthdays have been scheduled with Google Calendar notifications (7PM today, 7AM & 8AM tomorrow)."

        for notify in NOTIFY_EMAILS:
            send_email(
                connection,
                subject=f"🎂 Birthday Report – {today_date.strftime('%B %d, %Y')}",
                body=report_message,
                to_email=notify,
                from_name="TacsfonOAU Family Bot 🤖"
            )
