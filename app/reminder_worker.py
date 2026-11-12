"""Optional SMTP reminder worker. Run periodically via Windows Task Scheduler or a hosting cron job.
No mail is sent without explicit user opt-in and SMTP configuration.
"""
from app.main import conn
from email.message import EmailMessage
from datetime import datetime, timezone
import os, time, smtplib, ssl

def send_reminders(dry_run=False):
    host=os.getenv('LAPENG_SMTP_HOST','').strip();sender=os.getenv('LAPENG_SMTP_FROM','').strip();user=os.getenv('LAPENG_SMTP_USER','');secret=os.getenv('LAPENG_SMTP_PASSWORD','')
    if not dry_run and (not host or not sender or not secret):
        print('SMTP not configured. No reminder emails sent.');return 0
    now=int(time.time());count=0
    with conn() as db:
        # Advisory task: one reminder per booking/recipient/window; opt-in only.
        data=db.execute("""SELECT b.id,b.starts_at,b.status,l.title, u.id recipient_id,u.email
             FROM service_bookings b JOIN listings l ON l.id=b.listing_id
             JOIN providers p ON p.id=b.provider_id JOIN users u ON (u.id=b.buyer_id OR u.id=p.owner_id)
             JOIN notification_preferences np ON np.user_id=u.id
             WHERE np.email_appointment_reminders=1 AND b.status='confirmed'
             AND b.starts_at>? AND b.starts_at<=? ORDER BY b.starts_at LIMIT 200""",(now,now+25*3600)).fetchall()
        for row in data:
            diff=row['starts_at']-now
            kind=('2h' if diff<=2*3600 else '24h')+':user:'+str(row['recipient_id'])
            if db.execute('SELECT 1 FROM booking_reminder_log WHERE booking_id=? AND reminder_kind=?',(row['id'],kind)).fetchone():continue
            when=datetime.fromtimestamp(row['starts_at'],timezone.utc).strftime('%d %B %Y at %H:%M UTC')
            if dry_run:
                count+=1;continue
            msg=EmailMessage();msg['Subject']='LAPENG appointment reminder';msg['From']=sender;msg['To']=row['email']
            msg.set_content(f'Your LAPENG appointment for {row["title"]} starts {when}. Open LAPENG to review the confirmed booking. Do not reply with account credentials.')
            try:
                with smtplib.SMTP(host,int(os.getenv('LAPENG_SMTP_PORT','587')),timeout=12) as smtp:
                    smtp.starttls(context=ssl.create_default_context());smtp.login(user,secret);smtp.send_message(msg)
                db.execute('INSERT OR IGNORE INTO booking_reminder_log(booking_id,reminder_kind,created) VALUES(?,?,?)',(row['id'],kind,now))
                db.commit();count+=1
            except (OSError,smtplib.SMTPException) as ex:
                print('Reminder send failed for booking',row['id'],type(ex).__name__)
    print(('Eligible reminders' if dry_run else 'Sent reminders'),count);return count
if __name__=='__main__':
    import sys
    send_reminders('--dry-run' in sys.argv)
