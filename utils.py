from models import User, Class, Event, Message, Notification, CourseResource, StudyGroup, Resource, PeerReview, StudyMeeting
from app import db
from datetime import datetime, timedelta
import requests
from icalendar import Calendar
import logging
import re
from functools import wraps
from flask import redirect, url_for, flash, session, current_app
import random
import pytz

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
            
        user = db.session.get(User, session['user_id'])
        if not user:
            session.clear()
            flash('Session expired. Please log in again.', 'warning')
            return redirect(url_for('auth.login'))
            
        return f(*args, **kwargs)
    return decorated_function

def parse_ical_data(ical_data):
    cal = Calendar.from_ical(ical_data)
    events = []

    for component in cal.walk():
        if component.name == "VEVENT":
            event_title = str(component.get('summary', ''))
            event_date = component.get('dtstart').dt  # This returns a datetime object
            event_description = str(component.get('description', ''))

            # Append parsed event to list of events
            events.append({
                'title': event_title,
                'date': event_date,
                'description': event_description
            })

    return events

def fetch_canvas_events(canvas_url, user):
    try:
        response = requests.get(canvas_url)
        if response.status_code == 200:
            events = parse_ical_data(response.content)
            process_canvas_events(events, user)
            return True
    except Exception as e:
        logging.error(f"Error fetching Canvas events: {str(e)}")
    return False

def process_canvas_events(events, user):
    for event_data in events:
        existing_event = Event.query.filter_by(
            title=event_data['title'],
            date=event_data['date'],
            user_id=user.id
        ).first()
        
        if not existing_event:
            event = Event(
                title=event_data['title'],
                description=event_data.get('description', ''),
                date=event_data['date'],
                user_id=user.id
            )
            db.session.add(event)
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error processing Canvas events: {str(e)}")

def extract_course_name(text):
    """
    Extract valid course codes while filtering out non-course items.
    Valid formats: ABC-123, ABCD-123
    """
    if not text:
        return None
        
    logging.debug(f"Attempting to extract course name from: {text}")

    # Try to find course name in brackets [COURSE-123]
    bracket_match = re.search(r'\[(.*?)\]', text)
    if bracket_match:
        course_text = bracket_match.group(1).strip()
    else:
        course_text = text.strip()

    # Match course pattern: 2-4 letters, dash, 3-4 digits, optional letter
    match = re.search(r'([A-Z]{2,4})-(\d{3,4}[A-Z]?)', course_text.upper())
    
    if match:
        course_name = match.group(0)
        logging.debug(f"Found potential course name: {course_name}")
        return course_name
        
    logging.debug("No valid course code found")
    return None

def fetch_canvas_courses(ical_url, user):
    if not ical_url:
        return False
        
    try:
        logging.info(f"Fetching Canvas calendar for user {user.id}")
        response = requests.get(ical_url)
        
        if response.status_code != 200:
            logging.error(f"Canvas URL returned {response.status_code}")
            return False
        
        # Parse the calendar data
        cal = Calendar.from_ical(response.content)
        course_names = set()
        
        # First pass: collect unique course codes
        for component in cal.walk():
            if component.name == "VEVENT":
                summary = str(component.get('summary', 'No Title'))
                description = str(component.get('description', ''))
                
                # Try to find course name in various places
                course_name = None
                
                # Check description first (usually more reliable)
                if 'Course:' in description:
                    course_section = description.split('Course:')[1].split('\n')[0].strip()
                    course_name = extract_course_name(course_section)
                
                # If not found in description, try summary
                if not course_name:
                    match = re.search(r'\[(.*?)\]', summary)
                    if match:
                        course_name = match.group(1).strip()
                
                if course_name:
                    course_names.add(course_name)
        
        if not course_names:
            logging.warning("No valid courses found in calendar")
            return False
            
        # Create or update classes
        with db.session.no_autoflush:
            for course_name in course_names:
                existing_class = Class.query.filter_by(name=course_name).first()
                if existing_class:
                    if user not in existing_class.students:
                        existing_class.students.append(user)
                else:
                    new_class = Class(
                        name=course_name,
                        color=f"#{random.randint(0, 0xFFFFFF):06x}"
                    )
                    db.session.add(new_class)
                    new_class.students.append(user)
        
        db.session.commit()
        return True
        
    except Exception as e:
        logging.error(f"Canvas import failed: {str(e)}", exc_info=True)
        db.session.rollback()
        return False

def extract_course_names(ical_data):
    cal = Calendar.from_ical(ical_data)
    courses = set()
    for component in cal.walk():
        if component.name == "VEVENT":
            summary = str(component.get('summary', ''))
            course_name = extract_course_name(summary)
            if course_name:
                courses.add(course_name)
    return courses

def get_canvas_events(canvas_ical_url=None):
    # Set the target time zone
    target_tz = pytz.timezone('America/Phoenix')  # Adjust for your local time zone

    if not canvas_ical_url:
        user_id = session.get('user_id')
        if not user_id:
            return []
        user = User.query.get(user_id)
        if not user or not user.canvas_ical_url:
            return []

        canvas_ical_url = user.canvas_ical_url

    try:
        response = requests.get(canvas_ical_url)
        response.raise_for_status()
        calendar = Calendar(response.text)

        canvas_events = []
        for event in calendar.events:
            if event.begin:
                # Convert the event time to the target time zone
                event_time = event.begin.datetime
                local_event_time = event_time.astimezone(target_tz).isoformat()
                canvas_events.append({
                    "title": event.name,
                    "start": local_event_time,
                    "description": event.description or "",
                    "color": "#FF5733"
                })

        return canvas_events
    except requests.RequestException as e:
        print(f"Error fetching Canvas events: {e}")
        return []

def create_notification(user_id, message, notification_type='general'):
    notification = Notification(
        user_id=user_id,
        message=message,
        type=notification_type
    )
    db.session.add(notification)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating notification: {str(e)}")

def allowed_file(filename):
    # Define allowed file extensions
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS