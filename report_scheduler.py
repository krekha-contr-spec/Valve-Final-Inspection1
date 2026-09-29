from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from report_generated import generate_daily_report
from database_manager import db_manager
import logging
import os
import yagmail  

scheduler = BackgroundScheduler()

def send_email_with_report(to_email, subject, body, attachment_path):
    try:
        yag = yagmail.SMTP(user="your_email@gmail.com", password="your_app_password")
        yag.send(to=to_email, subject=subject, contents=body, attachments=attachment_path)
        logging.info(f"Email sent to {to_email}")
    except Exception as e:
        logging.exception("Error sending email")

def daily_report_job():
    try:
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        date_from = datetime(yesterday.year, yesterday.month, yesterday.day)
        date_to = date_from + timedelta(days=1)

        df = db_manager.fetch_inspections(date_from, date_to)
        if df.empty:
            logging.info("No inspection data found for yesterday.")
            return

        out_path, summary = generate_daily_report(df, date_from, date_to, out_format="pdf")
        logging.info(f"Report generated: {out_path}")

        send_email_with_report(
            to_email="recipient_email@example.com",
            subject=f"Daily Inspection Report - {date_from.date()}",
            body="Please find attached the daily inspection report.",
            attachment_path=out_path
        )
    except Exception as e:
        logging.exception("[Daily Report Job Error]")

def start_scheduler(app):
    scheduler.add_job(
        daily_report_job,
        trigger='cron',
        hour=15, 
        minute=30,
        id='daily_report_job',
        replace_existing=True
    )
    scheduler.start()
    app.logger.info("Report scheduler started.")
