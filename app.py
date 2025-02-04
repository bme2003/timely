from flask import Flask
from extensions import db, migrate
from models import User
import os
import secrets
from dotenv import load_dotenv
import logging
from routes import init_socketio, resource_routes

# Configure logging
logging.basicConfig(level=logging.INFO)

def create_app():
    app = Flask(__name__)
    
    # Load environment variables
    load_dotenv()
    
    # Configure app
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///calendar.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    socketio = init_socketio(app)

    # Register blueprints
    with app.app_context():
        from routes import (
            main_routes,
            auth_routes,
            calendar_routes,
            message_routes,
            resource_routes,
            study_routes,
            notification_routes,
            class_routes
        )
        app.register_blueprint(main_routes)
        app.register_blueprint(auth_routes)
        app.register_blueprint(calendar_routes, url_prefix='/calendar')
        app.register_blueprint(message_routes, url_prefix='/messages')
        app.register_blueprint(resource_routes, url_prefix='')
        app.register_blueprint(study_routes, url_prefix='/study')
        app.register_blueprint(notification_routes)
        app.register_blueprint(class_routes)

    return app

# Create the application instance
app = create_app()

# Main entry point of the application
if __name__ == '__main__':
    socketio.run(app, debug=True)
