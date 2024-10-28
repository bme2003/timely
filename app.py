from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate

# Initialize the Flask app
app = Flask(__name__)

# Configure the SQLite database URI for SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///calendar.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'

# Initialize the SQLAlchemy database object
db = SQLAlchemy(app)

migrate = Migrate(app, db)

# Define the User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

# Define the Class model
class Class(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), default="#000000")  # Default color as black
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    events = db.relationship('Event', back_populates='class_')

# Define the Event model
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    date = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.id'), nullable=True) 
    class_ = db.relationship('Class', back_populates='events')

# Home route
@app.route('/')
def home():
    return render_template('home.html')

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

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

# Calendar route
@app.route('/calendar')
def calendar():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    events = Event.query.filter_by(user_id=user_id).all()
    classes = Class.query.filter_by(user_id=user_id).all()  # Fetch classes associated with the user

    return render_template('calendar.html', events=events, classes=classes)

# Add Class route
@app.route('/add_class', methods=['GET', 'POST'])
def add_class():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        class_name = request.form['class_name']
        color = request.form['color']
        new_class = Class(name=class_name, color=color, user_id=session['user_id'])
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
