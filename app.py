from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
import requests
from icalendar import Calendar
import logging
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
import random
from functools import wraps
import secrets
from sqlalchemy import inspect
from werkzeug.utils import secure_filename
import re

# Load environment variables from .env file
load_dotenv()

# Initialize the Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))
csrf = CSRFProtect(app)

# Configure the SQLite database URI for SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///calendar.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the SQLAlchemy database object
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Association table to establish many-to-many relationship between User and Class
user_classes = db.Table('user_classes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('class_id', db.Integer, db.ForeignKey('class.id'), primary_key=True)
)

# Add this near your other model definitions
friends = db.Table('friends',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('friend_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    canvas_ical_url = db.Column(db.String(500))
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    study_reminders = db.Column(db.Boolean, default=True, nullable=False)
    group_notifications = db.Column(db.Boolean, default=True, nullable=False)
    theme = db.Column(db.String(20), default='light', nullable=False)
    
    # Relationships
    classes = db.relationship(
        'Class',
        secondary='user_classes',
        back_populates='students'
    )
    events = db.relationship('Event', back_populates='user', lazy=True)
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', 
                                  back_populates='sender')
    received_messages = db.relationship('Message', foreign_keys='Message.recipient_id', 
                                      back_populates='recipient')
    friends = db.relationship('User', 
        secondary=friends,
        primaryjoin=(friends.c.user_id == id),
        secondaryjoin=(friends.c.friend_id == id),
        backref=db.backref('friend_of', lazy='dynamic'),
        lazy='dynamic'
    )

    def __repr__(self):
        return f'<User {self.username}>'

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), default="#000000")
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Fix relationships
    students = db.relationship(
        'User',
        secondary='user_classes',
        back_populates='classes',
        overlaps="enrolled_students"
    )
    
    # Update events relationship to use back_populates instead of backref
    events = db.relationship('Event', back_populates='class_', lazy=True)

    def __repr__(self):
        return f'<Class {self.name}>'

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(100))
    event_type = db.Column(db.String(50), default='assignment')
    status = db.Column(db.String(20), default='pending')
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'))
    
    user = db.relationship('User', back_populates='events')
    class_ = db.relationship('Class', back_populates='events')

    def __repr__(self):
        return f'<Event {self.title}>'

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    message_type = db.Column(db.String(50), default='message')
    status = db.Column(db.String(20), default='unread')
    
    sender = db.relationship('User', foreign_keys=[sender_id], back_populates='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], back_populates='received_messages')

    def __repr__(self):
        return f'<Message {self.id}>'

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    type = db.Column(db.String(50))  # e.g., 'message', 'resource', 'study_group'
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('notifications', lazy=True))

class CourseResource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    resource_type = db.Column(db.String(50))  # textbook, website, video, etc.
    url = db.Column(db.String(200))
    notes = db.Column(db.Text)
    shared_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'))

class StudyGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    max_members = db.Column(db.Integer, default=5)
    meeting_link = db.Column(db.String(500))
    description = db.Column(db.Text)
    members = db.relationship('User', secondary='study_group_members')

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(500))
    file_path = db.Column(db.String(500))
    type = db.Column(db.String(50))  # pdf, video, link, note
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    likes = db.Column(db.Integer, default=0)
    downloads = db.Column(db.Integer, default=0)

# Association Tables
study_group_members = db.Table('study_group_members',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('study_group.id'), primary_key=True)
)

meeting_attendees = db.Table('meeting_attendees',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('meeting_id', db.Integer, db.ForeignKey('study_meeting.id'), primary_key=True)
)

resource_likes = db.Table('resource_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('resource_id', db.Integer, db.ForeignKey('resource.id'), primary_key=True)
)

class PeerReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewee_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'))
    rating = db.Column(db.Integer)  # 1-5 rating
    feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    helpfulness_score = db.Column(db.Integer, default=0)

class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    description = db.Column(db.Text)
    icon = db.Column(db.String(50))
    requirement = db.Column(db.String(200))
    points = db.Column(db.Integer)
    level = db.Column(db.Integer)  # Bronze: 1, Silver: 2, Gold: 3

class UserBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    badge_id = db.Column(db.Integer, db.ForeignKey('badge.id'))
    earned_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    total_points = db.Column(db.Integer, default=0)
    current_level = db.Column(db.Integer, default=1)
    study_streak = db.Column(db.Integer, default=0)
    resources_shared = db.Column(db.Integer, default=0)
    reviews_given = db.Column(db.Integer, default=0)
    helpful_reviews = db.Column(db.Integer, default=0)

class StudyMeeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('study_group.id'))
    date = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer)  # in minutes
    location = db.Column(db.String(200))
    meeting_link = db.Column(db.String(500))
    notes = db.Column(db.Text)
    attendees = db.relationship('User', secondary='meeting_attendees')

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

logging.basicConfig(level=logging.INFO)

def fetch_canvas_events(ical_url, user):
    try:
        response = requests.get(ical_url)
        if response.status_code != 200:
            logging.error(f"Failed to fetch Canvas calendar: {response.status_code}")
            return False

        cal = Calendar.from_ical(response.content)
        events_added = 0
        course_names = set()

        for component in cal.walk():
            if component.name == "VEVENT":
                summary = str(component.get('summary', ''))
                description = str(component.get('description', ''))
                
                # Extract course name from summary (usually in brackets [Course Name])
                course_name = None
                match = re.search(r'\[(.*?)\]', summary)
                if match:
                    course_name = match.group(1).strip()
                elif '[' in description and ']' in description:
                    # Try to find course name in description if not in summary
                    match = re.search(r'\[(.*?)\]', description)
                    if match:
                        course_name = match.group(1).strip()

                if not course_name:
                    continue

                # Add course name to set for later processing
                course_names.add(course_name)

                # Get or create class
                class_ = Class.query.filter_by(name=course_name).first()
                if not class_:
                    class_ = Class(
                        name=course_name,
                        color="#" + ''.join(random.choices('0123456789ABCDEF', k=6))
                    )
                    db.session.add(class_)
                    if class_ not in user.classes:
                        user.classes.append(class_)

                # Process event
                start_date = component.get('dtstart').dt
                if isinstance(start_date, datetime):
                    event_date = start_date
                else:
                    # If it's just a date, convert to datetime
                    event_date = datetime.combine(start_date, datetime.min.time())
                
                # Check for existing event to avoid duplicates
                existing_event = Event.query.filter_by(
                    user_id=user.id,
                    title=summary,
                    date=event_date,
                    class_id=class_.id if class_ else None
                ).first()

                if not existing_event:
                    new_event = Event(
                        title=summary,
                        description=description,
                        date=event_date,
                        user_id=user.id,
                        class_id=class_.id if class_ else None,
                        location=str(component.get('location', '')),
                        event_type='assignment' if 'assignment' in summary.lower() else 'canvas_event'
                    )
                    db.session.add(new_event)
                    events_added += 1

        if events_added > 0:
            db.session.commit()
            logging.info(f"Successfully imported {events_added} events for user {user.id}")
            return True
            
        return False

    except Exception as e:
        logging.error(f"Error in fetch_canvas_events: {str(e)}")
        db.session.rollback()
        return False

def process_canvas_events(events, user, class_name=None):
    """Process Canvas calendar events"""
    try:
        events_processed = 0
        for event in events:
            # Extract event details
            title = event.get('title', '')
            date = event.get('date', datetime.now())
            description = event.get('description', '')
            
            # Create or get class
            class_obj = None
            if class_name:
                class_obj = Class.query.filter_by(name=class_name).first()
                if not class_obj:
                    class_obj = Class(name=class_name)
                    db.session.add(class_obj)
                    user.classes.append(class_obj)
            
            # Create event
            new_event = Event(
                title=title,
                description=description,
                date=date,
                class_id=class_obj.id if class_obj else None,
                user_id=user.id,
                event_type='assignment'
            )
            
            db.session.add(new_event)
            events_processed += 1
        
        db.session.commit()
        return events_processed
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error processing Canvas events: {str(e)}")
        raise

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
        cal = Calendar.from_ical(response.content)  # Using content instead of text
        course_names = set()
        
        # First pass: collect unique course codes
        for component in cal.walk():
            if component.name == "VEVENT":
                summary = str(component.get('summary', 'No Title'))
                description = str(component.get('description', ''))
                
                logging.debug(f"Processing event: {summary}")
                
                # Try to find course name in various places
                course_name = None
                
                # Check description first (usually more reliable)
                if 'Course:' in description:
                    course_section = description.split('Course:')[1].split('\n')[0].strip()
                    course_name = extract_course_name(course_section)
                    logging.debug(f"Extracted from description: {course_name}")
                
                # If not found in description, try summary
                if not course_name:
                    course_name = extract_course_name(summary)
                    logging.debug(f"Extracted from summary: {course_name}")
                
                if course_name:
                    logging.info(f"Found valid course: {course_name}")
                    course_names.add(course_name)
        
        if not course_names:
            logging.warning("No valid courses found in calendar")
            return False
            
        logging.info(f"Valid courses found: {course_names}")
        
        # Create or update classes
        with db.session.no_autoflush:
            for course_name in course_names:
                existing_class = Class.query.filter_by(name=course_name).first()
                if existing_class:
                    if user not in existing_class.students:
                        existing_class.students.append(user)
                        logging.info(f"Added user to existing class: {course_name}")
                else:
                    new_class = Class(
                        name=course_name,
                        color=f"#{random.randint(0, 0xFFFFFF):06x}"
                    )
                    db.session.add(new_class)
                    new_class.students.append(user)
                    logging.info(f"Created new class: {course_name}")
        
        db.session.commit()
        return True
        
    except Exception as e:
        logging.error(f"Canvas import failed: {str(e)}", exc_info=True)
        db.session.rollback()
        return False

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

# Add this before any routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
            
        user = db.session.get(User, session['user_id'])
        if not user:
            session.clear()
            flash('Session expired. Please log in again.', 'warning')
            return redirect(url_for('login'))
            
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('calendar'))
            
        flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Generate password reset token
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.now() + timedelta(hours=1)
            db.session.commit()
            
            # Send reset email (implement this based on your email setup)
            flash('Password reset instructions have been sent to your email.', 'info')
            return redirect(url_for('login'))
            
        flash('Email address not found.', 'error')
    
    return render_template('reset_password.html')

@app.route('/calendar')
@login_required
def calendar():
    try:
        user = db.session.get(User, session['user_id'])
        classes = user.classes
        events = Event.query.filter_by(user_id=user.id).all()
        
        # Get classmates for each class
        classmates_by_class = {}
        for class_obj in classes:
            classmates = [student for student in class_obj.students if student.id != user.id]
            classmates_by_class[class_obj.id] = classmates
        
        # Safely check for Canvas URL
        show_canvas_import = bool(getattr(user, 'canvas_ical_url', None))
        
        return render_template('calendar.html',
            user=user,
            classes=classes,
            events=events,
            show_canvas_import=show_canvas_import,
            classmates_by_class=classmates_by_class
        )
        
    except Exception as e:
        logging.error(f"Calendar error: {str(e)}")
        flash('An error occurred while loading your calendar.', 'error')
        return redirect(url_for('login'))

@app.route('/add_class', methods=['GET', 'POST'])
@login_required
def add_class():
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        class_color = request.form.get('color', '#000000')
        
        if not class_name:
            flash('Class name is required', 'error')
            return redirect(url_for('add_class'))
            
        try:
            user = db.session.get(User, session['user_id'])
            
            # Create new class
            new_class = Class(
                name=class_name,
                color=class_color
            )
            db.session.add(new_class)
            user.classes.append(new_class)
            db.session.commit()
            
            flash('Class added successfully!', 'success')
            return redirect(url_for('manage_classes'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error adding class: {str(e)}")
            flash('Error adding class. Please try again.', 'error')
            return redirect(url_for('add_class'))
            
    return render_template('add_class.html')


@app.route('/add_event', methods=['POST'])
@login_required
def add_event():
    data = request.get_json()
    if not data or 'title' not in data or 'date' not in data:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    try:
        event = Event(
            title=data['title'],
            description=data.get('description', ''),
            date=datetime.fromisoformat(data['date']),
            location=data.get('location', ''),
            event_type=data.get('event_type', 'assignment'),
            user_id=session['user_id'],
            class_id=data.get('class_id')
        )
        db.session.add(event)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Event added successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/match_peers')
def match_peers():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    matched_peers = {}

    # Find classmates by iterating over user's classes
    for class_ in user.classes:
        classmates = [student for student in class_.students if student.id != user.id]
        if classmates:
            matched_peers[class_.name] = classmates

    return render_template('match_peers.html', matched_peers=matched_peers)

@app.route('/connect_with_peer/<int:peer_id>', methods=['POST'])
@login_required
def connect_with_peer(peer_id):
    try:
        # Check if it's an AJAX request using the X-Requested-With header
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'message': 'Invalid request method'
            }), 400
            
        user = db.session.get(User, session['user_id'])
        peer = db.session.get(User, peer_id)
        
        if not peer:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 404
            
        # Check if they're already connected
        existing_connection = db.session.query(Message).filter(
            ((Message.sender_id == user.id) & (Message.recipient_id == peer_id) |
            (Message.sender_id == peer_id) & (Message.recipient_id == user.id)) &
            (Message.message_type == 'connection_request')
        ).first()
        
        if existing_connection:
            return jsonify({
                'success': False,
                'message': 'Connection request already exists'
            })
            
        # Create new connection request
        connection = Message(
            sender_id=user.id,
            recipient_id=peer_id,
            content=f"{user.username} wants to connect with you",
            message_type='connection_request',
            status='pending'
        )
        
        db.session.add(connection)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Connection request sent successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Connection error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'An error occurred while processing your request'
        }), 500

@app.route('/manage_classes', methods=['GET', 'POST'])
def manage_classes():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        # Handle class deletion
        class_id = request.form.get('class_id')
        if class_id:
            class_to_remove = Class.query.get(class_id)
            if class_to_remove and class_to_remove in user.classes:
                user.classes.remove(class_to_remove)
                db.session.commit()

    # Retrieve the user's current classes to display
    user_classes = user.classes
    return render_template('manage_classes.html', user_classes=user_classes)

@app.route('/messages')
@app.route('/messages/<int:recipient_id>', methods=['GET', 'POST'])
@login_required
def messages(recipient_id=None):
    user = db.session.get(User, session['user_id'])
    
    # Handle message sending (POST request)
    if request.method == 'POST' and recipient_id:
        content = request.form.get('content')
        if content:
            message = Message(
                sender_id=user.id,
                recipient_id=recipient_id,
                content=content,
                message_type='message',
                status='sent',
                timestamp=datetime.utcnow()
            )
            try:
                db.session.add(message)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logging.error(f"Error sending message: {str(e)}")
                flash('Failed to send message', 'error')
            return redirect(url_for('messages', recipient_id=recipient_id))
    
    # Get all friends
    friends = user.friends.all() if hasattr(user.friends, 'all') else user.friends
    
    # Get chat history if recipient_id is provided
    chat_messages = []
    selected_recipient = None
    if recipient_id:
        selected_recipient = db.session.get(User, recipient_id)
        if selected_recipient:
            chat_messages = Message.query.filter(
                Message.message_type == 'message',
                db.or_(
                    db.and_(Message.sender_id == user.id, Message.recipient_id == recipient_id),
                    db.and_(Message.sender_id == recipient_id, Message.recipient_id == user.id)
                )
            ).order_by(Message.timestamp.asc()).all()
    
    # Get pending connection requests
    connection_requests = Message.query.filter_by(
        recipient_id=user.id,
        message_type='connection_request',
        status='pending'
    ).all()

    return render_template('messages.html',
                         user=user,
                         friends=friends,
                         chat_messages=chat_messages,
                         selected_recipient=selected_recipient,
                         connection_requests=connection_requests)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user = db.session.get(User, session['user_id'])
    
    if request.method == 'POST':
        user.canvas_ical_url = request.form['canvas_ical_url']
        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating your profile.', 'danger')
            print(f"Error: {e}")  # For debugging
            
    return render_template('profile.html', user=user)

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Add this new route for automated scheduling
@app.route('/generate_schedule', methods=['POST'])
@login_required
def generate_schedule():
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d')
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d')
        
        # Add timezone info
        start_date = start_date.replace(hour=0, minute=0, second=0)
        end_date = end_date.replace(hour=23, minute=59, second=59)
        
        user = db.session.get(User, session['user_id'])
        class_obj = db.session.get(Class, class_id)
        
        if not class_obj or class_obj not in user.classes:
            return jsonify({
                'success': False,
                'message': 'Invalid class selected'
            }), 400
        
        # First, delete any existing study sessions in this range
        Event.query.filter(
            Event.user_id == user.id,
            Event.class_id == class_id,
            Event.event_type == 'study_session',
            Event.date.between(start_date, end_date)
        ).delete()
        
        # Get assignments in date range
        assignments = Event.query.filter(
            Event.user_id == user.id,
            Event.class_id == class_id,
            Event.event_type == 'assignment',
            Event.date.between(start_date, end_date)
        ).order_by(Event.date).all()
        
        if not assignments:
            return jsonify({
                'success': False,
                'message': 'No assignments found in selected date range'
            }), 404
        
        study_sessions = []
        current_time = datetime.now()
        
        for assignment in assignments:
            # Create study sessions before each assignment
            for days_before in [5, 3, 1]:
                study_date = assignment.date - timedelta(days=days_before)
                study_date = study_date.replace(hour=14, minute=0, second=0)  # Set to 2 PM
                
                # Skip if study date is in the past or outside range
                if study_date < current_time or study_date < start_date or study_date > end_date:
                    continue
                
                study_session = Event(
                    title=f"Study Session for {assignment.title}",
                    description=f"Study session {days_before} days before {assignment.title}",
                    date=study_date,
                    user_id=user.id,
                    class_id=class_id,
                    event_type='study_session',
                    location='Study Location TBD'
                )
                
                db.session.add(study_session)
                study_sessions.append({
                    'title': study_session.title,
                    'date': study_date.strftime('%Y-%m-%d %H:%M:%S'),
                    'type': 'study_session'
                })
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Created {len(study_sessions)} study sessions',
            'study_sessions': study_sessions
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error generating study schedule: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'An error occurred while generating the study schedule'
        }), 500

# Add new routes for enhanced functionality
@app.route('/generate_smart_schedule', methods=['POST'])
@login_required
def generate_smart_schedule():
    try:
        user = db.session.get(User, session['user_id'])
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 400
            
        # Check if user has any classes
        if not user.classes:
            return jsonify({
                'success': False,
                'message': 'No classes found. Please add classes first.'
            }), 400  # Return 400 instead of 404
            
        now = datetime.now()
        end_date = now + timedelta(days=30)
        
        # Get all assignments for the next 30 days
        assignments = Event.query.filter(
            Event.user_id == user.id,
            Event.event_type == 'assignment',
            Event.date >= now,
            Event.date <= end_date
        ).order_by(Event.date).all()
        
        if not assignments:
            return jsonify({
                'success': False,
                'message': 'No upcoming assignments found'
            }), 400  # Return 400 instead of 404
        
        # Delete existing study sessions
        Event.query.filter(
            Event.user_id == user.id,
            Event.event_type == 'study_session',
            Event.date >= now
        ).delete()
        
        study_sessions = []
        for assignment in assignments:
            # Create study sessions before each assignment
            for days_before in [5, 3, 1]:
                study_date = assignment.date - timedelta(days=days_before)
                
                # Skip if study date is in the past
                if study_date < now:
                    continue
                
                study_session = Event(
                    title=f"Study for {assignment.title}",
                    description=f"Study session {days_before} days before {assignment.title}",
                    date=study_date,
                    user_id=user.id,
                    class_id=assignment.class_id,
                    event_type='study_session'
                )
                db.session.add(study_session)
                study_sessions.append({
                    'title': study_session.title,
                    'date': study_date.strftime('%Y-%m-%d'),
                    'type': 'study_session'
                })
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Created {len(study_sessions)} study sessions',
            'study_sessions': study_sessions
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error generating smart schedule: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'Error generating study schedule'
        }), 500

@app.route('/find_study_buddies')
def find_study_buddies():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    user = User.query.get(session['user_id'])
    study_buddies = []
    
    for class_ in user.classes:
        classmates = class_.enrolled_users
        for classmate in classmates:
            if classmate.id != user.id:
                study_buddies.append({
                    'id': classmate.id,
                    'username': classmate.username,
                    'class_name': class_.name
                })
    
    return jsonify({'study_buddies': study_buddies})

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    notifications = Notification.query.filter_by(
        user_id=session['user_id'],
        read=False
    ).order_by(Notification.created_at.desc()).all()
    
    return jsonify({
        'notifications': [{
            'id': n.id,
            'message': n.message,
            'type': n.type,
            'created_at': n.created_at.isoformat()
        } for n in notifications]
    })

@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    notification_ids = request.json.get('notification_ids', [])
    Notification.query.filter(
        Notification.id.in_(notification_ids),
        Notification.user_id == session['user_id']
    ).update({Notification.read: True}, synchronize_session=False)
    
    db.session.commit()
    return jsonify({'success': True})

# Add these configuration settings
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/share_resource', methods=['POST'])
def share_resource():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        print("Received resource upload request")  # Debug print
        
        if 'file' not in request.files:
            print("No file in request")  # Debug print
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        if file.filename == '':
            print("Empty filename")  # Debug print
            return jsonify({'error': 'No file selected'}), 400
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Create upload folder if it doesn't exist
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            # Save the file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            print(f"File saved to {file_path}")  # Debug print
            
            # Create resource record
            resource = CourseResource(
                title=request.form.get('title'),
                resource_type=request.form.get('type'),
                url=f'/static/uploads/{filename}',
                notes=request.form.get('notes'),
                shared_by=session['user_id'],
                class_id=request.form.get('class_id')
            )
            
            db.session.add(resource)
            db.session.commit()
            
            print(f"Resource created with ID {resource.id}")  # Debug print
            
            return jsonify({
                'success': True,
                'message': 'Resource uploaded successfully'
            })
        else:
            print(f"Invalid file type: {file.filename}")  # Debug print
            return jsonify({'error': 'File type not allowed'}), 400
            
    except Exception as e:
        db.session.rollback()
        print(f"Upload error: {str(e)}")  # Debug print
        return jsonify({'error': 'Failed to upload resource'}), 500

@app.route('/calendar/events')
def get_calendar_events():
    if 'user_id' not in session:
        return jsonify([])
    
    try:
        user = db.session.get(User, session['user_id'])
        events = Event.query.filter_by(user_id=user.id).all()
        
        event_list = []
        for event in events:
            event_color = event.class_.color if event.class_ else '#808080'
            if event.event_type == 'study_session':
                event_color = '#4CAF50'  # Green for study sessions
                
            event_list.append({
                'id': event.id,
                'title': event.title,
                'start': event.date.isoformat(),
                'end': (event.date + timedelta(hours=1)).isoformat(),
                'description': event.description,
                'type': event.event_type,
                'backgroundColor': event_color,
                'className': event.event_type
            })
        
        return jsonify(event_list)
        
    except Exception as e:
        logging.error(f"Error fetching calendar events: {str(e)}")
        return jsonify([])

@app.route('/class/<int:class_id>/resources')
def class_resources(class_id):
    """View resources for a specific class"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    class_ = db.session.get(Class, class_id)
    resources = CourseResource.query.filter_by(class_id=class_id).all()
    
    return render_template('class_resources.html', class_=class_, resources=resources)

def import_canvas_assignments():
    # Canvas API configuration
    CANVAS_URL = 'your_canvas_url'
    CANVAS_TOKEN = 'your_canvas_token'
    
    canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)
    
    try:
        user = canvas.get_current_user()
        courses = user.get_courses()
        
        for course in courses:
            assignments = course.get_assignments()
            for assignment in assignments:
                # Check if assignment already exists
                existing = Event.query.filter_by(
                    canvas_id=assignment.id
                ).first()
                
                if not existing:
                    event = Event(
                        title=assignment.name,
                        description=assignment.description,
                        date=assignment.due_at,
                        event_type='assignment',
                        canvas_id=assignment.id,
                        class_id=get_class_id(course.name)  # You'll need to implement this mapping
                    )
                    db.session.add(event)
        
        db.session.commit()
        return True
    except Exception as e:
        print(f"Canvas import error: {e}")
        return False

@app.route('/import_canvas', methods=['POST'])
def import_canvas():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    # Your Canvas import logic here
    return jsonify({'success': True})

@app.route('/study_groups/<int:class_id>')
def study_groups(class_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    class_ = db.session.get(Class, class_id)
    groups = StudyGroup.query.filter_by(class_id=class_id).all()
    return render_template('study_groups.html', class_=class_, groups=groups)

@app.route('/create_study_group', methods=['POST'])
def create_study_group():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.json
    group = StudyGroup(
        name=data['name'],
        class_id=data['class_id'],
        created_by=session['user_id'],
        max_members=data.get('max_members', 5),
        description=data.get('description', ''),
        meeting_link=data.get('meeting_link', '')
    )
    db.session.add(group)
    group.members.append(User.query.get(session['user_id']))
    db.session.commit()
    return jsonify({'success': True, 'group_id': group.id})

def predict_optimal_study_times(sessions):
    if not sessions:
        return []
    
    # Prepare data for linear regression
    X = [[s.start_time.hour, s.start_time.weekday()] for s in sessions]
    y = [s.productivity_rating for s in sessions]
    
    model = LinearRegression()
    model.fit(X, y)
    
    # Predict productivity for all possible times
    predictions = []
    for day in range(7):
        for hour in range(24):
            score = model.predict([[hour, day]])[0]
            predictions.append({
                'day': day,
                'hour': hour,
                'predicted_productivity': score
            })
    
    return sorted(predictions, key=lambda x: x['predicted_productivity'], reverse=True)[:5]


def create_notification(user_id, message, notification_type):
    notification = Notification(
        user_id=user_id,
        message=message,
        type=notification_type
    )
    db.session.add(notification)
    db.session.commit()
    return notification

def notify_study_group(group_id, message, exclude_user_id=None):
    group = StudyGroup.query.get(group_id)
    for member in group.members:
        if member.id != exclude_user_id:
            create_notification(
                user_id=member.id,
                message=message,
                notification_type='study_group'
            )

@app.route('/api/messages/send', methods=['POST'])
def send_message():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.json
    message = Message(
        sender_id=session['user_id'],
        recipient_id=data['recipient_id'],
        content=data['content']
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Create notification for recipient
    create_notification(
        user_id=data['recipient_id'],
        message=f"New message from {User.query.get(session['user_id']).username}",
        notification_type='message'
    )
    
    return jsonify({'success': True, 'message_id': message.id})

@app.route('/resources')
def resources():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Get filter parameters
    class_id = request.args.get('class_id')
    resource_type = request.args.get('type')
    sort = request.args.get('sort', 'newest')
    
    # Base query
    query = CourseResource.query.join(Class).filter(
        Class.students.any(id=session['user_id'])
    )
    
    # Apply filters
    if class_id:
        query = query.filter(CourseResource.class_id == class_id)
    if resource_type:
        query = query.filter(CourseResource.resource_type == resource_type)
    
    # Apply sorting
    if sort == 'oldest':
        query = query.order_by(CourseResource.created_at.asc())
    elif sort == 'title':
        query = query.order_by(CourseResource.title.asc())
    else:  # newest
        query = query.order_by(CourseResource.created_at.desc())
    
    resources = query.all()
    
    # Get user's classes for the filter dropdown
    user = User.query.get(session['user_id'])
    user_classes = user.classes
    
    return render_template('resources.html', 
                         resources=resources,
                         classes=user_classes)

# Add this after your app initialization but before your routes
@app.context_processor
def utility_processor():
    return {
        'current_user': db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    }

@app.route('/home')
@login_required
def home():
    user = db.session.get(User, session['user_id'])
    classes = user.classes
    
    # Get matched peers for each class
    matched_peers = {}
    for class_ in classes:
        # Get all students in the class except the current user
        classmates = [student for student in class_.students 
                     if student.id != user.id]
        if classmates:
            matched_peers[class_.name] = classmates
    
    return render_template('home.html', 
                         user=user,
                         classes=classes, 
                         matched_peers=matched_peers)

@app.route('/import_canvas_events', methods=['POST'])
@login_required
def import_canvas_events():
    try:
        user = db.session.get(User, session['user_id'])
        data = request.get_json(silent=True) or {}
        canvas_url = data.get('canvas_url')
        
        if not canvas_url and not user.canvas_ical_url:
            return jsonify({
                'success': False,
                'message': 'No Canvas URL provided'
            }), 400
            
        url_to_use = canvas_url or user.canvas_ical_url
            
        if not url_to_use.startswith(('http://', 'https://')):
            return jsonify({
                'success': False,
                'message': 'Invalid URL format'
            }), 400
            
        if 'canvas' not in url_to_use.lower():
            return jsonify({
                'success': False,
                'message': 'Not a valid Canvas URL'
            }), 400
            
        response = requests.get(url_to_use)
        if response.status_code != 200:
            return jsonify({
                'success': False,
                'message': f'Failed to fetch Canvas calendar: {response.status_code}'
            }), 400
            
        # Parse calendar data
        try:
            # Convert calendar text to events
            events = []
            calendar_lines = response.text.strip().split('\n')
            current_event = {}
            
            for line in calendar_lines:
                line = line.strip()
                if line == 'BEGIN:VEVENT':
                    current_event = {}
                elif line == 'END:VEVENT':
                    if current_event:
                        events.append(current_event)
                elif ':' in line:
                    key, value = line.split(':', 1)
                    if key == 'SUMMARY':
                        current_event['title'] = value
                    elif key == 'DTSTART':
                        # Convert to datetime
                        try:
                            year = int(value[0:4])
                            month = int(value[4:6])
                            day = int(value[6:8])
                            hour = int(value[9:11])
                            minute = int(value[11:13])
                            current_event['date'] = datetime(year, month, day, hour, minute)
                        except:
                            current_event['date'] = datetime.now()
            
            # Process the events
            events_processed = process_canvas_events(events, user)
            
            return jsonify({
                'success': True,
                'message': f'Successfully imported {events_processed} events'
            })
            
        except Exception as e:
            logging.error(f"Calendar parsing error: {str(e)}")
            return jsonify({
                'success': False,
                'message': 'Invalid calendar format'
            }), 400
            
    except Exception as e:
        logging.error(f"Error in import_canvas_events: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error processing Canvas events'
        }), 400

# Add migration commands
def init_db():
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Add event_type column if it doesn't exist
        inspector = inspect(db.engine)
        if 'event' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('event')]
            if 'event_type' not in columns:
                db.engine.execute('ALTER TABLE event ADD COLUMN event_type VARCHAR(50) DEFAULT "assignment"')
        
        db.session.commit()

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        canvas_ical_url = request.form.get('canvas_ical_url')
        
        # Validation
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('signup.html')
            
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('signup.html')
        
        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            password=hashed_password,
            canvas_ical_url=canvas_ical_url if canvas_ical_url else None,
            email_notifications=True,
            study_reminders=True,
            group_notifications=True,
            theme='light'
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # Import Canvas data if URL provided
            canvas_import_success = True
            if canvas_ical_url:
                # Import courses first
                courses_success = fetch_canvas_courses(canvas_ical_url, new_user)
                if courses_success:
                    # Then import events
                    events_success = fetch_canvas_events(canvas_ical_url, new_user)
                    if not events_success:
                        flash('Account created, but there was an issue importing Canvas events.', 'warning')
                        canvas_import_success = False
                else:
                    flash('Account created, but there was an issue importing Canvas courses.', 'warning')
                    canvas_import_success = False
            
            if canvas_import_success and canvas_ical_url:
                flash('Account created successfully! Canvas courses and events have been imported.', 'success')
            else:
                flash('Account created successfully! Please log in.', 'success')
                
            return redirect(url_for('login'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Signup error: {str(e)}")
            flash('An error occurred. Please try again.', 'error')
            
    return render_template('signup.html')

@app.route('/')
@app.route('/landing')
def landing():
    return render_template('landing.html')

@app.route('/get_student_schedule/<int:student_id>/<int:class_id>')
@login_required
def get_student_schedule(student_id, class_id):
    try:
        # Verify the requesting user is in the same class
        user = db.session.get(User, session['user_id'])
        class_obj = db.session.get(Class, class_id)
        
        if not class_obj or user not in class_obj.students:
            return jsonify({'error': 'Unauthorized'}), 403
            
        # Get the student's events for this class
        student_events = Event.query.filter_by(
            user_id=student_id,
            class_id=class_id
        ).all()
        
        return jsonify({
            'events': [event.id for event in student_events]
        })
        
    except Exception as e:
        logging.error(f"Error getting student schedule: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/accept_connection/<int:request_id>', methods=['POST'])
@login_required
def accept_connection(request_id):
    try:
        connection_request = Message.query.filter_by(
            id=request_id,
            message_type='connection_request',
            status='pending'
        ).first()
        
        if not connection_request:
            return jsonify({
                'success': False,
                'message': 'Connection request not found'
            }), 404
            
        # Verify the current user is the recipient
        if connection_request.recipient_id != session['user_id']:
            return jsonify({
                'success': False,
                'message': 'Unauthorized'
            }), 403
            
        # Update request status
        connection_request.status = 'accepted'
        
        # Create a friendship record for both users
        sender = db.session.get(User, connection_request.sender_id)
        recipient = db.session.get(User, connection_request.recipient_id)
        
        sender.friends.append(recipient)
        recipient.friends.append(sender)
        
        # Create notification for sender
        notification = Notification(
            user_id=connection_request.sender_id,
            message=f"{recipient.username} accepted your connection request! You can now message each other.",
            type='connection_accepted'
        )
        
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Connection accepted'
        })
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Accept connection error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'An error occurred'
        }), 500

@app.route('/register_class', methods=['GET', 'POST'])
@login_required
def register_class():
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        class_color = request.form.get('class_color', '#000000')
        
        new_class = Class(
            name=class_name,
            color=class_color
        )
        
        try:
            db.session.add(new_class)
            # Add the current user to the class
            user = db.session.get(User, session['user_id'])
            user.classes.append(new_class)
            db.session.commit()
            flash('Class added successfully!', 'success')
            return redirect(url_for('manage_classes'))
        except Exception as e:
            db.session.rollback()
            flash('Error adding class. Please try again.', 'error')
            
    return render_template('register_class.html')

# Main entry point of the application
if __name__ == '__main__':
    init_db()  # Initialize database before running app
    app.run(debug=True)

