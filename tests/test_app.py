# Command to run these tests if test_app.py is in a sub-directory called tests under app.py:
# python -m unittest discover -s tests

import unittest
from unittest.mock import patch, MagicMock
from app import app, db, User, Class, Event
from werkzeug.security import generate_password_hash
from datetime import datetime

# D4 - Test cases for routing function
class RoutingTestCases(unittest.TestCase):
    # Adapted from ChatGPT ---
    def setUp(self):
        # Enable testing mode
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    # Cleans up the database after each test. Automatically run following each test.
    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
    # Generated code segment end ---

    def test_home_route(self):
        """Test that the home route renders correctly."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200) # Check for successful render
        # Check if 'Home' is rendered on page to ensure home.html was rendered
        self.assertIn(b'Home', response.data)

    def test_register_route_get(self):
        """Test that the register page renders correctly (GET request)."""
        response = self.client.get('/register')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Register', response.data)

    def test_register_route_post(self):
        """Test that the register route creates a new user (POST request)."""
        response = self.client.post('/register', data={
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 302) # Check for redirect to login
        self.assertIn('/login', response.location) # Make sure user is at the login page

    def test_login_route_get(self):
        """Test that the login page renders correctly (GET request)."""
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data)

    def test_login_route_post(self):
        """Test that the login route authenticates a user (POST request)."""
        # Create a mock user
        hashed_password = generate_password_hash('testpassword')
        user = User(username='testuser', password=hashed_password)
        db.session.add(user)
        db.session.commit()

        # Test logging in
        response = self.client.post('/login', data={
            'username': 'testuser',
            'password': 'testpassword'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/calendar', response.location)

    def test_calendar_route_redirects_when_not_logged_in(self):
        """Test that the calendar route redirects to login when user is not logged in."""
        with self.client as client:
            response = client.get('/calendar')
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login', response.location)

    @patch('app.Event')
    @patch('app.Class')
    def test_calendar_route_renders_calendar_for_logged_in_user(self, MockClass, MockEvent):
        """Test that the calendar route renders correctly when user is logged in."""
        with self.client as client:
            with client.session_transaction() as session:
                session['user_id'] = 1  # Mock a logged-in user

        # Mock Event and Class instances
        mock_event = MagicMock()
        mock_class = MagicMock()
        MockEvent.query.filter_by.return_value.all.return_value = [mock_event]
        MockClass.query.filter_by.return_value.all.return_value = [mock_class]

        response = client.get('/calendar')
        self.assertEqual(response.status_code, 200)

        # Check for specific wording from calendar.html - MUST UPDATE IF calendar.html IS UPDATED.
        self.assertIn(b'Your Calendar', response.data)
        self.assertIn(b'Groups', response.data)
        self.assertIn(b'Add New Event', response.data)

    def test_add_class_route_redirect(self):
        """Test that the add_class route redirects if not logged in."""
        response = self.client.get('/add_class')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

    def test_add_class_route_post(self):
        """Test that the add_class route adds a new class for a logged-in user."""
        with self.client as client:
            with client.session_transaction() as session:
                session['user_id'] = 1  # Mock a logged-in user

        response = self.client.post('/add_class', data={
            'class_name': 'Computer Science',
            'color': '#FFFFFF'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/calendar', response.location)

    def test_add_event_route_redirect(self):
        """Test that the add_event route redirects if not logged in."""
        response = self.client.get('/add_event')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

    def test_add_event_route_post(self):
        """Test that the add_event route creates a new event for a logged-in user."""
        with self.client as client:
            with client.session_transaction() as session:
                session['user_id'] = 1

        # Mock an Event 
        new_class = Class(name='Computer Science', color='#FFFFFF', user_id=1)
        db.session.add(new_class)
        db.session.commit()

        response = client.post('/add_event', data={
            'title': 'Test Event',
            'description': 'This is a test event.',
            'date': '2024-10-30',
            'time': '14:30',
            'class_id': new_class.id
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/calendar', response.location)

    def test_logout_route(self):
        """Test that the logout route clears the session and redirects to login."""
        with self.client as client:
            with client.session_transaction() as session:
                session['user_id'] = 1

        response = client.get('/logout')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

        # Confirm that 'user_id' is no longer in session
        with client.session_transaction() as session:
            self.assertNotIn('user_id', session)

# D4 - Test cases for creating objects in database from models
class ModelTestCases(unittest.TestCase):
    # Adapted from ChatGPT ---
    # Set up test database
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app = app.test_client()
        with app.app_context():
            db.create_all()

    # Tear down test database
    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
    # Generated code end ---

    # Test creating a User object
    def test_create_user(self):
        with app.app_context():
            user = User(username='testuser', password='testpass')
            db.session.add(user)
            db.session.commit()

            # Make sure user is properly created in database
            saved_user = User.query.filter_by(username='testuser').first()
            self.assertIsNotNone(saved_user)
            self.assertEqual(saved_user.username, 'testuser')
            self.assertEqual(saved_user.password, 'testpass')

    # Test creating a Class object associated with a User
    def test_create_class(self):
        with app.app_context():
            # Create and add user first
            user = User(username='testuser', password='testpass')
            db.session.add(user)
            db.session.commit()
            # Create class associated with the user
            new_class = Class(name='Computer Science', color='#FFFFFF', user_id=user.id)
            db.session.add(new_class)
            db.session.commit()
            # Check if class is properly created in database
            saved_class = Class.query.filter_by(name='Computer Science').first()
            self.assertIsNotNone(saved_class)
            self.assertEqual(saved_class.name, 'Computer Science')
            self.assertEqual(saved_class.color, '#FFFFFF')
            self.assertEqual(saved_class.user_id, user.id)

    # Test creating an Event object associated with a User and a Class
    def test_create_event(self):
        with app.app_context():
            # Create and add user and class first
            user = User(username='testuser', password='testpass')
            db.session.add(user)
            db.session.commit()
            new_class = Class(name='Computer Science', color='#FFFFFF', user_id=user.id)
            db.session.add(new_class)
            db.session.commit()
            # Create event associated with the user and class
            event = Event(
                title='Group meeting 1',
                description='First meeting for CS, dont be late!',
                date=datetime(2024, 12, 25),
                user_id=user.id,
                class_id=new_class.id
            )
            db.session.add(event)
            db.session.commit()
            # Check if event is properly created in database
            saved_event = Event.query.filter_by(title='Group meeting 1').first()
            self.assertIsNotNone(saved_event)
            self.assertEqual(saved_event.title, 'Group meeting 1')
            self.assertEqual(saved_event.description, 'First meeting for CS, dont be late!')
            self.assertEqual(saved_event.date, datetime(2024, 12, 25))
            self.assertEqual(saved_event.user_id, user.id)
            self.assertEqual(saved_event.class_id, new_class.id)
