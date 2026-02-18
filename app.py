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
        values = (fname, lname, phone, email, gender, pin)
        cursor.execute(sql, values)
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

    if phone == "0700000000" and pin == "1234":
        return redirect(url_for('dashboard'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        # 1. Fetch User
        cursor.execute("SELECT userId, fname FROM users WHERE phone_number = %s AND user_pin = %s", (phone, pin))
        user = cursor.fetchone()

        if user:
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']

            target_bus = 1 

            # 2. Fetch Booked Seats
            cursor.execute("SELECT seatingno FROM booking WHERE busId = %s", (target_bus,))
            booked_data = cursor.fetchall()
            booked_seats = [row['seatingno'] for row in booked_data]

            # 3. CHECK: Has this user already booked a seat?
            cursor.execute("SELECT seatingno FROM booking WHERE busId = %s AND userId = %s", (target_bus, user['userId']))
            user_booking = cursor.fetchone()
            has_booked = True if user_booking else False
            user_seat = user_booking['seatingno'] if user_booking else None

            # 4. Fetch Bus Details
            cursor.execute("SELECT plateno, totalcapacity FROM bus WHERE busId = %s", (target_bus,))
            bus_info = cursor.fetchone()

            # 5. Calculate Seats Left
            total_cap = bus_info['totalcapacity'] if bus_info else 32
            seats_left = total_cap - len(booked_seats)

            cursor.close()
            db.close()

            return render_template('mainpage.html', 
                                   user_name=user['fname'], 
                                   booked_seats=booked_seats,
                                   bus_id=target_bus,
                                   bus_plate=bus_info['plateno'] if bus_info else "KCP 442L",
                                   total_capacity=total_cap,
                                   seats_left=seats_left,
                                   has_booked=has_booked,
                                   user_seat=user_seat)
        else:
            # Returns the error message to your new HTML error span
            return render_template('BusSeatReservationSystem(vs).html', error="Invalid phone number or PIN")
            
    except Exception as e:
        return render_template('BusSeatReservationSystem(vs).html', error="Database connection failed")

@app.route('/process_booking', methods=['POST'])
def process_booking():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id = session['user_id']
    bus_id = request.form.get('busId') or 1 
    seat_no = request.form.get('seatingno')
    amount = request.form.get('amount_paid')

    try:
        db = get_db()
        cursor = db.cursor()
        
        sql = """INSERT INTO booking (busId, userId, seatingno, amount_paid, bookingdate) 
                 VALUES (%s, %s, %s, %s, NOW())"""
        cursor.execute(sql, (bus_id, user_id, seat_no, amount))
        
        db.commit()
        cursor.close()
        db.close()
        
        return f"Booking Successful for Seat {seat_no}! <a href='/'>Refresh Page</a>"
    except Exception as e:
        return f"Booking Error: {e}"

@app.route('/dashboard')
def dashboard():
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM bus")
        bus_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM booking")
        booking_count = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(amount_paid) FROM booking")
        rev = cursor.fetchone()[0]
        total_revenue = rev if rev else 0
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        db_users = cursor.fetchall()
        cursor.close()
        db.close()
        return render_template('dashboards.html', passengers=db_users, bus_count=bus_count, 
                               booking_count=booking_count, total_revenue=total_revenue, 
                               passenger_count=len(db_users))
    except Exception as e:
        return f"Dashboard Error: {e}"

@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)