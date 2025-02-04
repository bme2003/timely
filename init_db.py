from app import create_app
from extensions import db
from models import User, Class, Event, Message, Notification, CourseResource, StudyGroup
from sqlalchemy import inspect

def init_db():
    app = create_app()
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Add event_type column if it doesn't exist
        inspector = inspect(db.engine)
        if 'event' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('event')]
            if 'event_type' not in columns:
                with db.engine.connect() as conn:
                    conn.execute(db.text('ALTER TABLE event ADD COLUMN event_type VARCHAR(50) DEFAULT "assignment"'))
                    conn.commit()
        
        db.session.commit()

if __name__ == '__main__':
    init_db() 