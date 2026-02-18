from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import mysql.connector
import uuid 
from datetime import datetime

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

    if phone == "0712345678" and pin == "9999":
        session['user_id'] = 'ADMIN'
        session['user_name'] = 'System Admin'
        return redirect(url_for('admin_dashboard'))

    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT userId, fname FROM users WHERE phone_number = %s AND user_pin = %s", (phone, pin))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if user:
            session['user_id'] = user['userId']
            session['user_name'] = user['fname']
            return redirect(url_for('main_page'))
        return "Invalid Login"
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/main_page')
def main_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT busId, plateno, totalcapacity FROM bus")
        buses = cursor.fetchall()
        
        cursor.execute("SELECT userId, busId, seatingno, ticket_ref, amount_paid FROM booking")
        bookings = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        return render_template('mainpage.html', 
                               user_name=session['user_name'], 
                               buses=buses, 
                               bookings=bookings)
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['user_id'] != 'ADMIN':
        return redirect(url_for('index'))
    
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)

        # 1. Stats for the cards
        cursor.execute("SELECT COUNT(*) as total FROM bus")
        bus_count = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM booking")
        booking_count = cursor.fetchone()['total']

        cursor.execute("SELECT COUNT(*) as total FROM users")
        passenger_count = cursor.fetchone()['total']

        cursor.execute("SELECT SUM(amount_paid) as total FROM booking")
        rev_res = cursor.fetchone()
        total_revenue = rev_res['total'] if rev_res['total'] else 0.0

        # 2. Passenger Registrations Table (Overview Section)
        # Using fetchall() and converting to list of tuples for your HTML indexing user[0], user[1]
        cursor.execute("SELECT userId, fname, lname, phone_number FROM users")
        passengers_raw = cursor.fetchall()
        passengers = [tuple(p.values()) for p in passengers_raw]

        # 3. Fleet Management Section (Bus #1)
        cursor.execute("""
            SELECT b.seatingno, u.fname, u.lname, b.bookingdate 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            WHERE b.busId = 1
        """)
        bus_passengers = cursor.fetchall()

        # 4. Booking Reports Section
        sql = """
            SELECT b.bookingdate, u.fname, u.lname, b.seatingno, b.busId, b.amount_paid 
            FROM booking b
            JOIN users u ON b.userId = u.userId
            ORDER BY b.bookingdate DESC
        """
        cursor.execute(sql)
        all_bookings = cursor.fetchall()

        cursor.close()
        db.close()
        
        # We must pass ALL these variables because your HTML template uses them
        return render_template('dashboards.html', 
                               bus_count=bus_count,
                               booking_count=booking_count,
                               passenger_count=passenger_count,
                               total_revenue=total_revenue,
                               passengers=passengers,
                               bus_passengers=bus_passengers,
                               all_bookings=all_bookings)
    except Exception as e:
        return f"Admin Dashboard Error: {e}"

@app.route('/process_booking', methods=['POST'])
def process_booking():
    if 'user_id' not in session: 
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    bus_id = request.form.get('busId')
    seat_no = request.form.get('seatingno')
    amount = request.form.get('amount_paid')
    ticket_ref = str(uuid.uuid4())[:8].upper()

    try:
        db = get_db()
        cursor = db.cursor()
        sql = """INSERT INTO booking (userId, busId, seatingno, amount_paid, ticket_ref, bookingdate) 
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        cursor.execute(sql, (user_id, bus_id, seat_no, amount, ticket_ref, datetime.now()))
        db.commit()
        cursor.close()
        db.close()
        return redirect(url_for('main_page'))
    except Exception as e:
        return f"Booking Error: {e}"

@app.route('/signout')
def signout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)