from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import uuid 
from datetime import datetime
# Security imports for passwords
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'ridesmart_secret_key'

# Connect to the local database
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="12345678910", 
        database="ridesmart_db"
    )

# Home page
@app.route('/')
def index():
    return render_template('BusSeatReservationSystem(vs).html')

# Login logic
@app.route('/login', methods=['POST'])
def login():
    phone = request.form.get('phone_number')
    pin = request.form.get('user_pin')

    # Quick way for admin to get in
    if phone == "0712345678" and pin == "9999":
        session['user_id'] = 'ADMIN'
        session['user_name'] = 'System Admin'
        return redirect(url_for('admin_dashboard'))

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT userId, fname, user_pin FROM users WHERE phone_number = %s", (phone,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        # Check if user exists and PIN matches
        if user and check_password_hash(user['user_pin'], pin):
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']
            return redirect(url_for('main_page'))
        
        return render_template('BusSeatReservationSystem(vs).html', error="Invalid phone number or PIN")
        
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Database connection failed")

# User's main booking page
@app.route('/main_page')
def main_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Get all buses
        cursor.execute("SELECT busId, plateno, totalcapacity FROM bus")
        buses = cursor.fetchall()
        
        # Only show seats that are currently booked/active
        cursor.execute("""
            SELECT bookingId, userId, busId, seatingno, ticket_ref, amount_paid 
            FROM booking WHERE status = 'Active' OR status IS NULL
        """)
        bookings_list = cursor.fetchall()
        
        cursor.close(); db.close()
        return render_template('mainpage.html', user_name=session['user_name'], buses=buses, bookings=bookings_list)
    except Exception as e:
        return f"Database Error: {e}"

# Admin panel logic
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Count buses, active bookings, and users for the cards
        cursor.execute("SELECT COUNT(*) as total FROM bus")
        bus_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM booking WHERE status = 'Active' OR status IS NULL")
        booking_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM users")
        passenger_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT SUM(amount_paid) as total FROM booking")
        rev_res = cursor.fetchone()
        total_revenue = rev_res['total'] if rev_res['total'] else 0.0

        # List of all passengers
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_raw = cursor.fetchall()
        passengers = [tuple(p.values()) for p in passengers_raw]

        # Get fleet details
        cursor.execute("SELECT busId, plateno, totalcapacity FROM bus")
        all_buses = cursor.fetchall()

        # Show who is currently on which bus
        cursor.execute("""
            SELECT b.bookingId, b.seatingno, u.fname, u.lname, b.bookingdate, b.busId 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.status = 'Active' OR b.status IS NULL
        """)
        bus_passengers = cursor.fetchall()

        # Get full history for reports
        cursor.execute("""
            SELECT b.bookingdate, u.fname, u.lname, b.seatingno, b.busId, b.amount_paid 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            ORDER BY b.bookingdate DESC
        """)
        all_bookings = cursor.fetchall()

        cursor.close(); db.close()
        
        return render_template('dashboards.html', 
                               bus_count=bus_count,
                               booking_count=booking_count,
                               passenger_count=passenger_count,
                               total_revenue=total_revenue,
                               passengers=passengers,
                               all_buses=all_buses,
                               bus_passengers=bus_passengers,
                               all_bookings=all_bookings)
    except Exception as e:
        return f"Admin Dashboard Error: {e}"

# Add a new bus to the database
@app.route('/add_bus', methods=['POST'])
def add_bus():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    
    plateno = request.form.get('plateno')
    capacity = request.form.get('capacity')

    try:
        db = get_db()
        cursor = db.cursor()
        sql = "INSERT INTO bus (plateno, totalcapacity) VALUES (%s, %s)"
        cursor.execute(sql, (plateno, capacity))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error adding bus: {e}"

# Remove a bus and its bookings
@app.route('/delete_bus/<int:bus_id>')
def delete_bus(bus_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM booking WHERE busId = %s", (bus_id,))
        cursor.execute("DELETE FROM bus WHERE busId = %s", (bus_id,))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error deleting bus: {e}"

# Clear seats once a trip is done
@app.route('/finish_trip/<int:bus_id>')
def finish_trip(bus_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE booking SET status = 'Completed' WHERE busId = %s AND (status = 'Active' OR status IS NULL)", (bus_id,))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error finishing trip: {e}"

# Delete a single booking
@app.route('/cancel_booking/<int:booking_id>')
def cancel_booking(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM booking WHERE bookingId = %s", (booking_id,))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('main_page'))
    except Exception as e:
        return f"Cancellation Error: {e}"

# Wipe a user from the system
@app.route('/delete_user/<int:user_id>')
def delete_user(user_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM booking WHERE userId = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE userId = %s", (user_id,))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Delete Error: {e}"

# Admin adding a user manually
@app.route('/add_user', methods=['POST'])
def add_user():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    phone = request.form.get('phone_number')
    email = request.form.get('email')
    gender = request.form.get('gender')
    plain_pin = request.form.get('user_pin')
    hashed_pin = generate_password_hash(plain_pin)

    try:
        db = get_db()
        cursor = db.cursor()
        sql = "INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(sql, (fname, lname, phone, email, gender, hashed_pin))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error adding user: {e}"

# Public signup logic
@app.route('/signup', methods=['POST'])
def signup():
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    phone = request.form.get('phone_number')
    email = request.form.get('email')
    gender = request.form.get('gender')
    plain_pin = request.form.get('user_pin')
    hashed_pin = generate_password_hash(plain_pin)

    try:
        db = get_db()
        cursor = db.cursor()
        # Check if phone is already taken
        cursor.execute("SELECT userId FROM users WHERE phone_number = %s", (phone,))
        if cursor.fetchone():
            cursor.close(); db.close()
            return render_template('BusSeatReservationSystem(vs).html', error="Phone number already exists")

        sql = "INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(sql, (fname, lname, phone, email, gender, hashed_pin))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('index'))
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Signup failed.")

# Mark a specific booking as done
@app.route('/complete_trip/<int:booking_id>')
def complete_trip(booking_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE booking SET status = 'Completed' WHERE bookingId = %s", (booking_id,))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Update Error: {e}"

# Handle the seat booking process
@app.route('/process_booking', methods=['POST'])
def process_booking():
    if 'user_id' not in session: return redirect(url_for('index'))
    user_id = session['user_id']
    bus_id = request.form.get('busId'); seat_no = request.form.get('seatingno')
    amount = request.form.get('amount_paid'); ticket_ref = str(uuid.uuid4())[:8].upper()

    try:
        db = get_db()
        cursor = db.cursor()
        sql = """INSERT INTO booking (userId, busId, seatingno, amount_paid, ticket_ref, bookingdate, status) 
                 VALUES (%s, %s, %s, %s, %s, %s, 'Active')"""
        cursor.execute(sql, (user_id, bus_id, seat_no, amount, ticket_ref, datetime.now()))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('main_page'))
    except Exception as e:
        return f"Booking Error: {e}"

# Clear session and go home
@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)