from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
import requests
from ics import Calendar
import re
import pytz
from flask_caching import Cache
from sqlalchemy import Table, Column, Integer, ForeignKey, desc
from sqlalchemy.orm import relationship
import random
import string
import re
from datetime import datetime
import logging
from icalendar import Calendar, Event

# Initialize the Flask app
app = Flask(__name__)

# Initialize the cache with Flask
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Configure the SQLite database URI for SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///calendar.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'

# Initialize the SQLAlchemy database object
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Association table to establish many-to-many relationship between User and Class
user_classes = Table('user_classes', db.Model.metadata,
    Column('user_id', Integer, ForeignKey('user.id'), primary_key=True),
    Column('class_id', Integer, ForeignKey('class.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    secret_username = db.Column(db.String(7), unique=True, nullable=False, default=lambda: ''.join(random.choices(string.ascii_letters + string.digits, k=7)))
    canvas_ical_url = db.Column(db.String(200))
    last_canvas_sync = db.Column(db.DateTime)

    # Relationships
    classes = db.relationship("Class", secondary=user_classes, back_populates="students")
    events = db.relationship("Event", back_populates="user")
    sent_messages = db.relationship("Message", foreign_keys='Message.sender_id', back_populates="sender")
    received_messages = db.relationship("Message", foreign_keys='Message.recipient_id', back_populates="recipient")

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), default="#000000")
    secret_name = db.Column(db.String(7), unique=True, nullable=False, default=lambda: ''.join(random.choices(string.ascii_letters + string.digits, k=7)))
    
    # Relationships
    students = db.relationship("User", secondary=user_classes, back_populates="classes")
    events = db.relationship("Event", back_populates="class_")

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True)  # Associate with Class

    # Relationships
    user = relationship("User", back_populates="events")
    class_ = relationship("Class", back_populates="events")

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    sender = db.relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    recipient = db.relationship("User", foreign_keys=[recipient_id], back_populates="received_messages")

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

def fetch_canvas_events(canvas_url):
    try:
        response = requests.get(canvas_url)
        if response.status_code != 200:
            logging.error(f"Failed to retrieve iCal data: HTTP {response.status_code}")
            return False

        # Parse iCal data
        events = parse_ical_data(response.text)
        logging.info(f"Fetched events: {events}")

        if not events:
            logging.warning("No events found in iCal data.")
            return False

        user = User.query.filter_by(canvas_ical_url=canvas_url).first()
        new_events = []

        for event_data in events:
            if 'title' not in event_data or 'date' not in event_data:
                continue

            # Add new event logic here
            existing_event = Event.query.filter_by(
                user_id=user.id,
                title=event_data['title'],
                date=event_data['date']
            ).first()
            if not existing_event:
                new_event = Event(
                    title=event_data['title'],
                    description=event_data.get('description', ''),
                    date=event_data['date'],
                    user_id=user.id,
                    class_id=None
                )
                new_events.append(new_event)

        db.session.bulk_save_objects(new_events)
        db.session.commit()
        return True

    except requests.RequestException as e:
        logging.error(f"Error fetching iCal data: {e}")
        return False


def fetch_canvas_courses(canvas_url, user):
    try:
        response = requests.get(canvas_url)
        if response.status_code != 200:
            logging.error(f"Failed to retrieve iCal data: HTTP {response.status_code}")
            return False

        cal = Calendar.from_ical(response.text)
        course_names = set()  # Use a set to avoid duplicates

        for component in cal.walk():
            if component.name == "VEVENT":
                summary = str(component.get('summary', ''))
                
                # Extract the course name (e.g., "CS-386")
                course_name = extract_course_name(summary)
                if course_name:
                    course_names.add(course_name)

        # Ensure each course is associated with the user
        for course_name in course_names:
            # Check if the class already exists in the database
            existing_class = Class.query.filter_by(name=course_name).first()
            if existing_class:
                # Associate existing class with user if not already associated
                if existing_class not in user.classes:
                    user.classes.append(existing_class)
            else:
                # If the class doesn't exist, create it and associate with the user
                new_class = Class(name=course_name)
                db.session.add(new_class)
                user.classes.append(new_class)

        db.session.commit()
        return True

    except requests.RequestException as e:
        logging.error(f"Error fetching iCal data: {e}")
        return False

def extract_course_name(summary):
    # Pattern to match course codes with a hyphen, like "CS-386"
    match = re.search(r'\b[A-Z]{2,4}-\d{3}\b', summary)
    
    if match:
        return match.group(0).strip()  # Return the matched course code (e.g., "CS-386")
    return None

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

# Home route
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        canvas_ical_url = request.form.get('canvas_ical_url', '')

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists. Please choose a different one.', 'danger')
            return redirect(url_for('register'))

        # Create and add the new user
        new_user = User(username=username, password=password, canvas_ical_url=canvas_ical_url)
        db.session.add(new_user)
        db.session.commit()

        # Automatically log in the new user
        session['user_id'] = new_user.id

        # Load Canvas classes immediately if a URL is provided
        if canvas_ical_url:
            success = fetch_canvas_courses(canvas_ical_url, new_user)
            if not success:
                flash("Failed to load Canvas calendar. Please check your Canvas URL.", "danger")

        return redirect(url_for('calendar'))  # Redirect to the calendar

    return render_template('register.html')

def validate_password(password):
    # Minimum 8 characters, at least one uppercase, one lowercase, one number, and one special character
    if (len(password) < 8 or not re.search(r"[A-Z]", password) or
            not re.search(r"[a-z]", password) or not re.search(r"[0-9]", password) or
            not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)):
        return False
    return True


# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('calendar'))
    return render_template('login.html')

@app.route('/register_class', methods=['GET', 'POST'])
def register_class():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        class_id = request.form.get('class_id')
        
        if class_id:  # Register for an existing class
            selected_class = Class.query.get(class_id)
            if selected_class not in user.classes:
                user.classes.append(selected_class)
        else:  # Register for a new class
            class_name = request.form['class_name']
            color = request.form['color']
            new_class = Class(name=class_name, color=color)
            user.classes.append(new_class)
            db.session.add(new_class)

        db.session.commit()
        return redirect(url_for('match_peers'))

    # Retrieve all classes to display in the dropdown
    classes = Class.query.all()
    return render_template('register_class.html', classes=classes)


@app.route('/calendar')
def calendar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = db.session.get(User, session['user_id'])
    
    # Fetch Canvas courses if the user has provided a Canvas URL
    if user.canvas_ical_url:
        success = fetch_canvas_courses(user.canvas_ical_url, user)
        if not success:
            flash("Failed to load Canvas calendar. Please check your Canvas URL.", "danger")

    classes = user.classes

    return render_template('calendar.html', classes=classes)

@app.route('/add_class', methods=['GET', 'POST'])
def add_class():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        class_name = request.form['class_name']
        color = request.form['color']
        
        # Check if the class already exists by name
        existing_class = Class.query.filter_by(name=class_name).first()
        
        if existing_class:
            # If the class exists and the user is not already registered, associate the user with it
            if existing_class not in user.classes:
                user.classes.append(existing_class)
        else:
            # If the class doesn't exist, create it and associate the user
            new_class = Class(name=class_name, color=color)
            user.classes.append(new_class)
            db.session.add(new_class)

        db.session.commit()
        return redirect(url_for('calendar'))
    
    return render_template('add_class.html')


@app.route('/add_event', methods=['GET', 'POST'])
def add_event():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        date = request.form['date']
        time = request.form['time']
        class_id = request.form.get('class_id')  # Get class_id from form

        datetime_str = f"{date} {time}"
        event_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')

        new_event = Event(
            title=title, 
            description=description, 
            date=event_datetime, 
            user_id=session['user_id'], 
            class_id=class_id  # Associate the event with the selected class
        )
        db.session.add(new_event)
        db.session.commit()
        return redirect(url_for('calendar'))
    
    user_id = session['user_id']
    classes = Class.query.filter_by(user_id=user_id).all()  # Fetch classes for the dropdown
    return render_template('add_event.html', classes=classes)

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

@app.route('/connect_with_peer/<int:peer_id>')
def connect_with_peer(peer_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    # Logic to create connection (could involve notifications or friend requests)
    flash("Connection request sent!", "success")
    return redirect(url_for('match_peers'))

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

@app.route('/message/<int:recipient_id>', methods=['GET', 'POST'])
def message_user(recipient_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    recipient = User.query.get(recipient_id)

    if request.method == 'POST':
        content = request.form['content']
        message = Message(sender_id=user.id, recipient_id=recipient.id, content=content)
        db.session.add(message)
        db.session.commit()
        return redirect(url_for('view_messages'))

    return render_template('message_user.html', recipient=recipient)

@app.route('/messages')
def view_messages():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    # Query received messages and order by timestamp
    received_messages = Message.query.filter_by(recipient_id=user_id).order_by(desc(Message.timestamp)).all()

    return render_template('messages.html', received_messages=received_messages)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        canvas_ical_url = request.form.get('canvas_ical_url')
        user.canvas_ical_url = canvas_ical_url
        db.session.commit()
        flash("Canvas calendar link updated successfully!", "success")
        return redirect(url_for('profile'))

    return render_template('profile.html', user=user)

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Main entry point of the application
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
