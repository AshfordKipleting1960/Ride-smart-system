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

# These are the test credentials for the M-Pesa sandbox
MPESA_CONSUMER_KEY    = 'B0zxwLToNfvnwXHKfaZL7cf0iADgI93PmIv7pOoEGCFv8DlN'
MPESA_CONSUMER_SECRET = 'kbtkz4vDFmENujgdeHQ4d0TR8xSsHuWn18Wpn3nnLdvsBx9XoLcIiAGms1wJUn7P'
MPESA_PASSKEY         = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
MPESA_SHORTCODE       = '174379'

#  public URL so Safaricom can reach  local server
NGROK_URL = "https://untying-studio-paparazzi.ngrok-free.dev"

# Admin login — phone number and a hashed version of the PIN
ADMIN_PHONE    = "0712345678"
ADMIN_PIN_HASH = generate_password_hash("9999")


# Every route in our system is defined here.
# The key is the start and end point, and the value is every stop along the way.

ROUTE_DEFINITIONS = {
    # Each entry maps a start-end pair to the full list of stops on that route
    ('Kencom / CBD',    'Ngong Road'):        ['Kencom / CBD',    'Upper Hill',         'Kilimani',        'Ngong Road'],
    ('KNH (Hospital)',  'Kawangware'):        ['KNH (Hospital)',  'Dagoretti Corner',   'Kawangware'],
    ('Westlands',       'Kasarani'):          ['Westlands',       'CBD / Town',         'Pangani',         'Thika Road Mall',  'Kasarani'],
    ('Utawala',         'CBD / Ambassadeur'): ['Utawala',         'Ruai',               'Kayole',          'Umoja',            'CBD / Ambassadeur'],
    ('Kencom / CBD',    'Kawangware'):        ['Kencom / CBD',    'Dagoretti Corner',   'Kawangware'],
    ('Westlands',       'CBD / Ambassadeur'): ['Westlands',       'CBD / Town',         'CBD / Ambassadeur'],
    ('KNH (Hospital)',  'Ngong Road'):        ['KNH (Hospital)',  'Ngong Road'],
    ('Utawala',         'Kasarani'):          ['Utawala',         'Ruai',               'CBD / Town',      'Pangani',          'Kasarani'],
}

# Only 4 seats can be booked per bus, no matter how big the bus is
MAX_BOOKABLE_SEATS = 4


def get_route_stops(startlocation, destination):
    """Looks up the full list of stops for a given start and end point."""
    key = (startlocation, destination)
    return ROUTE_DEFINITIONS.get(key, [startlocation, destination])



# The fare a passenger pays depends on how far they travel along the route.
# If they only go part of the way, they pay less than the full fare.


def calculate_segment_fare(base_fare, route_stops, boarding_stop, dropoff_stop):
    """
    Works out how much a passenger should pay based on the segments they travel.

    Args:
        base_fare    (float): The full-route price set by the admin.
        route_stops  (list):  Every stop on the route, in order.
        boarding_stop (str):  Where the passenger gets on.
        dropoff_stop  (str):  Where the passenger gets off.

    Returns:
        float: The price for their specific journey, rounded to 2 decimal places.
    """
    if not boarding_stop or not dropoff_stop:
        return float(base_fare)

    if boarding_stop not in route_stops or dropoff_stop not in route_stops:
        return float(base_fare)

    boarding_idx = route_stops.index(boarding_stop)
    dropoff_idx  = route_stops.index(dropoff_stop)

    # The passenger must get on before they get off
    if boarding_idx >= dropoff_idx:
        return float(base_fare)

    total_segments    = len(route_stops) - 1          #  4 stops means 3 segments between them
    travelled_segments = dropoff_idx - boarding_idx   # how many segments the passenger actually travels

    if total_segments == 0:
        return float(base_fare)

    # Charge proportionally , travel 2 out of 3 segments, pay 2/3 of the fare
    segment_fare = (travelled_segments / total_segments) * float(base_fare)
    return round(segment_fare, 2)


def validate_stop_selection(route_stops, boarding_stop, dropoff_stop):
    """
    Checks that the passenger's chosen stops make sense for this route.

    Returns:
        (bool, str): True if everything is fine, or False with an explanation.
    """
    if not boarding_stop or not dropoff_stop:
        return False, "Boarding and drop-off stops are required."

    if boarding_stop not in route_stops:
        return False, f"Boarding stop '{boarding_stop}' is not on this route."

    if dropoff_stop not in route_stops:
        return False, f"Drop-off stop '{dropoff_stop}' is not on this route."

    if boarding_stop == dropoff_stop:
        return False, "Boarding and drop-off stops cannot be the same."

    boarding_idx = route_stops.index(boarding_stop)
    dropoff_idx  = route_stops.index(dropoff_stop)

    if boarding_idx >= dropoff_idx:
        return False, (
            f"Invalid direction: '{dropoff_stop}' comes before '{boarding_stop}' on this route. "
            f"Reverse travel is not permitted."
        )

    return True, ""


def get_db():
    """Opens a fresh connection to the MySQL database."""
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="12345678910",
        database="ridesmart_db"
    )


def get_access_token():
    """Asks Safaricom for a temporary access token so we can use the M-Pesa API."""
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        response = requests.get(url, auth=HTTPBasicAuth(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET))
        if response.status_code == 200:
            return response.json().get('access_token')
        print(f"[MPESA] Auth failed: {response.status_code} — {response.text}")
        return None
    except Exception as e:
        print(f"[MPESA] Couldn't reach Safaricom: {e}")
        return None


def generate_password(shortcode, passkey, timestamp):
    """Creates the encrypted password M-Pesa needs for every STK Push request."""
    data_to_encode = shortcode + passkey + timestamp
    return base64.b64encode(data_to_encode.encode()).decode('utf-8')


def is_valid_email(email):
    """Quick check to make sure the email looks like a real one."""
    return re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email) is not None

def is_valid_phone(phone):
    """Checks that the phone number starts with 0 and has exactly 10 digits."""
    return re.match(r'^0[0-9]{9}$', phone) is not None


# 
# Counts how many seats are currently taken on a bus (for the 4-seat limit)
def get_confirmed_booking_count(cursor, bus_id):
    """Returns the number of Active, Paid, or Pending bookings for a bus."""
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM booking WHERE busId = %s AND status IN ('Active','Paid','Pending')",
        (bus_id,)
    )
    return cursor.fetchone()['cnt']


# All the URL routes for the app
# 

@app.route('/')
def landing():
    # If the user is already logged in, skip the landing page
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
    pin   = request.form.get('user_pin', '').strip()

    # Make sure both fields are filled in
    if not phone or not pin:
        return render_template('BusSeatReservationSystem(vs).html', error="Phone and PIN are required")
    if not is_valid_phone(phone):
        return render_template('BusSeatReservationSystem(vs).html', error="Enter a valid 10-digit phone number")
    if len(pin) != 4 or not pin.isdigit():
        return render_template('BusSeatReservationSystem(vs).html', error="PIN must be exactly 4 digits")

    # Check if this is the admin logging in
    if phone == ADMIN_PHONE and check_password_hash(ADMIN_PIN_HASH, pin):
        session['user_id']   = 'ADMIN'
        session['user_name'] = 'System Admin'
        return redirect(url_for('admin_dashboard'))

    # Otherwise, look for a regular passenger account
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT userId, fname, user_pin, phone_number FROM users WHERE phone_number = %s", (phone,)
        )
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user and check_password_hash(user['user_pin'], pin):
            session['user_id']    = user['userId']
            session['user_name']  = user['fname']
            session['user_phone'] = user['phone_number']
            return redirect(url_for('main_page'))

        return render_template('BusSeatReservationSystem(vs).html', error="Invalid phone number or PIN")
    except Exception:
        return render_template('BusSeatReservationSystem(vs).html', error="Database connection failed")


@app.route('/main_page')
def main_page():
    # Only logged-in users can see this page
    if 'user_id' not in session:
        return redirect(url_for('index'))

    # Grab any parameters from the URL (search terms, error messages, etc.)
    pickup             = request.args.get('pickup', '').strip()
    destination_search = request.args.get('destination', '').strip()
    searched           = request.args.get('searched')
    booking_error      = request.args.get('booking_error')
    booking_success    = request.args.get('booking_success')
    profile_error      = request.args.get('profile_error')
    profile_success    = request.args.get('profile_success')
    show_profile       = request.args.get('show_profile')
    show_ticket        = request.args.get('show_ticket')

    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)

        # Only search for buses if the user clicked the Search button
        buses = []
        if searched and pickup and destination_search:
            cursor.execute(
                "SELECT busId, plateno, totalcapacity, startlocation, destination, fare "
                "FROM bus WHERE startlocation = %s AND destination = %s",
                (pickup, destination_search)
            )
            buses = cursor.fetchall()

        # For each bus found, add the route stops and how many seats are taken
        for bus in buses:
            bus['route_stops'] = get_route_stops(bus['startlocation'], bus['destination'])
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM booking "
                "WHERE busId = %s AND status IN ('Active','Paid','Pending')",
                (bus['busId'],)
            )
            bus['confirmed_count'] = cursor.fetchone()['cnt']
            bus['slots_left']      = max(0, MAX_BOOKABLE_SEATS - bus['confirmed_count'])
            bus['is_full']         = bus['slots_left'] == 0

            # Work out how many segments the route has (for fare calculation)
            total_stops = len(bus['route_stops'])
            bus['total_segments'] = max(0, total_stops - 1)

        # Check if the user has any unpaid bookings sitting around
        cursor.execute(
            "SELECT bookingId, checkout_id FROM booking WHERE userId = %s AND status = 'Pending'",
            (session['user_id'],)
        )
        pending_booking = cursor.fetchone()

        # Get all the user's confirmed or completed bookings
        cursor.execute("""
            SELECT bookingId, userId, busId, seatingno, ticket_ref, amount_paid, status,
                   boarding_stop, dropoff_stop
            FROM booking
            WHERE userId = %s AND status IN ('Completed', 'Active', 'Paid', 'Pending')
        """, (session['user_id'],))
        bookings_list = cursor.fetchall()

        # Get every active booking across all buses (so we can show which seats are taken)
        cursor.execute("""
            SELECT busId, seatingno
            FROM booking
            WHERE status IN ('Active', 'Paid', 'Pending')
        """)
        all_bus_bookings = cursor.fetchall()

        # Load the user's profile info for the profile panel
        cursor.execute(
            "SELECT userId, fname, lname, email, phone_number, gender FROM users WHERE userId = %s",
            (session['user_id'],)
        )
        profile_data = cursor.fetchone()

        cursor.close()
        db.close()

        return render_template(
            'mainpage.html',
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
            show_profile=show_profile,
            max_bookable=MAX_BOOKABLE_SEATS,
            show_ticket=show_ticket
        )
    except Exception as e:
        return f"Database Error: {e}"


@app.route('/verify_payment/<checkout_id>')
def verify_payment(checkout_id):
    """Manually checks with Safaricom whether a payment went through."""
    if 'user_id' not in session:
        return redirect(url_for('index'))

    access_token = get_access_token()
    timestamp    = datetime.now().strftime('%Y%m%d%H%M%S')
    password     = generate_password(MPESA_SHORTCODE, MPESA_PASSKEY, timestamp)

    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_id,
    }
    response = requests.post(
        "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
        json=payload, headers=headers
    )
    res_data = response.json()

    # If Safaricom says the payment succeeded, mark the booking as Active
    if res_data.get('ResultCode') == "0":
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE booking SET status = 'Active' WHERE checkout_id = %s", (checkout_id,)
        )
        db.commit()
        cursor.close()
        db.close()

    return redirect(url_for('main_page'))


@app.route('/admin_dashboard')
def admin_dashboard():
    """The admin control panel — only accessible with the admin account."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))

    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)

        # Get the big-picture numbers for the stat cards
        cursor.execute("SELECT COUNT(*) as total FROM bus")
        bus_count = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM booking")
        booking_count = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM users")
        passenger_count = cursor.fetchone()['total']

        cursor.execute(
            "SELECT SUM(amount_paid) as total FROM booking WHERE status IN ('Completed', 'Active', 'Paid')"
        )
        rev_res       = cursor.fetchone()
        total_revenue = rev_res['total'] if rev_res['total'] else 0.0

        # Get the full passenger list
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_raw = cursor.fetchall()
        passengers     = [tuple(p.values()) for p in passengers_raw]

        # Get every bus with its details
        cursor.execute(
            "SELECT busId, plateno, totalcapacity, startlocation, destination, fare FROM bus"
        )
        all_buses_raw = cursor.fetchall()

        # Add route stops and capacity info to each bus
        all_buses = []
        for bus in all_buses_raw:
            bus['route_stops']      = get_route_stops(bus['startlocation'], bus['destination'])
            bus['total_segments']   = max(0, len(bus['route_stops']) - 1)
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM booking "
                "WHERE busId = %s AND status IN ('Active','Paid','Pending')",
                (bus['busId'],)
            )
            bus['confirmed_count'] = cursor.fetchone()['cnt']
            bus['slots_left']      = max(0, MAX_BOOKABLE_SEATS - bus['confirmed_count'])
            bus['is_full']         = bus['slots_left'] == 0
            all_buses.append(bus)

        # Get the passenger manifest for each bus
        cursor.execute("""
            SELECT b.bookingId, b.seatingno, u.fname, u.lname, b.bookingdate, b.busId,
                   b.status, b.boarding_stop, b.dropoff_stop, b.amount_paid
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.status IN ('Active', 'Paid', 'Completed')
            ORDER BY b.bookingdate DESC
        """)
        bus_passengers = cursor.fetchall()

        # Attach route info to each booking so we can show the full journey
        for bp in bus_passengers:
            bus_data = next((b for b in all_buses if b['busId'] == bp['busId']), None)
            if bus_data:
                bp['route_stops']    = bus_data['route_stops']
                bp['total_segments'] = bus_data['total_segments']
            else:
                bp['route_stops']    = []
                bp['total_segments'] = 0

        # Get all bookings for the reports table
        cursor.execute("""
            SELECT b.bookingId, b.bookingdate, u.fname, u.lname, b.seatingno,
                   b.busId, b.amount_paid, b.status, b.boarding_stop, b.dropoff_stop
            FROM booking b
            JOIN users u ON b.userId = u.userId
            ORDER BY b.bookingdate DESC
        """)
        all_bookings = cursor.fetchall()

        # Attach route info to each report row too
        for ab in all_bookings:
            bus_data = next((b for b in all_buses if b['busId'] == ab['busId']), None)
            if bus_data:
                ab['route_stops']    = bus_data['route_stops']
                ab['total_segments'] = bus_data['total_segments']
            else:
                ab['route_stops']    = []
                ab['total_segments'] = 0

        cursor.close()
        db.close()

        return render_template(
            'dashboards.html',
            bus_count=bus_count,
            booking_count=booking_count,
            passenger_count=passenger_count,
            total_revenue=total_revenue,
            passengers=passengers,
            all_buses=all_buses,
            bus_passengers=bus_passengers,
            all_bookings=all_bookings,
            max_bookable=MAX_BOOKABLE_SEATS,
        )
    except Exception as e:
        return f"Admin Dashboard Error: {e}"


@app.route('/add_bus', methods=['POST'])
def add_bus():
    """Adds a new bus to the fleet. Only the admin can do this."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    plateno       = request.form.get('plateno')
    capacity      = request.form.get('totalcapacity')
    startlocation = request.form.get('startlocation')
    destination   = request.form.get('destination')
    fare          = request.form.get('fare')
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO bus (plateno, totalcapacity, startlocation, destination, fare) "
            "VALUES (%s, %s, %s, %s, %s)",
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
    """Removes a bus and all its bookings. Admin only."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db     = get_db()
        cursor = db.cursor()
        # Delete the bookings first, then the bus itself
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
    """Marks all active bookings on a bus as Completed. Admin only."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE booking SET status = 'Completed' "
            "WHERE busId = %s AND status IN ('Active','Paid','Pending')",
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
    """Deletes a single booking. Admin only."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db     = get_db()
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
    """Lets a passenger cancel their own booking."""
    if 'user_id' not in session:
        return redirect(url_for('index'))
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        # Find the ticket reference so we can cancel all seats booked together
        cursor.execute(
            "SELECT ticket_ref FROM booking WHERE bookingId = %s AND userId = %s",
            (booking_id, session['user_id'])
        )
        row = cursor.fetchone()
        if row and row['ticket_ref']:
            # Cancel every seat that shares this ticket reference
            cursor.execute(
                "DELETE FROM booking WHERE ticket_ref = %s AND userId = %s",
                (row['ticket_ref'], session['user_id'])
            )
        else:
            # Just cancel the single booking
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
    """Removes a user and all their bookings. Admin only."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db     = get_db()
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
    """Lets the admin manually create a new user account."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    fname      = request.form.get('fname')
    lname      = request.form.get('lname')
    phone      = request.form.get('phone')
    plain_pin  = request.form.get('password')
    # Never store the PIN as plain text — hash it first
    hashed_pin = generate_password_hash(plain_pin)
    try:
        db     = get_db()
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
    """Creates a new passenger account from the signup form."""
    fname     = request.form.get('fname', '').strip()
    lname     = request.form.get('lname', '').strip()
    phone     = request.form.get('phone_number', '').strip()
    email     = request.form.get('email', '').strip()
    gender    = request.form.get('gender', '').strip()
    plain_pin = request.form.get('user_pin', '').strip()

    # Check that everything is filled in and looks correct
    if not all([fname, lname, phone, email, gender, plain_pin]):
        return render_template('BusSeatReservationSystem(vs).html', error="All fields are required")
    if not is_valid_phone(phone):
        return render_template('BusSeatReservationSystem(vs).html', error="Enter a valid 10-digit phone number")
    if not is_valid_email(email):
        return render_template('BusSeatReservationSystem(vs).html', error="Enter a valid email address")
    if len(plain_pin) != 4 or not plain_pin.isdigit():
        return render_template('BusSeatReservationSystem(vs).html', error="PIN must be exactly 4 digits")

    # Hash the PIN before saving it to the database
    hashed_pin = generate_password_hash(plain_pin)
    try:
        db     = get_db()
        cursor = db.cursor()
        # Make sure this phone number isn't already registered
        cursor.execute("SELECT userId FROM users WHERE phone_number = %s", (phone,))
        if cursor.fetchone():
            cursor.close()
            db.close()
            return render_template('BusSeatReservationSystem(vs).html', error="Phone number already exists")
        cursor.execute(
            "INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (fname, lname, phone, email, gender, hashed_pin)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('index', success='true'))
    except Exception:
        return render_template('BusSeatReservationSystem(vs).html', error="Signup failed.")


@app.route('/complete_trip/<int:booking_id>')
def complete_trip(booking_id):
    """Marks a single booking as Completed. Admin only."""
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    try:
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE booking SET status = 'Completed' WHERE bookingId = %s", (booking_id,)
        )
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        return f"Update Error: {e}"



# API — called by JavaScript every 15 seconds to keep the seat map up to date
@app.route('/api/bus_slots/<int:bus_id>')
def bus_slots(bus_id):
    """Returns how many booking slots are still available on a specific bus."""
    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cnt    = get_confirmed_booking_count(cursor, bus_id)
        cursor.close()
        db.close()
        slots_left = max(0, MAX_BOOKABLE_SEATS - cnt)
        return jsonify({
            'busId':            bus_id,
            'confirmed_count':  cnt,
            'slots_left':       slots_left,
            'max_bookable':     MAX_BOOKABLE_SEATS,
            'is_full':          slots_left == 0,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# API — called when a passenger changes their boarding or drop-off stop

@app.route('/api/calculate_fare', methods=['POST'])
def calculate_fare_api():
    """
    Receives a bus ID and two stops, returns the calculated fare for that journey.
    """
    try:
        data          = request.get_json()
        bus_id        = data.get('busId')
        boarding_stop = data.get('boardingStop', '').strip()
        dropoff_stop  = data.get('dropoffStop', '').strip()

        db     = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT startlocation, destination, fare FROM bus WHERE busId = %s", (bus_id,))
        bus = cursor.fetchone()
        cursor.close()
        db.close()

        if not bus:
            return jsonify({'error': 'Bus not found'}), 404

        route_stops = get_route_stops(bus['startlocation'], bus['destination'])
        base_fare   = float(bus['fare']) if bus['fare'] else 0.0

        # Make sure the chosen stops are valid before calculating
        is_valid, err_msg = validate_stop_selection(route_stops, boarding_stop, dropoff_stop)
        if not is_valid:
            return jsonify({'error': err_msg, 'baseFare': base_fare, 'routeStops': route_stops})

        fare = calculate_segment_fare(base_fare, route_stops, boarding_stop, dropoff_stop)

        boarding_idx       = route_stops.index(boarding_stop)
        dropoff_idx        = route_stops.index(dropoff_stop)
        travelled_segments = dropoff_idx - boarding_idx
        total_segments     = len(route_stops) - 1

        return jsonify({
            'fare':               fare,
            'baseFare':           base_fare,
            'travelledSegments':  travelled_segments,
            'totalSegments':      total_segments,
            'routeStops':         route_stops,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/process_booking', methods=['POST'])
def process_booking():
    """
    The main booking handler. It:
      - Checks the 4-seat limit
      - Saves the boarding and drop-off stops
      - Calculates the fare based on distance
      - Validates that the stops are in the right order
      - Sends the M-Pesa STK Push
      - Creates the booking records in the database
    """
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id       = session['user_id']
    bus_id        = request.form.get('busId')
    seats_raw     = request.form.get('seatingno', '').strip()
    boarding_stop = request.form.get('boarding_stop', '').strip()
    dropoff_stop  = request.form.get('dropoff_stop', '').strip()

    # Split the comma-separated seat list into individual seat numbers
    seat_list = [s.strip() for s in seats_raw.split(',') if s.strip()]

    phone = session.get('user_phone')
    if not phone:
        return redirect(url_for('index'))

    if not bus_id or not seat_list:
        return redirect(url_for('main_page', booking_error='Booking submission incomplete. Please try again.'))

    # Create a short unique reference for the ticket
    ticket_ref = str(uuid.uuid4())[:8].upper()

    try:
        db     = get_db()
        cursor = db.cursor(dictionary=True)

        # Look up the bus to get its route and base fare
        cursor.execute(
            "SELECT busId, startlocation, destination, fare FROM bus WHERE busId = %s", (bus_id,)
        )
        bus = cursor.fetchone()
        if not bus:
            cursor.close()
            db.close()
            return redirect(url_for('main_page', booking_error='Bus not found.'))

        route_stops = get_route_stops(bus['startlocation'], bus['destination'])
        base_fare   = float(bus['fare']) if bus['fare'] else 0.0

        # If the route has intermediate stops, check the passenger's selection
        if len(route_stops) > 2:
            is_valid, err_msg = validate_stop_selection(route_stops, boarding_stop, dropoff_stop)
            if not is_valid:
                cursor.close()
                db.close()
                return redirect(url_for('main_page', booking_error=err_msg))
        else:
            # For direct routes, the only option is the full journey
            boarding_stop = route_stops[0]
            dropoff_stop  = route_stops[-1]

        # Work out the fare based on how many segments the passenger travels
        fare_per_seat = calculate_segment_fare(base_fare, route_stops, boarding_stop, dropoff_stop)
        amount        = fare_per_seat * len(seat_list)

        print(f"[BOOKING] busId={bus_id}, seats={seat_list}, "
              f"boarding={boarding_stop}, dropoff={dropoff_stop}, "
              f"baseFare={base_fare}, farePerSeat={fare_per_seat}, total={amount}, "
              f"userId={user_id}")

        # Make sure adding these seats won't go over the 4-seat limit
        current_count = get_confirmed_booking_count(cursor, bus_id)
        if current_count + len(seat_list) > MAX_BOOKABLE_SEATS:
            remaining = max(0, MAX_BOOKABLE_SEATS - current_count)
            cursor.close()
            db.close()
            if remaining == 0:
                msg = 'This bus is fully booked (max 4 seats). Please choose another bus.'
            else:
                msg = (f'Only {remaining} seat(s) left on this bus (max {MAX_BOOKABLE_SEATS}). '
                       f'Please select fewer seats.')
            return redirect(url_for('main_page', booking_error=msg))

        # Double-check that nobody else just grabbed these seats
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
            return redirect(url_for('main_page',
                                    booking_error=f'Seat(s) {taken} just got taken. Please select others.'))

        # Remove any old unpaid bookings for this user
        cursor.execute(
            "DELETE FROM booking WHERE userId = %s AND status = 'Pending'", (user_id,)
        )

        # Send the M-Pesa payment request to the user's phone
        access_token = get_access_token()
        if not access_token:
            db.rollback()
            cursor.close()
            db.close()
            return redirect(url_for('main_page',
                                    booking_error='Could not connect to M-Pesa. Please try again.'))

        timestamp       = datetime.now().strftime('%Y%m%d%H%M%S')
        password        = generate_password(MPESA_SHORTCODE, MPESA_PASSKEY, timestamp)
        # Convert 07XX... to 2547XX... for M-Pesa
        formatted_phone = '254' + phone[1:] if phone.startswith('0') else phone

        headers   = {"Authorization": f"Bearer {access_token}"}
        seat_desc = ', '.join(seat_list)

        stop_desc = f" ({boarding_stop}→{dropoff_stop})" if boarding_stop and dropoff_stop else ""

        payload   = {
            "BusinessShortCode": MPESA_SHORTCODE,
            "Password":          password,
            "Timestamp":         timestamp,
            "TransactionType":   "CustomerPayBillOnline",
            "Amount":            int(amount),   # M-Pesa needs a whole number
            "PartyA":            formatted_phone,
            "PartyB":            MPESA_SHORTCODE,
            "PhoneNumber":       formatted_phone,
            "CallBackURL":       f"{NGROK_URL}/callback",
            "AccountReference":  ticket_ref,
            "TransactionDesc":   f"Seat(s) {seat_desc}{stop_desc}",
        }

        response    = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
            json=payload, headers=headers
        )
        res_data    = response.json()
        checkout_id = res_data.get('CheckoutRequestID')

        # Save each seat as its own booking row, all linked by the same ticket reference
        sql = """
            INSERT INTO booking
                (userId, busId, seatingno, amount_paid, ticket_ref, bookingdate,
                 status, checkout_id, boarding_stop, dropoff_stop)
            VALUES (%s, %s, %s, %s, %s, %s, 'Pending', %s, %s, %s)
        """
        for seat in seat_list:
            cursor.execute(sql, (
                user_id, bus_id, seat, fare_per_seat,
                ticket_ref, datetime.now(), checkout_id,
                boarding_stop or None, dropoff_stop or None,
            ))

        db.commit()
        seat_count    = len(seat_list)
        seats_display = ', '.join(seat_list)
        cursor.close()
        db.close()

        stop_info = ''
        if boarding_stop and dropoff_stop:
            stop_info = f' ({boarding_stop} → {dropoff_stop})'

        # Send the user back with a success message
        return redirect(url_for(
            'main_page',
            booking_success=(
                f'M-Pesa prompt sent! {seat_count} seat(s) reserved ({seats_display})'
                f'{stop_info}. Fare: KES {fare_per_seat:,.0f}/seat. Ref: {ticket_ref}'
            ),
             show_ticket=ticket_ref
        ))

    except Exception as e:
        print(f"[BOOKING] Exception: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return redirect(url_for('main_page', booking_error='Booking failed. Please try again.'))


@app.route('/callback', methods=['POST'])
def mpesa_callback():
    """Safaricom calls this URL when a payment is confirmed or fails."""
    data         = request.get_json()
    stk_callback = data.get('Body', {}).get('stkCallback', {})
    result_code  = stk_callback.get('ResultCode')
    checkout_id  = stk_callback.get('CheckoutRequestID')

    # ResultCode 0 means the payment was successful
    if result_code == 0:
        try:
            db     = get_db()
            cursor = db.cursor()
            cursor.execute(
                "UPDATE booking SET status = 'Active' WHERE checkout_id = %s", (checkout_id,)
            )
            db.commit()
            cursor.close()
            db.close()
        except Exception as e:
            print(f"[CALLBACK] DB error: {e}")

    # Always respond with this so Safaricom knows we received the callback
    return jsonify({"ResultCode": 0, "ResultDesc": "Success"})


@app.route('/update_profile', methods=['POST'])
def update_profile():
    """Lets a passenger update their name, email, and phone number."""
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
        db     = get_db()
        cursor = db.cursor()
        cursor.execute(
            "UPDATE users SET fname=%s, lname=%s, email=%s, phone_number=%s WHERE userId=%s",
            (fname, lname, email, phone, session['user_id'])
        )
        db.commit()
        cursor.close()
        db.close()
        # Update the session so the navbar shows the new name immediately
        session['user_name']  = fname
        session['user_phone'] = phone
        return redirect(url_for('main_page', show_profile=1, profile_success='Profile updated successfully'))
    except Exception:
        return redirect(url_for('main_page', show_profile=1, profile_error='Update failed. Please try again.'))


@app.route('/signout')
def signout():
    """Logs the user out by clearing their session."""
    session.clear()
    return redirect(url_for('landing'))


if __name__ == '__main__':
    app.run(debug=True)