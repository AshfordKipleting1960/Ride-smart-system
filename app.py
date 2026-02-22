from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import uuid 
from datetime import datetime
# NEW: Import for hashing and verification
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'ridesmart_secret_key'

# Database Connection
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="12345678910", 
        database="ridesmart_db"
    )

@app.route('/')
def index():
    return render_template('BusSeatReservationSystem(vs).html')

@app.route('/login', methods=['POST'])
def login():
    phone = request.form.get('phone_number')
    pin = request.form.get('user_pin')

    # Admin bypass
    if phone == "0712345678" and pin == "9999":
        session['user_id'] = 'ADMIN'
        session['user_name'] = 'System Admin'
        return redirect(url_for('admin_dashboard'))

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # We only fetch the record by phone number first
        cursor.execute("SELECT userId, fname, user_pin FROM users WHERE phone_number = %s", (phone,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        # check_password_hash compares the typed 'pin' with the 'hashed pin' in the DB
        if user and check_password_hash(user['user_pin'], pin):
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']
            return redirect(url_for('main_page'))
        
        # MODIFIED: Instead of returning a string, we pass the error to the template
        return render_template('BusSeatReservationSystem(vs).html', error="Invalid phone number or PIN")
        
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Database connection failed")

@app.route('/main_page')
def main_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT busId, plateno, totalcapacity FROM bus")
        buses = cursor.fetchall()
        
        # Structure Preserved: Fetching bookings for the map
        cursor.execute("""
            SELECT bookingId, userId, busId, seatingno, ticket_ref, amount_paid 
            FROM booking WHERE status = 'Active' OR status IS NULL
        """)
        bookings_list = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        return render_template('mainpage.html', 
                               user_name=session['user_name'], 
                               buses=buses, 
                               bookings=bookings_list)
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # 1. Stats Calculation
        cursor.execute("SELECT COUNT(*) as total FROM bus")
        bus_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM booking WHERE status = 'Active' OR status IS NULL")
        booking_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM users")
        passenger_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT SUM(amount_paid) as total FROM booking")
        rev_res = cursor.fetchone()
        total_revenue = rev_res['total'] if rev_res['total'] else 0.0

        # 2. Passenger Registrations
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_raw = cursor.fetchall()
        passengers = [tuple(p.values()) for p in passengers_raw]

        # 3. Dynamic Fleet Data
        cursor.execute("SELECT busId, plateno FROM bus")
        all_buses = cursor.fetchall()

        cursor.execute("""
            SELECT b.bookingId, b.seatingno, u.fname, u.lname, b.bookingdate, b.busId 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.status = 'Active' OR b.status IS NULL
        """)
        bus_passengers = cursor.fetchall()

        # 4. Reports (Logic for the "Booking Reports" tab)
        cursor.execute("""
            SELECT b.bookingId, b.bookingdate, u.fname, u.lname, b.seatingno, b.busId, b.amount_paid 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.status = 'Active' OR b.status IS NULL
            ORDER BY b.bookingdate DESC
        """)
        active_bookings = cursor.fetchall()

        cursor.execute("""
            SELECT b.bookingId, b.bookingdate, u.fname, u.lname, b.seatingno, b.busId, b.amount_paid 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.status = 'Completed'
            ORDER BY b.bookingdate DESC
        """)
        completed_history = cursor.fetchall()

        cursor.close()
        db.close()
        
        return render_template('dashboards.html', 
                               bus_count=bus_count,
                               booking_count=booking_count,
                               passenger_count=passenger_count,
                               total_revenue=total_revenue,
                               passengers=passengers,
                               all_buses=all_buses,
                               bus_passengers=bus_passengers,
                               active_bookings=active_bookings,
                               completed_history=completed_history)
    except Exception as e:
        return f"Admin Dashboard Error: {e}"

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
        cursor.execute("SELECT userId FROM users WHERE phone_number = %s", (phone,))
        if cursor.fetchone():
            cursor.close(); db.close()
            # MODIFIED: Redirect to main page with error
            return render_template('BusSeatReservationSystem(vs).html', error="Phone number already exists")

        sql = """INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) 
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        cursor.execute(sql, (fname, lname, phone, email, gender, hashed_pin))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('index'))
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Signup failed. Please try again.")

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

@app.route('/process_booking', methods=['POST'])
def process_booking():
    if 'user_id' not in session: return redirect(url_for('index'))
    user_id = session['user_id']
    bus_id = request.form.get('busId')
    seat_no = request.form.get('seatingno')
    amount = request.form.get('amount_paid')
    ticket_ref = str(uuid.uuid4())[:8].upper()

    try:
        db = get_db()
        cursor = db.cursor()
        # Explicitly set status to Active for new bookings
        sql = """INSERT INTO booking (userId, busId, seatingno, amount_paid, ticket_ref, bookingdate, status) 
                 VALUES (%s, %s, %s, %s, %s, %s, 'Active')"""
        cursor.execute(sql, (user_id, bus_id, seat_no, amount, ticket_ref, datetime.now()))
        db.commit()
        cursor.close(); db.close()
        return redirect(url_for('main_page'))
    except Exception as e:
        return f"Booking Error: {e}"

@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)