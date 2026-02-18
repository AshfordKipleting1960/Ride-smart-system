from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector

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

@app.route('/signup', methods=['POST'])
def signup():
    fname = request.form.get('fname')
    lname = request.form.get('lname')
    phone = request.form.get('phone_number')
    email = request.form.get('email')
    gender = request.form.get('gender')
    pin = request.form.get('user_pin')

    try:
        db = get_db()
        cursor = db.cursor()
        sql = "INSERT INTO users (fname, lname, phone_number, email, gender, user_pin) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(sql, (fname, lname, phone, email, gender, pin))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('index'))
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/login', methods=['POST'])
def login():
    phone = request.form.get('phone_number')
    pin = request.form.get('user_pin')

    # Admin Login
    if phone == "0700000000" and pin == "1234":
        return redirect(url_for('dashboard'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT userId, fname FROM users WHERE phone_number = %s AND user_pin = %s", (phone, pin))
        user = cursor.fetchone()

        if user:
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']
            
            # Hardcoded Bus ID 1
            target_bus = 1 
            cursor.execute("SELECT seatingno FROM booking WHERE busId = %s", (target_bus,))
            booked_seats = [row['seatingno'] for row in cursor.fetchall()]
            
            cursor.execute("SELECT plateno, totalcapacity FROM bus WHERE busId = %s", (target_bus,))
            bus_info = cursor.fetchone()
            total_cap = bus_info['totalcapacity'] if bus_info else 32
            seats_left = total_cap - len(booked_seats)

            cursor.close()
            db.close()
            return render_template('mainpage.html', user_name=user['fname'], booked_seats=booked_seats, bus_id=target_bus, bus_plate=bus_info['plateno'] if bus_info else "KCP 442L", total_capacity=total_cap, seats_left=seats_left)
        else:
            return render_template('BusSeatReservationSystem(vs).html', error="Invalid credentials")
    except Exception as e:
        return f"Login Error: {e}"

# --- NEW ROUTE: PROCESS BOOKING ---
@app.route('/process_booking', methods=['POST'])
def process_booking():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id = session['user_id']
    bus_id = request.form.get('busId')
    seat_no = request.form.get('seatingno')
    amount = request.form.get('amount_paid')

    if not seat_no:
        return "Please select a seat first!", 400

    try:
        db = get_db()
        cursor = db.cursor()
        
        # Save booking to database
        sql = """
            INSERT INTO booking (userId, busId, seatingno, amount_paid, bookingdate) 
            VALUES (%s, %s, %s, %s, NOW())
        """
        cursor.execute(sql, (user_id, bus_id, seat_no, amount))
        db.commit()
        
        cursor.close()
        db.close()

        # Success! Redirect back to mainpage (or show a ticket)
        # We use a trick here: redirect to login to refresh the session data and seat map
        return f"""
            <script>
                alert('Booking Successful! Seat {{ seat_no }} is yours.');
                window.location.href = '/';
            </script>
        """
    except Exception as e:
        return f"Booking Error: {e}"

@app.route('/dashboard')
def dashboard():
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # 1. Stats
        cursor.execute("SELECT COUNT(*) as count FROM bus")
        bus_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM booking")
        booking_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT SUM(amount_paid) as total FROM booking")
        res = cursor.fetchone()
        total_revenue = res['total'] if res['total'] else 0
        
        cursor.execute("SELECT COUNT(*) as count FROM users")
        passenger_count = cursor.fetchone()['count']

        # 2. Registrations
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_list = cursor.fetchall()
        formatted_passengers = [(u['userId'], u['fname'], u['lname'], u['phone_number']) for u in passengers_list]

        # 3. Fleet Management (Who is in Bus 1)
        cursor.execute("""
            SELECT u.fname, u.lname, b.seatingno, b.bookingdate 
            FROM booking b 
            JOIN users u ON b.userId = u.userId 
            WHERE b.busId = 1
        """)
        bus_passengers = cursor.fetchall()

        # 4. Reports (Revenue per person)
        cursor.execute("""
            SELECT u.fname, u.lname, b.seatingno, b.busId, b.amount_paid, b.bookingdate 
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
                               total_revenue=total_revenue, 
                               passenger_count=passenger_count,
                               passengers=formatted_passengers,
                               bus_passengers=bus_passengers,
                               all_bookings=all_bookings)
    except Exception as e:
        return f"Dashboard Error: {e}"

@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)