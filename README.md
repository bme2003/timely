# Timely

Timely is a college networking and scheduling tool designed to help students organize their academic lives more effectively. Students can create profiles based on their major, add their class schedules, manage events, and find peers who are in the same classes. Built with Flask for backend and frontend handling, it uses SQLite for data storage, offering an efficient platform for managing college routines.

## Features

- **User Registration and Login**: A secure system allowing students to register and log in with a username and password.
- **Password Security**: Passwords are securely hashed to protect user data.
- **Personalized Profile Setup**: Users can input their major and personalize their profile information.
- **Class Management**: Add classes through a form, assigning each class a name and color.
- **Event Management**: Users can add events to their schedule, including details like title, description, date, and time, with an option to associate each event with a specific class.
- **Interactive Calendar View**: A calendar displays scheduled events, allowing users to view, manage, and organize their classes and events. The calendar features color-coded events for quick visual reference based on class association.
- **Color-Coded Class Groups**: Classes are displayed in groups with specific colors, making it easy to distinguish between different subjects on the calendar.
- **Background Styling and Customization**: Consistent background images across pages, with logo integration on the home and login pages for a cohesive user experience.

## Technologies Used

- **Python**: Core language for backend logic.
- **Flask**: Web framework for routing, rendering templates, and handling HTTP requests.
- **SQLite**: Database for storing user profiles, class information, events, and relationships.
- **HTML/CSS**: For structuring and styling the front-end templates.
- **JavaScript**: Provides interactivity and functionality for calendar events and date selection.
- **FullCalendar Library**: JavaScript library for the interactive calendar.
- **Werkzeug**: Used for secure password hashing.

## Prerequisites

- **Python 3.x**
- **pip** (Python package installer)

## Folder Structure

```plaintext
timely/
├── app.py                   # Main application file with routes and configurations
├── requirements.txt         # Dependencies file
├── static/                  # Static assets
│   ├── images/              # Backgrounds, logos, and icons
│   │   ├── background.jpg
│   │   └── logo.jpg
│   └── styles.css           # Main stylesheet for styling the app
└── templates/               # HTML templates
    ├── home.html            # Landing page for the app
    ├── login.html           # Login page
    ├── register.html        # Registration page
    ├── calendar.html        # Calendar view for displaying events
    ├── add_event.html       # Form page for adding events
    └── add_class.html       # Form page for adding classes
## Getting Started

## 1. Clone repository locally
bash
git clone https://github.com/bme2003/timely.git

## 2. Install dependencies
bash
pip install -r reqs.txt

## 3. Setup Database and local instance
bash
python app.py

## Usage Guide

### User Registration and Login
- Go to the **Register** page to create a new account by providing a username and password.
- Once registered, log in using your credentials on the **Login** page.

### Managing Classes
- Access the **Add Class** page to add your classes, assigning each a unique name and color.
- Classes appear in the **Groups** section on the **Calendar** page, color-coded for easy reference.

### Adding Events
- Use the **Add Event** page to create events, assigning each event a title, description, date, time, and associated class.
- Events linked to classes are displayed with their respective colors on the calendar for clear visual separation.

### Interactive Calendar
- View your schedule in a monthly calendar format.
- Click on events to view more details, including title, description, and class association.
- Toggle between different time views to see your schedule for the day, week, or month.

### Class Peer Matching
- **Timely** will soon feature peer-matching based on shared classes, allowing students to find and connect with classmates.

## Screenshots

- **Home Page**: Displays the main landing page of the app.
- **Calendar View**: Shows the monthly calendar with class events.
- **Add Class**: A form to input new class information, including color coding.

## Troubleshooting

### Common Errors
- **Database errors**: Ensure that you've run the application at least once to initialize the database.
- **Pushing to GitHub**: If you encounter issues pushing to GitHub, try synchronizing with the remote repository first, then push your changes.

### Known Issues
- **Compatibility**: For the best experience, use an updated web browser. Some styling or interactive elements may display differently on older browsers.
