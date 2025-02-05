from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash, current_app, send_from_directory, send_file
from extensions import db
from models import User, Class, Event, Message, Notification, CourseResource, StudyGroup, Resource, StudyMeeting
from datetime import datetime, timedelta, timezone
from utils import (
    login_required,
    fetch_canvas_events,
    fetch_canvas_courses,
    parse_ical_data,
    extract_course_name,
    process_canvas_events,
    allowed_file,
    create_notification
)
import logging
import os
import re
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import secrets
from flask_wtf import FlaskForm
import requests
import icalendar
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import current_user

# Initialize Blueprints
main_routes = Blueprint('main', __name__)
auth_routes = Blueprint('auth', __name__)
calendar_routes = Blueprint('calendar', __name__)
message_routes = Blueprint('messages', __name__)
resource_routes = Blueprint('resources', __name__)
study_routes = Blueprint('study', __name__)
notification_routes = Blueprint('notifications', __name__)
class_routes = Blueprint('classes', __name__)

socketio = SocketIO()

# Add this after your blueprint definitions
def init_socketio(app):
    socketio.init_app(app, cors_allowed_origins="*")
    return socketio

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        join_room(f"user_{session['user_id']}")

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        leave_room(f"user_{session['user_id']}")

@socketio.on('send_message')
def handle_message(data):
    try:
        sender_id = session['user_id']
        recipient_id = data['recipient_id']
        content = data['content']
        
        message = Message(
            sender_id=sender_id,
            recipient_id=recipient_id,
            content=content,
            timestamp=datetime.utcnow()
        )
        db.session.add(message)
        db.session.commit()
        
        message_data = {
            'id': message.id,
            'content': message.content,
            'sender_id': message.sender_id,
            'timestamp': message.timestamp.strftime('%I:%M %p')
        }
        
        # Emit to both sender and recipient rooms
        emit('new_message', message_data, room=f"user_{sender_id}")
        emit('new_message', message_data, room=f"user_{recipient_id}")
        
        # Update unread count for recipient
        emit('update_unread', room=f"user_{recipient_id}")
        
    except Exception as e:
        logging.error(f"Socket error: {str(e)}")

# --------------------------
# Authentication Routes
# --------------------------

@auth_routes.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('main.home'))
            
        flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@auth_routes.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        canvas_ical_url = request.form.get('canvas_ical_url')

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('auth.signup'))

        hashed_password = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            password=hashed_password,
            canvas_ical_url=canvas_ical_url
        )

        try:
            db.session.add(new_user)
            db.session.commit()
            if canvas_ical_url:
                fetch_canvas_courses(canvas_ical_url, new_user)
                fetch_canvas_events(canvas_ical_url, new_user)
            flash('Account created successfully!', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Signup error: {str(e)}")
            flash('Registration failed', 'error')
    return render_template('signup.html')

@auth_routes.route('/reset_password', methods=['GET', 'POST'])
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
            return redirect(url_for('auth.login'))
            
        flash('Email address not found.', 'error')
    
    return render_template('reset_password.html')

@auth_routes.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.landing'))

# --------------------------
# Calendar Routes
# --------------------------

@calendar_routes.route('/')
@login_required
def calendar():
    try:
        user = db.session.get(User, session['user_id'])
        # Filter out archived classes
        active_classes = [c for c in user.classes if not c.archived]
        
        # Only get events from active classes
        events = Event.query.join(Class).filter(
            Event.user_id == user.id,
            Class.archived == False
        ).all()
        
        # Get classmates for each active class
        classmates_by_class = {}
        for class_obj in active_classes:
            classmates = [student for student in class_obj.students if student.id != user.id]
            classmates_by_class[class_obj.id] = classmates
        
        # Safely check for Canvas URL
        show_canvas_import = bool(getattr(user, 'canvas_ical_url', None))
        
        return render_template('calendar.html',
            user=user,
            classes=active_classes,
            events=events,
            show_canvas_import=show_canvas_import,
            classmates_by_class=classmates_by_class
        )
        
    except Exception as e:
        logging.error(f"Calendar error: {str(e)}")
        flash('An error occurred while loading your calendar.', 'error')
        return redirect(url_for('main.home'))

@calendar_routes.route('/events')
@login_required
def get_calendar_events():
    try:
        user = db.session.get(User, session['user_id'])
        # Only get events from non-archived classes
        events = Event.query.join(Class).filter(
            Event.user_id == user.id,
            Class.archived == False
        ).all()
        
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

@calendar_routes.route('/add_class', methods=['GET', 'POST'])
@login_required
def add_class():
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        class_color = request.form.get('color', '#000000')
        
        if not class_name:
            flash('Class name is required', 'error')
            return redirect(url_for('calendar.add_class'))
            
        try:
            user = db.session.get(User, session['user_id'])
            new_class = Class(
                name=class_name,
                color=class_color
            )
            db.session.add(new_class)
            user.classes.append(new_class)
            db.session.commit()
            
            flash('Class added successfully!', 'success')
            return redirect(url_for('calendar.manage_classes'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error adding class: {str(e)}")
            flash('Error adding class. Please try again.', 'error')
            return redirect(url_for('calendar.add_class'))
            
    return render_template('add_class.html')

@calendar_routes.route('/add_event', methods=['POST'])
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

@calendar_routes.route('/generate_schedule', methods=['POST'])
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

@calendar_routes.route('/generate_smart_schedule', methods=['POST'])
@login_required
def generate_smart_schedule():
    try:
        user = db.session.get(User, session['user_id'])
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 400
            
        if not user.classes:
            return jsonify({'success': False, 'message': 'No classes found. Please add classes first.'}), 400
            
        now = datetime.now()
        end_date = now + timedelta(days=30)
        
        assignments = Event.query.filter(
            Event.user_id == user.id,
            Event.event_type == 'assignment',
            Event.date >= now,
            Event.date <= end_date
        ).order_by(Event.date).all()
        
        if not assignments:
            return jsonify({'success': False, 'message': 'No upcoming assignments found'}), 400
        
        Event.query.filter(
            Event.user_id == user.id,
            Event.event_type == 'study_session',
            Event.date >= now
        ).delete()

        study_sessions = []
        for assignment in assignments:
            for days_before in [5, 3, 1]:
                study_date = assignment.date - timedelta(days=days_before)
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
        logging.error(f"Error generating smart schedule: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500

@calendar_routes.route('/get_student_schedule/<int:student_id>/<int:class_id>')
@login_required
def get_student_schedule(student_id, class_id):
    try:
        user = db.session.get(User, session['user_id'])
        class_obj = db.session.get(Class, class_id)
        
        if not class_obj or user not in class_obj.students:
            return jsonify({'error': 'Unauthorized'}), 403
            
        student_events = Event.query.filter_by(
            user_id=student_id,
            class_id=class_id
        ).all()
        
        return jsonify({'events': [event.id for event in student_events]})
        
    except Exception as e:
        logging.error(f"Error getting student schedule: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@calendar_routes.route('/import_canvas', methods=['POST'])
@login_required
def import_canvas():
    try:
        user = db.session.get(User, session['user_id'])
        data = request.get_json(silent=True) or {}
        canvas_url = data.get('canvas_url')
        
        # If URL provided, save it to user profile
        if canvas_url:
            if not canvas_url.startswith(('http://', 'https://')):
                return jsonify({'success': False, 'message': 'Invalid URL format'}), 400
                
            if 'canvas' not in canvas_url.lower():
                return jsonify({'success': False, 'message': 'Not a valid Canvas URL'}), 400
                
            user.canvas_ical_url = canvas_url
            db.session.commit()
        
        # Use saved URL if none provided
        url_to_use = canvas_url or user.canvas_ical_url
        if not url_to_use:
            return jsonify({'success': False, 'message': 'No Canvas URL configured'}), 400
            
        # Import courses and events
        success = fetch_canvas_courses(url_to_use, user)
        if not success:
            return jsonify({'success': False, 'message': 'Failed to import courses'}), 400
            
        success = fetch_canvas_events(url_to_use, user)
        if not success:
            return jsonify({'success': False, 'message': 'Failed to import events'}), 400
            
        return jsonify({
            'success': True,
            'message': 'Canvas data imported successfully'
        })
        
    except Exception as e:
        logging.error(f"Canvas import error: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error importing Canvas data'
        }), 500

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
                        class_id=get_class_id(course.name)
                    )
                    db.session.add(event)
        
        db.session.commit()
        return True
    except Exception as e:
        print(f"Canvas import error: {e}")
        return False

@calendar_routes.route('/save_canvas_url', methods=['POST'])
@login_required
def save_canvas_url():
    try:
        user = db.session.get(User, session['user_id'])
        data = request.get_json()
        canvas_url = data.get('canvas_url')
        
        if not canvas_url:
            return jsonify({
                'success': False,
                'message': 'No Canvas URL provided'
            }), 400
            
        if not canvas_url.startswith(('http://', 'https://')):
            return jsonify({
                'success': False,
                'message': 'Invalid URL format'
            }), 400
            
        if 'canvas' not in canvas_url.lower():
            return jsonify({
                'success': False,
                'message': 'Not a valid Canvas URL'
            }), 400
            
        user.canvas_ical_url = canvas_url
        db.session.commit()
        
        # Try to import courses immediately
        success = fetch_canvas_courses(canvas_url, user)
        
        return jsonify({
            'success': True,
            'message': 'Canvas URL saved successfully'
        })
        
    except Exception as e:
        logging.error(f"Error saving Canvas URL: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error saving Canvas URL'
        }), 500

# --------------------------
# Messaging Routes
# --------------------------

@message_routes.route('/')
@message_routes.route('/<int:recipient_id>')
@login_required
def messages(recipient_id=None):
    try:
        user = db.session.get(User, session['user_id'])
        friends = user.friends.all()
        
        # Get last messages for each friend
        for friend in friends:
            last_message = Message.query.filter(
                ((Message.sender_id == user.id) & (Message.recipient_id == friend.id)) |
                ((Message.sender_id == friend.id) & (Message.recipient_id == user.id))
            ).order_by(Message.timestamp.desc()).first()
            
            if last_message:
                friend.last_message = last_message.content
                friend.unread_count = Message.query.filter_by(
                    sender_id=friend.id,
                    recipient_id=user.id,
                    status='unread'
                ).count()
        
        chat_messages = []
        selected_recipient = None
        
        if recipient_id:
            selected_recipient = db.session.get(User, recipient_id)
            if selected_recipient:
                chat_messages = Message.query.filter(
                    ((Message.sender_id == user.id) & (Message.recipient_id == recipient_id)) |
                    ((Message.sender_id == recipient_id) & (Message.recipient_id == user.id))
                ).order_by(Message.timestamp).all()
                
                # Mark messages as read
                Message.query.filter_by(
                    sender_id=recipient_id,
                    recipient_id=user.id,
                    status='unread'
                ).update({'status': 'read'})
                db.session.commit()
        
        return render_template('messages.html',
                             user=user,
                             friends=friends,
                             chat_messages=chat_messages,
                             selected_recipient=selected_recipient)
                             
    except Exception as e:
        logging.error(f"Error accessing messages: {str(e)}")
        flash('Error accessing messages', 'error')
        return redirect(url_for('main.home'))

@message_routes.route('/connect/<int:peer_id>', methods=['POST'])
@login_required
def connect_with_peer(peer_id):
    try:
        user = User.query.get(session['user_id'])
        peer = User.query.get(peer_id)
        
        connection = Message(
            sender_id=user.id,
            recipient_id=peer_id,
            message_type='connection_request'
        )
        db.session.add(connection)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Connection error: {str(e)}")
        return jsonify({'success': False}), 500

@message_routes.route('/unread_count')
@login_required
def get_unread_count():
    try:
        user_id = session['user_id']
        count = Message.query.filter_by(
            recipient_id=user_id,
            read=False
        ).count()
        return jsonify({'count': min(count, 99)})
    except Exception as e:
        logging.error(f"Error getting unread count: {str(e)}")
        return jsonify({'count': 0})

@message_routes.route('/api/messages/unread-count')
@login_required
def get_unread_message_count():
    try:
        user_id = session['user_id']
        count = Message.query.filter_by(
            recipient_id=user_id,
            status='unread'
        ).count()
        return jsonify({'count': min(count, 99)})
    except Exception as e:
        logging.error(f"Error getting unread count: {str(e)}")
        return jsonify({'count': 0})

@message_routes.route('/send', methods=['POST'])
@login_required
def send_message():
    try:
        data = request.get_json()
        recipient_id = data.get('recipient_id')
        content = data.get('content')
        
        if not recipient_id or not content:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
            
        message = Message(
            sender_id=session['user_id'],
            recipient_id=recipient_id,
            content=content,
            status='unread',
            timestamp=datetime.utcnow()
        )
        db.session.add(message)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': {
                'id': message.id,
                'content': message.content,
                'timestamp': message.timestamp.strftime('%I:%M %p')
            }
        })
        
    except Exception as e:
        logging.error(f"Error sending message: {str(e)}")
        return jsonify({'success': False, 'message': 'Error sending message'}), 500

@message_routes.route('/mark-read/<int:sender_id>', methods=['POST'])
@login_required
def mark_messages_read(sender_id):
    try:
        Message.query.filter_by(
            sender_id=sender_id,
            recipient_id=session['user_id'],
            status='unread'
        ).update({'status': 'read'})
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Error marking messages read: {str(e)}")
        return jsonify({'success': False}), 500

# --------------------------
# Resource Routes
# --------------------------

@resource_routes.route('/resources')
@login_required
def resources():
    try:
        user = db.session.get(User, session['user_id'])
        
        # Get filter parameters
        class_id = request.args.get('class_id')
        resource_type = request.args.get('type')
        sort = request.args.get('sort', 'newest')
        
        # Base query - exclude archived classes
        query = CourseResource.query.join(Class).filter(
            Class.students.any(id=user.id),
            Class.archived == False
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
        
        resources_list = query.all()
        active_classes = [c for c in user.classes if not c.archived]
        
        return render_template('resources.html',
                             user=user,
                             resources=resources_list,
                             classes=active_classes)
                             
    except Exception as e:
        logging.error(f"Error loading resources: {str(e)}")
        flash('Error loading resources', 'error')
        return redirect(url_for('main.home'))

@resource_routes.route('/share_resource', methods=['POST'])
@login_required
def share_resource():
    try:
        user = db.session.get(User, session['user_id'])
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed'}), 400
            
        filename = secure_filename(file.filename)
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        
        # Set resource_type either from the form, or use a default value (for example, "general")
        resource_type = request.form.get('type') or "general"
        
        resource = CourseResource(
            title=request.form.get('title'),
            resource_type=resource_type,
            notes=request.form.get('notes'),
            url=f"/uploads/{filename}",
            class_id=request.form.get('class_id'),
            shared_by=user.id
        )
        
        db.session.add(resource)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Resource shared successfully!'
        })
        
    except Exception as e:
        logging.error(f"Share resource error: {str(e)}")
        return jsonify({
            'error': 'Failed to upload resource',
            'details': str(e)
        }), 500

@resource_routes.route('/class/<int:class_id>/resources')
@login_required
def class_resources(class_id):
    try:
        user = db.session.get(User, session['user_id'])
        class_ = db.session.get(Class, class_id)
        
        if not class_ or user not in class_.students:
            flash('Unauthorized access to class resources', 'error')
            return redirect(url_for('main.home'))
        
        resources = CourseResource.query.filter_by(class_id=class_id).all()
        return render_template('class_resources.html', 
                             user=user,
                             class_=class_, 
                             resources=resources)
                             
    except Exception as e:
        logging.error(f"Error accessing class resources: {str(e)}")
        flash('Error accessing class resources', 'error')
        return redirect(url_for('main.home'))

@resource_routes.route('/upload', methods=['POST'])
@login_required
def upload_resource():
    try:
        logging.info("Starting resource upload...")

        if 'file' not in request.files:
            logging.error("No file in request")
            return jsonify({'error': 'No file selected'}), 400

        file = request.files['file']
        if file.filename == '':
            logging.error("Empty filename")
            return jsonify({'error': 'No file selected'}), 400

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"

            upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)

            file_path = os.path.join(upload_dir, unique_filename)
            file.save(file_path)
            logging.info(f"File saved to: {file_path}")

            resource = CourseResource(
                title=request.form.get('title'),
                resource_type=file.filename.split('.')[-1].lower(),
                url=f'/static/uploads/{unique_filename}',
                notes=request.form.get('description'),
                shared_by=session['user_id'],
                class_id=request.form.get('class_id'),
                created_at=datetime.utcnow()
            )
            logging.info(f"Created resource object for class {resource.class_id} with title '{resource.title}'")

            db.session.add(resource)
            db.session.commit()
            logging.info(f"Resource saved with ID: {resource.id}")

            # Debug: Log all resources for this class so you can check the count
            resources_in_db = CourseResource.query.filter_by(class_id=resource.class_id).all()
            logging.info(f"Total resources for class {resource.class_id}: {len(resources_in_db)}")
            for res in resources_in_db:
                logging.info(f" - Resource ID {res.id}: {res.title}")

            return jsonify({
                'success': True,
                'message': 'Resource uploaded successfully!',
                'resource': {
                    'id': resource.id,
                    'title': resource.title,
                    'notes': resource.notes,
                    'url': resource.url,
                    'class_id': resource.class_id
                }
            })
        else:
            logging.error("File type not allowed")
            return jsonify({'error': 'File type not allowed'}), 400

    except Exception as e:
        logging.error(f"Upload error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to upload resource', 'details': str(e)}), 500

@resource_routes.route('/download/<int:resource_id>')
@login_required
def download_resource(resource_id):
    try:
        resource = Resource.query.get_or_404(resource_id)
        
        if not resource.file_path:
            flash('No file available for download', 'error')
            return redirect(request.referrer)
            
        # Get the file from the static/uploads directory
        file_path = os.path.join(current_app.root_path, 'static', 'uploads', resource.file_path)
        
        if not os.path.exists(file_path):
            flash('File not found', 'error')
            return redirect(request.referrer)
            
        # Increment download counter
        resource.downloads += 1
        db.session.commit()
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=resource.filename
        )
        
    except Exception as e:
        logging.error(f"Download error: {str(e)}")
        flash('Error downloading resource', 'error')
        return redirect(request.referrer)

# --------------------------
# Main Routes
# --------------------------

@main_routes.route('/')
@main_routes.route('/landing')
def landing():
    return render_template('landing.html')

@main_routes.context_processor
def inject_user():
    return {
        'current_user': db.session.get(User, session.get('user_id')) if 'user_id' in session else None
    }

@main_routes.route('/home')
@login_required
def home():
    user = db.session.get(User, session['user_id'])
    classes = user.classes
    
    # Get matched peers for each class
    matched_peers = {}
    for class_ in classes:
        classmates = [student for student in class_.students 
                     if student.id != user.id]
        if classmates:
            matched_peers[class_.name] = classmates
    
    return render_template('home.html', 
                         user=user,
                         classes=classes, 
                         matched_peers=matched_peers)

@main_routes.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = db.session.get(User, session['user_id'])
    
    if request.method == 'POST':
        canvas_ical_url = request.form.get('canvas_ical_url')
        if canvas_ical_url:
            user.canvas_ical_url = canvas_ical_url
            try:
                # Import Canvas data
                courses_success = fetch_canvas_courses(canvas_ical_url, user)
                events_success = fetch_canvas_events(canvas_ical_url, user)
                
                db.session.commit()
                
                if courses_success and events_success:
                    flash('Canvas URL updated and data imported successfully!', 'success')
                else:
                    flash('Canvas URL updated but there was an issue importing some data.', 'warning')
            except Exception as e:
                db.session.rollback()
                flash('Error updating Canvas URL. Please try again.', 'error')
                logging.error(f"Canvas update error: {str(e)}")
        
    return render_template('profile.html', user=user)

@main_routes.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = db.session.get(User, session['user_id'])
    
    if user:
        try:
            db.session.delete(user)
            db.session.commit()
            flash('Your account has been deleted successfully.', 'success')
            session.clear()  # Clear the session after deletion
            return redirect(url_for('welcome'))  # Redirect to a welcome or login page
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while deleting your account.', 'danger')
            print(f"Error: {e}")  # For debugging
    else:
        flash('User not found. Please log in again.', 'danger')
    
    return redirect(url_for('profile'))  # Redirect back to profile if something goes wrong

# --------------------------
# Utility Routes
# --------------------------

@main_routes.route('/notifications')
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(
        user_id=session['user_id'],
        read=False
    ).all()
    return jsonify([n.serialize() for n in notifications])

@message_routes.route('/accept/<int:request_id>', methods=['POST'])
@login_required
def accept_connection(request_id):
    try:
        request = Message.query.get(request_id)
        request.status = 'accepted'
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"Accept error: {str(e)}")
        return jsonify({'success': False}), 500

# --------------------------
# Study Routes
# --------------------------

@study_routes.route('/groups/<int:class_id>')
@login_required
def study_groups(class_id):
    try:
        user = db.session.get(User, session['user_id'])
        class_ = db.session.get(Class, class_id)
        
        if not class_ or user not in class_.students:
            flash('Unauthorized access to study groups', 'error')
            return redirect(url_for('main.home'))
            
        groups = StudyGroup.query.filter_by(class_id=class_id).all()
        return render_template('study_groups.html', 
                             class_obj=class_,
                             study_groups=groups)
                             
    except Exception as e:
        logging.error(f"Error accessing study groups: {str(e)}")
        flash('Error accessing study groups', 'error')
        return redirect(url_for('main.home'))

@study_routes.route('/groups/<int:class_id>/new')
@login_required
def create_study_group_form(class_id):
    try:
        user = db.session.get(User, session['user_id'])
        class_ = db.session.get(Class, class_id)
        
        if not class_ or user not in class_.students:
            flash('Unauthorized access', 'error')
            return redirect(url_for('main.home'))
            
        return render_template('create_study_group.html', 
                             class_obj=class_,
                             user=user)
                             
    except Exception as e:
        logging.error(f"Error accessing create study group form: {str(e)}")
        flash('Error accessing create study group form', 'error')
        return redirect(url_for('main.home'))

@study_routes.route('/groups/<int:class_id>')
@login_required
def view_study_groups(class_id):
    try:
        user = db.session.get(User, session['user_id'])
        class_ = db.session.get(Class, class_id)
        
        if not class_ or user not in class_.students:
            flash('Unauthorized access', 'error')
            return redirect(url_for('main.home'))
            
        study_groups = StudyGroup.query.filter_by(class_id=class_id).all()
        return render_template('study_groups.html',
                             class_obj=class_,
                             study_groups=study_groups,
                             current_user=user)
                             
    except Exception as e:
        logging.error(f"Error accessing study groups: {str(e)}")
        flash('Error accessing study groups', 'error')
        return redirect(url_for('main.home'))

@study_routes.route('/find_buddies')
@login_required
def find_study_buddies():
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

@study_routes.route('/groups/<int:class_id>/create', methods=['POST'])
@login_required
def create_study_group(class_id):
    try:
        user = db.session.get(User, session['user_id'])
        class_ = db.session.get(Class, class_id)
        
        if not class_ or user not in class_.students:
            flash('Unauthorized access', 'error')
            return redirect(url_for('main.home'))
            
        study_group = StudyGroup(
            name=request.form.get('name'),
            description=request.form.get('description'),
            max_members=request.form.get('max_members', type=int),
            class_id=class_id,
            created_by=user.id
        )
        
        study_group.members.append(user)
        db.session.add(study_group)
        db.session.commit()
        
        flash('Study group created successfully!', 'success')
        return redirect(url_for('study.view_study_groups', class_id=class_id))
        
    except Exception as e:
        logging.error(f"Error creating study group: {str(e)}")
        flash('Error creating study group', 'error')
        return redirect(url_for('main.home'))

@study_routes.route('/groups/<int:group_id>/join', methods=['POST'])
@login_required
def join_study_group(group_id):
    try:
        user = db.session.get(User, session['user_id'])
        group = db.session.get(StudyGroup, group_id)
        
        if not group:
            return jsonify({'success': False, 'message': 'Group not found'}), 404
            
        if user in group.members:
            return jsonify({'success': False, 'message': 'Already a member'}), 400            
        if len(group.members) >= group.max_members:
            return jsonify({'success': False, 'message': 'Group is full'}), 400
            
        group.members.append(user)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logging.error(f"Error joining study group: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@study_routes.route('/groups/<int:group_id>/leave', methods=['POST'])
@login_required
def leave_study_group(group_id):
    try:
        user = db.session.get(User, session['user_id'])
        group = db.session.get(StudyGroup, group_id)
        
        if not group:
            return jsonify({'success': False, 'message': 'Group not found'}), 404
            
        if user not in group.members:
            return jsonify({'success': False, 'message': 'Not a member'}), 400
            
        if user.id == group.created_by:
            return jsonify({'success': False, 'message': 'Creator cannot leave group'}), 400
            
        group.members.remove(user)
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logging.error(f"Error leaving study group: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# --------------------------
# Notification Routes
# --------------------------

@notification_routes.route('/', methods=['GET'])
@login_required
def get_notifications():
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

@notification_routes.route('/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    notification_ids = request.json.get('notification_ids', [])
    Notification.query.filter(
        Notification.id.in_(notification_ids),
        Notification.user_id == session['user_id']
    ).update({Notification.read: True}, synchronize_session=False)
    
    db.session.commit()
    return jsonify({'success': True})

@class_routes.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_classes():
    try:
        user = db.session.get(User, session['user_id'])
        
        if request.method == 'POST':
            class_id = request.form.get('class_id')
            action = request.form.get('action', 'archive')
            
            if class_id:
                class_obj = Class.query.get(class_id)
                if class_obj and class_obj in user.classes:
                    if action == 'archive':
                        class_obj.archived = True
                        class_obj.archived_date = datetime.utcnow()
                        flash('Class archived successfully!', 'success')
                    elif action == 'restore':
                        class_obj.archived = False
                        class_obj.archived_date = None
                        flash('Class restored successfully!', 'success')
                    db.session.commit()
        
        active_classes = [c for c in user.classes if not c.archived]
        archived_classes = [c for c in user.classes if c.archived]
        
        return render_template('manage_classes.html', 
                             active_classes=active_classes,
                             archived_classes=archived_classes)
                             
    except Exception as e:
        logging.error(f"Error managing classes: {str(e)}")
        flash('Error managing classes', 'error')
        return redirect(url_for('main.home'))

@class_routes.route('/add', methods=['GET', 'POST'])
@login_required
def add_class():
    if request.method == 'POST':
        class_name = request.form.get('class_name')
        class_color = request.form.get('color', '#000000')
        
        if not class_name:
            flash('Class name is required', 'error')
            return redirect(url_for('classes.add_class'))
            
        try:
            user = db.session.get(User, session['user_id'])
            new_class = Class(
                name=class_name,
                color=class_color
            )
            db.session.add(new_class)
            user.classes.append(new_class)
            db.session.commit()
            
            flash('Class added successfully!', 'success')
            return redirect(url_for('classes.manage'))
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error adding class: {str(e)}")
            flash('Error adding class. Please try again.', 'error')
            return redirect(url_for('classes.add_class'))
            
    return render_template('add_class.html')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@main_routes.route('/add_friend/<int:friend_id>', methods=['POST'])
@login_required
def add_friend(friend_id):
    try:
        user = db.session.get(User, session['user_id'])
        friend = db.session.get(User, friend_id)
        
        if not friend:
            return jsonify({'success': False, 'message': 'User not found'}), 404
            
        if friend in user.friends:
            return jsonify({'success': False, 'message': 'Already friends'}), 400
            
        user.friends.append(friend)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Added {friend.username} as friend'
        })
        
    except Exception as e:
        logging.error(f"Error adding friend: {str(e)}")
        return jsonify({'success': False, 'message': 'Error adding friend'}), 500

@class_routes.route('/classmates')
@login_required
def classmates():
    user = db.session.get(User, session['user_id'])
    # Only show active classes
    active_classes = [c for c in user.classes if not c.archived]
    
    return render_template('classmates.html', 
                         classes=active_classes)

@class_routes.route('/archive/<int:class_id>', methods=['POST'])
@login_required
def archive_class(class_id):
    try:
        class_ = db.session.get(Class, class_id)
        if not class_:
            flash('Class not found', 'error')
            return redirect(url_for('classes.manage'))
            
        class_.archived = True
        class_.archived_date = datetime.utcnow()
        db.session.commit()
        
        flash('Class archived successfully', 'success')
        return redirect(url_for('classes.manage'))
        
    except Exception as e:
        logging.error(f"Error archiving class: {str(e)}")
        flash('Error archiving class', 'error')
        return redirect(url_for('classes.manage'))
