from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import uuid 
import base64
import requests
from datetime import datetime
from requests.auth import HTTPBasicAuth
# Bringing in security helpers to keep user passwords safe
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'ridesmart_secret_key'

#  MPESA API KEYS & CONFIG 
MPESA_CONSUMER_KEY = 'B0zxwLToNfvnwXHKfaZL7cf0iADgI93PmIv7pOoEGCFv8DlN'
MPESA_CONSUMER_SECRET = 'kbtkz4vDFmENujgdeHQ4d0TR8xSsHuWn18Wpn3nnLdvsBx9XoLcIiAGms1wJUn7P'
MPESA_PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
MPESA_SHORTCODE = '174379'

# Update this NGROK_URL whenever you restart your tunnel
NGROK_URL = "https://thao-gnarly-reverberantly.ngrok-free.dev"

# Creating a fresh connection to the local MySQL database
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="12345678910", 
        database="ridesmart_db"
    )

#  MPESA INTEGRATION 

# Reaching out to Safaricom to get a temporary authorization token
def get_access_token():
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        response = requests.get(url, auth=HTTPBasicAuth(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET))
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            print(f"M-Pesa Auth Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

# Encoding the password string required for the STK Push
def generate_password(shortcode, passkey, timestamp):
    data_to_encode = shortcode + passkey + timestamp
    return base64.b64encode(data_to_encode.encode()).decode('utf-8')

# Landing page route
@app.route('/')
def index():
    success = request.args.get('success')
    return render_template('BusSeatReservationSystem(vs).html', success=success)

# Handling the login process for both Admins and Passengers
@app.route('/login', methods=['POST'])
def login():
    phone = request.form.get('phone_number')
    pin = request.form.get('user_pin')

    # Quick check for hardcoded admin credentials
    if phone == "0712345678" and pin == "9999":
        session['user_id'] = 'ADMIN'
        session['user_name'] = 'System Admin'
        return redirect(url_for('admin_dashboard'))

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Pulling user data to verify the hashed PIN
        cursor.execute("SELECT userId, fname, user_pin, phone_number FROM users WHERE phone_number = %s", (phone,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user['user_pin'], pin):
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']
            session['user_phone'] = user['phone_number'] # Keeping this for M-Pesa prompts
            return redirect(url_for('main_page'))
        
        return render_template('BusSeatReservationSystem(vs).html', error="Invalid phone number or PIN")
        
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Database connection failed")

# The main view for logged-in users to see buses and their own bookings
@app.route('/main_page')
def main_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT busId, plateno, totalcapacity FROM bus")
        buses = cursor.fetchall()
        
        # Security Gate: Making sure users only see their own active or past bookings
        cursor.execute("""
            SELECT bookingId, userId, busId, seatingno, ticket_ref, amount_paid, status 
            FROM booking WHERE userId = %s AND (status = 'Completed' OR status = 'Pending' OR status = 'Active')
        """, (session['user_id'],))
        bookings_list = cursor.fetchall()
        
        cursor.close()
        db.close()
        return render_template('mainpage.html', user_name=session['user_name'], buses=buses, bookings=bookings_list)
    except Exception as e:
        return f"Database Error: {e}"

# Dashboard for managing the entire system
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # Gathering high-level system stats
        cursor.execute("SELECT COUNT(*) as total FROM bus")
        bus_count = cursor.fetchone()['total']
        
        # Including Pending, Completed, and Active bookings in the total count
        cursor.execute("SELECT COUNT(*) as total FROM booking WHERE status IN ('Completed', 'Pending', 'Active')")
        booking_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM users")
        passenger_count = cursor.fetchone()['total']
        
        cursor.execute("SELECT SUM(amount_paid) as total FROM booking WHERE status = 'Completed'")
        rev_res = cursor.fetchone()
        total_revenue = rev_res['total'] if rev_res['total'] else 0.0
        
        # Fetching passenger list
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_raw = cursor.fetchall()
        passengers = [tuple(p.values()) for p in passengers_raw]
        
        cursor.execute("SELECT busId, plateno, totalcapacity FROM bus")
        all_buses = cursor.fetchall()
        
        # Fetching all booking details to show in the Fleet Management view
        cursor.execute("""
            SELECT b.bookingId, b.seatingno, u.fname, u.lname, b.bookingdate, b.busId, b.status
            FROM booking b
            JOIN users u ON b.userId = u.userId
            ORDER BY b.bookingdate DESC
        """)
        bus_passengers = cursor.fetchall()
        
        # Compiling the full booking history for reporting
        cursor.execute("""
            SELECT b.bookingdate, u.fname, u.lname, b.seatingno, b.busId, b.amount_paid, b.status 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            ORDER BY b.bookingdate DESC
        """)
        all_bookings = cursor.fetchall()
        
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
                               all_bookings=all_bookings)
    except Exception as e:
        return f"Admin Dashboard Error: {e}"

# Logic for adding a new vehicle to the system
@app.route('/add_bus', methods=['POST'])
def add_bus():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    plateno = request.form.get('plateno')
    capacity = request.form.get('capacity')
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO bus (plateno, totalcapacity) VALUES (%s, %s)", (plateno, capacity))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e: 
        return f"Error adding bus: {e}"

# Removing a bus and cleaning up any associated bookings
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
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e: 
        return f"Error deleting bus: {e}"

# Marks all current bookings as 'Completed' when a bus reaches its destination
@app.route('/finish_trip/<int:bus_id>')
def finish_trip(bus_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN': 
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE booking SET status = 'Completed' WHERE busId = %s AND (status = 'Active' OR status IS NULL OR status = 'Pending')", (bus_id,))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e: 
        return f"Error finishing trip: {e}"

# Deletes a specific booking entry
@app.route('/cancel_booking/<int:booking_id>')
def cancel_booking(booking_id):
    if 'user_id' not in session: 
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM booking WHERE bookingId = %s", (booking_id,))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('main_page'))
    except Exception as e: 
        return f"Cancellation Error: {e}"

# Fully removes a user account and their history from the database
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
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e: 
        return f"Delete Error: {e}"

# Form logic for an admin to manually create a new user account
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
        cursor.execute("INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) VALUES (%s, %s, %s, %s, %s, %s)", (fname, lname, phone, email, gender, hashed_pin))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e: 
        return f"Error adding user: {e}"

# Public registration for new passengers
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
        # Checking if the phone number is already registered
        cursor.execute("SELECT userId FROM users WHERE phone_number = %s", (phone,))
        if cursor.fetchone():
            cursor.close()
            db.close()
            return render_template('BusSeatReservationSystem(vs).html', error="Phone number already exists")
        cursor.execute("INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) VALUES (%s, %s, %s, %s, %s, %s)", (fname, lname, phone, email, gender, hashed_pin))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('index', success='true'))
    except Exception as e: 
        return render_template('BusSeatReservationSystem(vs).html', error="Signup failed.")

# Manually setting a single booking status to 'Completed'
@app.route('/complete_trip/<int:booking_id>')
def complete_trip(booking_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN': 
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE booking SET status = 'Completed' WHERE bookingId = %s", (booking_id,))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e: 
        return f"Update Error: {e}"

# Creating a booking record and triggering the M-Pesa payment prompt
@app.route('/process_booking', methods=['POST'])
def process_booking():
    if 'user_id' not in session: 
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    bus_id = request.form.get('busId')
    seat_no = request.form.get('seatingno')
    amount = request.form.get('amount_paid')
    ticket_ref = str(uuid.uuid4())[:8].upper()
    phone = session.get('user_phone')

    if not phone:
        return "Error: No phone found in session. Please log out and back inside."

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # RESTORED LOGIC: Check if user already has an active or pending booking
        cursor.execute("""
            SELECT bookingId FROM booking 
            WHERE userId = %s AND status IN ('Pending', 'Active')
        """, (user_id,))
        if cursor.fetchone():
            cursor.close()
            db.close()
            return "Error: You already have an active booking. You can only book once."

        access_token = get_access_token()
        if not access_token:
            cursor.close()
            db.close()
            return "Error: Could not connect to Safaricom."
            
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password = generate_password(MPESA_SHORTCODE, MPESA_PASSKEY, timestamp)
        formatted_phone = '254' + phone[1:] if phone.startswith('0') else phone

        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {
            "BusinessShortCode": MPESA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": formatted_phone,
            "PartyB": MPESA_SHORTCODE,
            "PhoneNumber": formatted_phone,
            "CallBackURL": f"{NGROK_URL}/callback",
            "AccountReference": ticket_ref,
            "TransactionDesc": f"Seat {seat_no} Booking"
        }

        # Requesting the STK Push from Safaricom
        response = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=payload, headers=headers)
        res_data = response.json()
        checkout_id = res_data.get('CheckoutRequestID')

        # Saving the booking as 'Pending' while we wait for payment confirmation
        sql = """INSERT INTO booking (userId, busId, seatingno, amount_paid, ticket_ref, bookingdate, status, checkout_id) 
                  VALUES (%s, %s, %s, %s, %s, %s, 'Pending', %s)"""
        cursor.execute(sql, (user_id, bus_id, seat_no, amount, ticket_ref, datetime.now(), checkout_id))
        db.commit()
        cursor.close()
        db.close()
        
        return redirect(url_for('main_page'))
    except Exception as e:
        return f"Booking Error: {e}"

# Catching the automated response from M-Pesa to confirm successful payments
@app.route('/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    stk_callback = data.get('Body', {}).get('stkCallback', {})
    result_code = stk_callback.get('ResultCode')
    checkout_id = stk_callback.get('CheckoutRequestID')

    # ResultCode 0 means the user successfully entered their PIN and paid
    if result_code == 0:
        try:
            db = get_db()
            cursor = db.cursor()
            update_query = "UPDATE booking SET status = 'Active' WHERE checkout_id = %s"
            cursor.execute(update_query, (checkout_id,))
            db.commit()
            cursor.close()
            db.close()
        except Exception as e:
            print(f"Database Callback Error: {e}")

    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})

# Clearing user data from the session
@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)