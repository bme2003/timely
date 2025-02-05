from extensions import db
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

# Association tables
user_classes = db.Table('user_classes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('class_id', db.Integer, db.ForeignKey('class.id'), primary_key=True)
)

friends = db.Table('friends',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('friend_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
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

    def get_unread_message_count(self, from_user_id):
        count = Message.query.filter_by(
            sender_id=from_user_id,
            recipient_id=self.id,
            status='unread'
        ).count()
        return min(count, 99)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), default='#3498db')
    archived = db.Column(db.Boolean, default=False)
    archived_date = db.Column(db.DateTime)
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
    filename = db.Column(db.String(500))
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

class StudyMeeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('study_group.id'))
    date = db.Column(db.DateTime, nullable=False)
    duration = db.Column(db.Integer)  # in minutes
    location = db.Column(db.String(200))
    meeting_link = db.Column(db.String(500))
    notes = db.Column(db.Text)
    attendees = db.relationship('User', secondary='meeting_attendees')