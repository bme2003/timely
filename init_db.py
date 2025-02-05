from app import create_app
from extensions import db
from models import User, Class, Event, Message, Notification, CourseResource, StudyGroup, Resource, PeerReview, StudyMeeting
import os

def init_db():
    app = create_app()
    
    with app.app_context():
        # Create uploads directory
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        # Remove existing database if it exists
        if os.path.exists('calendar.db'):
            os.remove('calendar.db')
            
        # Create all tables
        db.create_all()
        
        print("Database initialized successfully!")

if __name__ == '__main__':
    init_db() 