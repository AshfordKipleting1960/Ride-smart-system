from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import uuid
import base64
import requests
import re
from datetime import datetime
from requests.auth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'ridesmart_secret_key'

# M-Pesa sandbox credentials 
MPESA_CONSUMER_KEY = 'B0zxwLToNfvnwXHKfaZL7cf0iADgI93PmIv7pOoEGCFv8DlN'
MPESA_CONSUMER_SECRET = 'kbtkz4vDFmENujgdeHQ4d0TR8xSsHuWn18Wpn3nnLdvsBx9XoLcIiAGms1wJUn7P'
MPESA_PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
MPESA_SHORTCODE = '174379'

# ngrok tunnel URL for the M-Pesa callback 
NGROK_URL = "https://untying-studio-paparazzi.ngrok-free.dev"

# Hardcoded admin credentials 
ADMIN_PHONE = "0712345678"
ADMIN_PIN_HASH = generate_password_hash("9999")


def get_db():
    # Simple DB factory 
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="12345678910",
        database="ridesmart_db"
    )


def get_access_token():
    # Hit the Safaricom OAuth endpoint to get a short-lived bearer token
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        response = requests.get(url, auth=HTTPBasicAuth(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET))
        if response.status_code == 200:
            return response.json().get('access_token')
        else:
            print(f"[MPESA] Auth failed: {response.status_code} — {response.text}")
            return None
    except Exception as e:
        print(f"[MPESA] Couldn't reach Safaricom: {e}")
        return None


def generate_password(shortcode, passkey, timestamp):
    # M-Pesa requires a base64-encoded string of shortcode + passkey + timestamp
    data_to_encode = shortcode + passkey + timestamp
    return base64.b64encode(data_to_encode.encode()).decode('utf-8')


# Quick regex validators
def is_valid_email(email):
    return re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) is not None

def is_valid_phone(phone):
    return re.match(r'^0[0-9]{9}$', phone) is not None


@app.route('/')
def landing():
    if 'user_id' in session:
        return redirect(url_for('main_page'))
    return render_template('landing_page.html')


@app.route('/login_page')
def index():
    success = request.args.get('success')
    return render_template('BusSeatReservationSystem(vs).html', success=success)


@app.route('/login', methods=['POST'])
def login():
    phone = request.form.get('phone_number', '').strip()
    pin = request.form.get('user_pin', '').strip()

    if not phone or not pin:
        return render_template('BusSeatReservationSystem(vs).html', error="Phone and PIN are required")
    if not is_valid_phone(phone):
        return render_template('BusSeatReservationSystem(vs).html', error="Enter a valid 10-digit phone number")
    if len(pin) != 4 or not pin.isdigit():
        return render_template('BusSeatReservationSystem(vs).html', error="PIN must be exactly 4 digits")

    # Admin shortcut 
    if phone == ADMIN_PHONE and check_password_hash(ADMIN_PIN_HASH, pin):
        session['user_id'] = 'ADMIN'
        session['user_name'] = 'System Admin'
        return redirect(url_for('admin_dashboard'))

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT userId, fname, user_pin, phone_number FROM users WHERE phone_number = %s", (phone,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user['user_pin'], pin):
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']
            session['user_phone'] = user['phone_number']
            return redirect(url_for('main_page'))

        return render_template('BusSeatReservationSystem(vs).html', error="Invalid phone number or PIN")
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Database connection failed")


@app.route('/main_page')
def main_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    pickup = request.args.get('pickup', '').strip()
    destination_search = request.args.get('destination', '').strip()
    searched = request.args.get('searched')
    booking_error = request.args.get('booking_error')
    booking_success = request.args.get('booking_success')
    profile_error = request.args.get('profile_error')
    profile_success = request.args.get('profile_success')
    show_profile = request.args.get('show_profile')

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        buses = []
        if searched and pickup and destination_search:
            cursor.execute(
                "SELECT busId, plateno, totalcapacity, startlocation, destination, fare FROM bus WHERE startlocation = %s AND destination = %s",
                (pickup, destination_search)
            )
            buses = cursor.fetchall()

        cursor.execute(
            "SELECT bookingId, checkout_id FROM booking WHERE userId = %s AND status = 'Pending'",
            (session['user_id'],)
        )
        pending_booking = cursor.fetchone()

        # All confirmed bookings for this user
        cursor.execute("""
            SELECT bookingId, userId, busId, seatingno, ticket_ref, amount_paid, status
            FROM booking WHERE userId = %s AND (status = 'Completed' OR status = 'Active' OR status = 'Paid')
        """, (session['user_id'],))
        bookings_list = cursor.fetchall()

        # All active bookings across all users 
        cursor.execute("""
            SELECT busId, seatingno
            FROM booking
            WHERE status IN ('Active', 'Paid', 'Pending')
        """)
        all_bus_bookings = cursor.fetchall()

        cursor.execute(
            "SELECT userId, fname, lname, email, phone_number, gender FROM users WHERE userId = %s",
            (session['user_id'],)
        )
        profile_data = cursor.fetchone()

        cursor.close()
        db.close()

        return render_template('mainpage.html',
                               user_name=session['user_name'],
                               buses=buses,
                               bookings=bookings_list,
                               all_bus_bookings=all_bus_bookings,
                               pending=pending_booking,
                               searched=searched,
                               pickup=pickup,
                               destination_search=destination_search,
                               booking_error=booking_error,
                               booking_success=booking_success,
                               profile_data=profile_data,
                               profile_error=profile_error,
                               profile_success=profile_success,
                               show_profile=show_profile)
    except Exception as e:
        return f"Database Error: {e}"


@app.route('/verify_payment/<checkout_id>')
def verify_payment(checkout_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    access_token = get_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = generate_password(MPESA_SHORTCODE, MPESA_PASSKEY, timestamp)

    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_id
    }

    response = requests.post(
        "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json=payload, headers=headers
    )
    res_data = response.json()

    # ResultCode 0 means payment went through 
    if res_data.get('ResultCode') == "0":
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE booking SET status = 'Active' WHERE checkout_id = %s", (checkout_id,))
        db.commit()
        cursor.close()
        db.close()

    return redirect(url_for('main_page'))


@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) as total FROM bus")
        bus_count = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM booking")
        booking_count = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM users")
        passenger_count = cursor.fetchone()['total']

        # Only count revenue from paid bookings 
        cursor.execute("SELECT SUM(amount_paid) as total FROM booking WHERE status IN ('Completed', 'Active', 'Paid')")
        rev_res = cursor.fetchone()
        total_revenue = rev_res['total'] if rev_res['total'] else 0.0

        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_raw = cursor.fetchall()
        passengers = [tuple(p.values()) for p in passengers_raw]

        cursor.execute("SELECT busId, plateno, totalcapacity, startlocation, destination, fare FROM bus")
        all_buses = cursor.fetchall()

        cursor.execute("""
            SELECT b.bookingId, b.seatingno, u.fname, u.lname, b.bookingdate, b.busId, b.status
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.status IN ('Active', 'Paid', 'Completed')
            ORDER BY b.bookingdate DESC
        """)
        bus_passengers = cursor.fetchall()

        cursor.execute("""
            SELECT b.bookingId, b.bookingdate, u.fname, u.lname, b.seatingno, b.busId, b.amount_paid, b.status
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


@app.route('/add_bus', methods=['POST'])
def add_bus():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    plateno = request.form.get('plateno')
    capacity = request.form.get('totalcapacity')
    startlocation = request.form.get('startlocation')
    destination = request.form.get('destination')
    fare = request.form.get('fare')
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO bus (plateno, totalcapacity, startlocation, destination, fare) VALUES (%s, %s, %s, %s, %s)",
            (plateno, capacity, startlocation, destination, fare)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error adding bus: {e}"


@app.route('/delete_bus/<int:bus_id>')
def delete_bus(bus_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        # Delete bookings before the bus to avoid FK constraint errors
        cursor.execute("DELETE FROM booking WHERE busId = %s", (bus_id,))
        cursor.execute("DELETE FROM bus WHERE busId = %s", (bus_id,))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error deleting bus: {e}"


@app.route('/finish_trip/<int:bus_id>')
def finish_trip(bus_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE booking SET status = 'Completed' WHERE busId = %s AND (status = 'Active' OR status = 'Paid' OR status = 'Pending')",
            (bus_id,)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error finishing trip: {e}"


@app.route('/delete_booking/<int:booking_id>')
def delete_booking(booking_id):
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM booking WHERE bookingId = %s", (booking_id,))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error removing booking: {e}"


@app.route('/cancel_booking/<int:booking_id>')
def cancel_booking(booking_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # Fetch the ticket_ref so that one can cancel ALL seats from the same booking group
        cursor.execute(
            "SELECT ticket_ref FROM booking WHERE bookingId = %s AND userId = %s",
            (booking_id, session['user_id'])
        )
        row = cursor.fetchone()

        if row and row['ticket_ref']:
            # Cancel every seat that shares the same ticket reference 
            cursor.execute(
                "DELETE FROM booking WHERE ticket_ref = %s AND userId = %s",
                (row['ticket_ref'], session['user_id'])
            )
        else:
            # Fallback: cancel just this single booking
            cursor.execute(
                "DELETE FROM booking WHERE bookingId = %s AND userId = %s",
                (booking_id, session['user_id'])
            )

        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('main_page'))
    except Exception as e:
        return f"Cancellation Error: {e}"


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


@app.route('/add_user', methods=['POST'])
def add_user():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    phone = request.form.get('phone')
    plain_pin = request.form.get('password')
    hashed_pin = generate_password_hash(plain_pin)
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO users (fname, lname, phone_number, user_pin) VALUES (%s, %s, %s, %s)",
            (fname, lname, phone, hashed_pin)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Error adding user: {e}"


@app.route('/signup', methods=['POST'])
def signup():
    fname = request.form.get('fname', '').strip()
    lname = request.form.get('lname', '').strip()
    phone = request.form.get('phone_number', '').strip()
    email = request.form.get('email', '').strip()
    gender = request.form.get('gender', '').strip()
    plain_pin = request.form.get('user_pin', '').strip()

    if not all([fname, lname, phone, email, gender, plain_pin]):
        return render_template('BusSeatReservationSystem(vs).html', error="All fields are required")
    if not is_valid_phone(phone):
        return render_template('BusSeatReservationSystem(vs).html', error="Enter a valid 10-digit phone number")
    if not is_valid_email(email):
        return render_template('BusSeatReservationSystem(vs).html', error="Enter a valid email address")
    if len(plain_pin) != 4 or not plain_pin.isdigit():
        return render_template('BusSeatReservationSystem(vs).html', error="PIN must be exactly 4 digits")

    hashed_pin = generate_password_hash(plain_pin)
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT userId FROM users WHERE phone_number = %s", (phone,))
        if cursor.fetchone():
            cursor.close()
            db.close()
            return render_template('BusSeatReservationSystem(vs).html', error="Phone number already exists")
        cursor.execute(
            "INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) VALUES (%s, %s, %s, %s, %s, %s)",
            (fname, lname, phone, email, gender, hashed_pin)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('index', success='true'))
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Signup failed.")


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


@app.route('/process_booking', methods=['POST'])
def process_booking():
    """
    FEATURE 2: Multi-seat booking handler.

    The front-end now sends seatingno as a comma-separated string, e.g. "1A,1B,2C".
    A single checkout_id and ticket_ref covers the whole group, so one M-Pesa prompt
    is sent for the combined total.  Each individual seat gets its own booking row in
    the DB (seatingno stays a single value per row), preserving the existing schema.

    Single-seat bookings ("1A") continue to work exactly as before because
    splitting "1A" on commas still yields ["1A"].
    """
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id   = session['user_id']
    bus_id    = request.form.get('busId')
    seats_raw = request.form.get('seatingno', '').strip()   
    amount    = request.form.get('amount_paid')             

    # Parse the comma-separated seat list which filters out any empty tokens
    seat_list = [s.strip() for s in seats_raw.split(',') if s.strip()]

    print(f"[BOOKING] busId={bus_id}, seats={seat_list}, amount={amount}, userId={user_id}")

    phone = session.get('user_phone')
    if not phone:
        print("[BOOKING] No phone in session — user needs to log in again")
        return redirect(url_for('index'))

    if not bus_id or not seat_list or not amount:
        print(f"[BOOKING] Missing required field — busId={bus_id}, seats={seat_list}, amount={amount}")
        return redirect(url_for('main_page', booking_error='Booking submission incomplete. Please try again.'))

    # Shared reference for the whole group
    ticket_ref  = str(uuid.uuid4())[:8].upper()

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

       
        # Builds a parameterised IN clause that rejects the whole booking if any seat is taken.
        placeholders = ','.join(['%s'] * len(seat_list))
        cursor.execute(
            f"SELECT seatingno FROM booking WHERE busId = %s AND seatingno IN ({placeholders}) "
            f"AND status IN ('Active', 'Paid', 'Pending')",
            [bus_id] + seat_list
        )
        conflicts = cursor.fetchall()
        if conflicts:
            taken = ', '.join(r['seatingno'] for r in conflicts)
            cursor.close()
            db.close()
            print(f"[BOOKING] Conflict — seat(s) {taken} already taken")
            return redirect(url_for('main_page',
                                    booking_error=f'Seat(s) {taken} just got taken. Please select others.'))

        #db.start_transaction()

        # Clear any stale pending booking for this user before creating new ones
        cursor.execute("DELETE FROM booking WHERE userId = %s AND status = 'Pending'", (user_id,))

        #  M-Pesa STK Push for the combined amount 
        access_token = get_access_token()
        print(f"[MPESA] Access token: {'OK' if access_token else 'FAILED'}")

        if not access_token:
            db.rollback()
            cursor.close()
            db.close()
            return redirect(url_for('main_page', booking_error='Could not connect to M-Pesa. Please try again.'))

        timestamp      = datetime.now().strftime('%Y%m%d%H%M%S')
        password       = generate_password(MPESA_SHORTCODE, MPESA_PASSKEY, timestamp)
        formatted_phone = '254' + phone[1:] if phone.startswith('0') else phone

        headers = {"Authorization": f"Bearer {access_token}"}
        seat_desc = ', '.join(seat_list)
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
            "TransactionDesc": f"Seat(s) {seat_desc} Booking"
        }

        print(f"[MPESA] STK Push payload: {payload}")
        response = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload, headers=headers
        )
        res_data = response.json()
        print(f"[MPESA] STK Push response: {res_data}")

        checkout_id = res_data.get('CheckoutRequestID')
        if not checkout_id:
            print(f"[MPESA] No CheckoutRequestID — saving anyway: {res_data}")

        
        # Amount per seat = total / number of seats 
        fare_per_seat = request.form.get('fare_per_seat', amount)
        sql = """INSERT INTO booking (userId, busId, seatingno, amount_paid, ticket_ref, bookingdate, status, checkout_id)
                 VALUES (%s, %s, %s, %s, %s, %s, 'Pending', %s)"""

        for seat in seat_list:
            cursor.execute(sql, (user_id, bus_id, seat, fare_per_seat, ticket_ref, datetime.now(), checkout_id))

        db.commit()
        seat_count = len(seat_list)
        print(f"[BOOKING] {seat_count} seat(s) saved. ticket_ref={ticket_ref}, checkout_id={checkout_id}, status=Pending")
        cursor.close()
        db.close()

        seats_display = ', '.join(seat_list)
        return redirect(url_for('main_page',
                                booking_success=f'M-Pesa prompt sent! {seat_count} seat(s) reserved ({seats_display}). Ref: {ticket_ref}'))

    except Exception as e:
        print(f"[BOOKING] Exception: {e}")
        try:
            db.rollback()
        except:
            pass
        return redirect(url_for('main_page', booking_error='Booking failed. Please try again.'))


@app.route('/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    print(f"[CALLBACK] Received: {data}")
    stk_callback = data.get('Body', {}).get('stkCallback', {})
    result_code  = stk_callback.get('ResultCode')
    checkout_id  = stk_callback.get('CheckoutRequestID')

    print(f"[CALLBACK] ResultCode={result_code}, CheckoutRequestID={checkout_id}")

    if result_code == 0:
        try:
            db = get_db()
            cursor = db.cursor()
            # One checkout_id covers all seats in the group
            cursor.execute("UPDATE booking SET status = 'Active' WHERE checkout_id = %s", (checkout_id,))
            db.commit()
            print(f"[CALLBACK] Seats activated for checkout_id={checkout_id}")
            cursor.close()
            db.close()
        except Exception as e:
            print(f"[CALLBACK] DB error: {e}")

    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})


@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session or session['user_id'] == 'ADMIN':
        return redirect(url_for('index'))

    fname = request.form.get('fname', '').strip()
    lname = request.form.get('lname', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone_number', '').strip()

    if not all([fname, lname, email, phone]):
        return redirect(url_for('main_page', show_profile=1, profile_error='All fields are required'))
    if not is_valid_email(email):
        return redirect(url_for('main_page', show_profile=1, profile_error='Enter a valid email address'))
    if not is_valid_phone(phone):
        return redirect(url_for('main_page', show_profile=1, profile_error='Enter a valid 10-digit phone number'))

    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE users SET fname = %s, lname = %s, email = %s, phone_number = %s WHERE userId = %s",
            (fname, lname, email, phone, session['user_id'])
        )
        db.commit()
        cursor.close()
        db.close()
        # Keep session values in sync after a profile update
        session['user_name'] = fname
        session['user_phone'] = phone
        return redirect(url_for('main_page', show_profile=1, profile_success='Profile updated successfully'))
    except Exception as e:
        return redirect(url_for('main_page', show_profile=1, profile_error='Update failed. Please try again.'))


@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('landing'))


if __name__ == '__main__':
    app.run(debug=True)