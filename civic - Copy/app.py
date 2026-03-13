import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import mysql.connector
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
from functools import wraps
import socket

# Load env variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default-secret-key')

# Database connection utility
def generate_display_id():
    """Generates an ID in the format: 2 digits, 2 letters, 1 digit (e.g., 26CV3)"""
    digits1 = ''.join(random.choices(string.digits, k=2))
    letters = ''.join(random.choices(string.ascii_uppercase, k=2))
    digit2 = random.choice(string.digits)
    return f"{digits1}{letters}{digit2}"

def get_unique_display_id(cursor):
    while True:
        new_id = generate_display_id()
        cursor.execute("SELECT complaint_id FROM complaints WHERE display_id = %s", (new_id,))
        if not cursor.fetchone():
            return new_id

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'civic_complaints')
        )
        return connection
    except mysql.connector.Error as err:
        print(f"Error connecting to MySQL: {err}")
        return None

# Context processor to make active page and session user available
@app.context_processor
def inject_active():
    return dict(
        active_page=request.endpoint,
        user=session.get('user')
    )

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('login', next=request.url))
            if role and session['user']['role'] != role:
                flash("You do not have permission to access this page.", "error")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Routes
@app.route('/')
def index():
    # Fetch Top Priority (Highest Votes) and Recent Complaints
    conn = get_db_connection()
    recent_complaints = []
    top_priority = []
    
    if conn:
        cursor = conn.cursor(dictionary=True)
        # 1. Fetch Top Priority (Highest Votes)
        cursor.execute('''
            SELECT c.complaint_id, c.display_id, c.issue_type, c.area, c.status, c.date_submitted, COUNT(v.vote_id) as vote_count
            FROM complaints c
            LEFT JOIN votes v ON c.complaint_id = v.complaint_id
            GROUP BY c.complaint_id
            ORDER BY vote_count DESC, c.date_submitted DESC 
            LIMIT 5
        ''')
        top_priority = cursor.fetchall()

        # 2. Fetch Recent
        cursor.execute('''
            SELECT c.complaint_id, c.display_id, c.issue_type, c.area, c.status, c.date_submitted, COUNT(v.vote_id) as vote_count
            FROM complaints c
            LEFT JOIN votes v ON c.complaint_id = v.complaint_id
            GROUP BY c.complaint_id
            ORDER BY c.date_submitted DESC 
            LIMIT 5
        ''')
        recent_complaints = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
    return render_template('index.html', 
                          recent_complaints=recent_complaints, 
                          top_priority=top_priority)

@app.route('/api/vote/<int:complaint_id>', methods=['POST'])
def api_vote(complaint_id):
    voter_id = request.remote_addr # Simplified unique ID
    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database connection error"}), 500
        
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO votes (complaint_id, voter_identifier) 
            VALUES (%s, %s)
        ''', (complaint_id, voter_id))
        conn.commit()
        return jsonify({"success": True, "message": "Thank you for your vote!"})
    except mysql.connector.IntegrityError:
        return jsonify({"success": False, "message": "You have already voted for this issue."}), 400
    except mysql.connector.Error as err:
        return jsonify({"success": False, "message": "Voting failed."}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        govt_id = request.form.get('govt_id')
        
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if user and check_password_hash(user['password'], password):
                if user['role'] == 'admin' and user['govt_id'] != govt_id:
                    flash("Invalid Government ID for Admin access.", "error")
                else:
                    session['user'] = {
                        'id': user['id'],
                        'name': user['name'],
                        'email': user['email'],
                        'role': user['role']
                    }
                    flash(f"Welcome back, {user['name']}!", "success")
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('dashboard' if user['role'] == 'admin' else 'index'))
            else:
                flash("Invalid email or password.", "error")
        else:
            flash("Database connection error.", "error")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        govt_id = request.form.get('govt_id')
        
        if not all([name, email, password, govt_id]):
            flash("All fields are required.", "error")
            return render_template('register.html')

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            try:
                # 1. Check if email exists
                cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cursor.fetchone():
                    flash("Email address already registered.", "error")
                    return render_template('register.html')
                
                # 2. Check if Govt ID exists
                cursor.execute("SELECT id FROM users WHERE govt_id = %s", (govt_id,))
                if cursor.fetchone():
                    flash("Government ID already in use.", "error")
                    return render_template('register.html')
                
                # 3. Create user
                hashed_pw = generate_password_hash(password)
                cursor.execute('''
                    INSERT INTO users (name, email, password, govt_id, role)
                    VALUES (%s, %s, %s, %s, 'admin')
                ''', (name, email, hashed_pw, govt_id))
                conn.commit()
                
                flash("Account created successfully! Please log in.", "success")
                return redirect(url_for('login'))
            except mysql.connector.Error as err:
                print(f"Registration error: {err}")
                flash("An error occurred during registration.", "error")
            finally:
                cursor.close()
                conn.close()
        else:
            flash("Database connection error.", "error")
            
    return render_template('register.html')

@app.route('/track', methods=['GET'])
def track():
    complaint_id = request.args.get('id')
    complaint = None
    
    if complaint_id:
        complaint_id = complaint_id.strip().lstrip('#').upper()
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            try:
                # Lookup by display_id instead of integer ID
                cursor.execute('''
                    SELECT c.*, r.action_taken 
                    FROM complaints c 
                    LEFT JOIN resolution r ON c.complaint_id = r.complaint_id 
                    WHERE c.display_id = %s
                ''', (complaint_id,))
                complaint = cursor.fetchone()
                
                if not complaint:
                    flash(f"No complaint found with ID: {complaint_id}", 'error')
            except mysql.connector.Error as err:
                print(f"Tracking error: {err}")
                flash('An error occurred querying the database.', 'error')
            finally:
                cursor.close()
                conn.close()
                
    return render_template('track.html', complaint=complaint, search_id=complaint_id)

@app.route('/submit', methods=['GET', 'POST'])
def submit():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        area = request.form.get('area')
        issue_type = request.form.get('issue_type')
        description = request.form.get('description')
        
        # 1. Honeypot check for bots
        if request.form.get('confirm_identity'):
            return redirect(url_for('submit'))
        
        # 2. Check accuracy confirmation
        if not request.form.get('confirm'):
            flash("You must confirm that your details are accurate.", "error")
            return redirect(url_for('submit'))
            
        # 3. Simple Duplicate Check (Prevent spam within 5 mins)
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute('''
                SELECT complaint_id FROM complaints 
                WHERE citizen_email = %s AND area = %s AND issue_type = %s 
                AND date_submitted >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
            ''', (email, area, issue_type))
            if cursor.fetchone():
                cursor.close()
                conn.close()
                flash("You have already submitted a similar complaint recently. Please wait a few minutes.", "warning")
                return redirect(url_for('submit'))
            cursor.close()
            conn.close()
        
        # Proceed with submission
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            try:
                display_id = get_unique_display_id(cursor)
                cursor.execute('''
                    INSERT INTO complaints (citizen_name, citizen_email, area, issue_type, description, display_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (name, email, area, issue_type, description, display_id))
                complaint_id = cursor.lastrowid
                
                # Automatically register a vote for the reporter
                try:
                    cursor.execute('''
                        INSERT INTO votes (complaint_id, voter_identifier) 
                        VALUES (%s, %s)
                    ''', (complaint_id, request.remote_addr))
                except mysql.connector.Error:
                    pass # Non-critical if vote fails
                
                conn.commit()
                flash(f'Your complaint has been submitted successfully! Your Tracking ID is: {display_id}', 'success')
            except mysql.connector.Error as err:
                print(f"Error inserting complaint: {err}")
                flash('An error occurred submitting your complaint. Please try again.', 'error')
            finally:
                cursor.close()
                conn.close()
            return redirect(url_for('submit'))
        else:
            flash('Database connection error.', 'error')
    
    return render_template('submit.html')

@app.route('/dashboard')
@login_required(role='admin')
def dashboard():
    area_filter = request.args.get('area')
    issue_filter = request.args.get('issue_type')
    
    query = 'SELECT * FROM complaints WHERE 1=1'
    params = []
    
    if area_filter:
        query += ' AND area = %s'
        params.append(area_filter)
    
    if issue_filter:
        query += ' AND issue_type = %s'
        params.append(issue_filter)
        
    query += ' ORDER BY date_submitted DESC'
    
    conn = get_db_connection()
    complaints = []
    stats = {'total': 0, 'pending': 0, 'resolved': 0, 'top_issue': 'N/A'}
    alerts = []
    
    if conn:
        cursor = conn.cursor(dictionary=True)
        # 1. Fetch filtered complaints
        cursor.execute(query, params)
        complaints = cursor.fetchall()
        
        # 2. Fetch Stats
        cursor.execute("SELECT COUNT(*) as c FROM complaints")
        res = cursor.fetchone()
        stats['total'] = res['c'] if res else 0
        
        cursor.execute("SELECT COUNT(*) as c FROM complaints WHERE status IN ('Pending', 'In Progress')")
        res = cursor.fetchone()
        stats['pending'] = res['c'] if res else 0
        
        cursor.execute("SELECT COUNT(*) as c FROM complaints WHERE status = 'Resolved'")
        res = cursor.fetchone()
        stats['resolved'] = res['c'] if res else 0
        
        cursor.execute("SELECT issue_type, COUNT(*) as c FROM complaints GROUP BY issue_type ORDER BY c DESC LIMIT 1")
        res = cursor.fetchone()
        if res:
            stats['top_issue'] = res['issue_type']
            
        # 3. Get intelligent insights (clusters, predictions, recommendations)
        insights = get_intelligent_insights(cursor)
        
        cursor.close()
        conn.close()
        
    return render_template('dashboard.html', 
                          complaints=complaints, 
                          area_filter=area_filter, 
                          issue_filter=issue_filter,
                          stats=stats,
                          alerts=insights['predictions'], # Pass predictions as alerts
                          clusters=insights['clusters']) # Pass clusters
    

@app.route('/analytics')
def analytics():
    conn = get_db_connection()
    stats = {'total': 0, 'resolved': 0, 'active': 0}
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) as total FROM complaints")
        stats['total'] = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as resolved FROM complaints WHERE status = 'Resolved'")
        stats['resolved'] = cursor.fetchone()['resolved']
        
        stats['active'] = stats['total'] - stats['resolved']
        cursor.close()
        conn.close()
        
    return render_template('analytics.html', stats=stats)

# API Routes for Analytics
@app.route('/api/analytics')
def api_analytics():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = conn.cursor(dictionary=True)
    
    data = {}
    
    # 1. Complaints by Issue Type (Pie Chart)
    cursor.execute('SELECT issue_type, COUNT(*) as count FROM complaints GROUP BY issue_type')
    data['by_issue'] = cursor.fetchall()
    
    # 2. Complaints by Area (Bar Chart)
    cursor.execute('SELECT area, COUNT(*) as count FROM complaints GROUP BY area ORDER BY count DESC LIMIT 10')
    data['by_area'] = cursor.fetchall()
    
    # 3. Monthly Trends (Line Chart)
    # Using DATE_FORMAT for MySQL to group by YYYY-MM
    cursor.execute('''
        SELECT DATE_FORMAT(date_submitted, '%Y-%m') as month, COUNT(*) as count 
        FROM complaints 
        GROUP BY month 
        ORDER BY month ASC
    ''')
    data['trends'] = cursor.fetchall()
    
    # 4. Overall stats
    cursor.execute("SELECT COUNT(*) as total FROM complaints")
    total_res = cursor.fetchone()
    data['total_complaints'] = total_res['total'] if total_res else 0
    
    cursor.execute("SELECT COUNT(*) as resolved FROM complaints WHERE status='Resolved'")
    resolved_res = cursor.fetchone()
    data['resolved_complaints'] = resolved_res['resolved'] if resolved_res else 0
    
    cursor.close()
    conn.close()
    
    return jsonify(data)

@app.route('/api/admin/update-status', methods=['POST'])
@login_required(role='admin')
def api_admin_update_status():
    data = request.json
    complaint_id = data.get('complaint_id')
    new_status = data.get('status')
    action_taken = data.get('action_taken', '')

    if not complaint_id or not new_status:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    cursor = conn.cursor()
    try:
        # 1. Update status
        cursor.execute('''
            UPDATE complaints SET status = %s WHERE complaint_id = %s
        ''', (new_status, complaint_id))

        # 2. If Resolved, add to resolution table
        if new_status == 'Resolved' and action_taken:
            cursor.execute('''
                INSERT INTO resolution (complaint_id, action_taken)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE action_taken = %s, resolved_date = NOW()
            ''', (complaint_id, action_taken, action_taken))

        conn.commit()
        return jsonify({"success": True, "message": f"Complaint #{complaint_id} updated to {new_status}"})
    except mysql.connector.Error as err:
        print(f"Error updating status: {err}")
        return jsonify({"success": False, "message": "Failed to update status"}), 500
    finally:
        cursor.close()
        conn.close()

def get_intelligent_insights(cursor):
    """Refactored logic to find clusters and predictions for both API and Dashboard."""
    # 1. Clustering: Find areas with multiple active (Pending/In Progress) complaints of same type
    cursor.execute('''
        SELECT area, issue_type, COUNT(*) as count 
        FROM complaints 
        WHERE status IN ('Pending', 'In Progress')
        GROUP BY area, issue_type
        HAVING count >= 3
        ORDER BY count DESC
    ''')
    clusters = cursor.fetchall()
    
    # 2. Predictions: Compare last 7 days vs previous 7 days to find rising hotspots
    cursor.execute('''
        SELECT area, 
               SUM(CASE WHEN date_submitted >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) as recent_count,
               SUM(CASE WHEN date_submitted < DATE_SUB(NOW(), INTERVAL 7 DAY) AND date_submitted >= DATE_SUB(NOW(), INTERVAL 14 DAY) THEN 1 ELSE 0 END) as previous_count
        FROM complaints 
        GROUP BY area
    ''')
    trend_data = cursor.fetchall()
    
    predictions = []
    for area in trend_data:
        recent = float(area['recent_count'] or 0)
        prev = float(area['previous_count'] or 0)
        
        # Logic: If recent > 5 and (prev == 0 or recent > prev * 1.2), mark as high risk
        is_rising = recent > 5 and (prev == 0 or recent > prev * 1.2)
        is_critical = recent >= 15 # High absolute volume
        
        if is_rising or is_critical:
            risk_level = "Critical" if is_critical else "High - Rising"
            growth_pct = round(((recent - prev) / prev * 100), 1) if prev > 0 else 100.0
            predictions.append({
                "area": area['area'],
                "risk_level": risk_level,
                "recent_volume": int(recent),
                "growth": growth_pct
            })
    
    # Sort predictions by volume
    predictions = sorted(predictions, key=lambda x: x['recent_volume'], reverse=True)
    
    # 3. Recommendations: Based on clusters and issue types
    recommendations = []
    seen_recommendations = set()
    
    for c in clusters:
        msg = ""
        action_type = "Inspection"
        if c['issue_type'] == 'Garbage':
            msg = f"Increase waste collection frequency in {c['area']} due to {c['count']} active reports."
            action_type = "Resource Allocation"
        elif c['issue_type'] == 'Road':
            msg = f"Deploy road maintenance crew to {c['area']} for immediate pothole/damage repair."
        elif c['issue_type'] == 'Water':
            msg = f"Inspect water supply lines in {c['area']} for potential major leakages."
        elif c['issue_type'] == 'Electricity':
            msg = f"Check transformer/grid stability in {c['area']} following repeated power issues."
        
        if msg and msg not in seen_recommendations:
            recommendations.append({"issue": c['issue_type'], "area": c['area'], "suggestion": msg, "action": action_type})
            seen_recommendations.add(msg)

    # 4. Global Predictions based on Type trends
    cursor.execute('''
        SELECT issue_type, COUNT(*) as count 
        FROM complaints 
        WHERE date_submitted >= DATE_SUB(NOW(), INTERVAL 3 DAY)
        GROUP BY issue_type
        HAVING count >= 5
    ''')
    recent_spikes = cursor.fetchall()
    for spike in recent_spikes:
        msg = f"City-wide spike in {spike['issue_type']} complaints detected. Alerting relevant department for emergency check."
        if msg not in seen_recommendations:
            recommendations.append({"issue": spike['issue_type'], "area": "City-wide", "suggestion": msg, "action": "Departmental Alert"})
            seen_recommendations.add(msg)

    return {
        "clusters": clusters,
        "predictions": predictions,
        "recommendations": recommendations
    }

@app.route('/api/insights')
def api_insights():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = conn.cursor(dictionary=True)
    insights = get_intelligent_insights(cursor)
    cursor.close()
    conn.close()
    
    return jsonify(insights)

@app.route('/api/heatmap')
def api_heatmap():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
        
    cursor = conn.cursor(dictionary=True)
    # Aggregate complaints by area
    cursor.execute('''
        SELECT area, COUNT(*) as volume 
        FROM complaints 
        GROUP BY area
    ''')
    areas = cursor.fetchall()
    
    # We will mock coordinates dynamically based on hashing the string, 
    # ensuring the same area always gets the same coordinate clustered around a center
    # Center: [37.7749, -122.4194] (San Francisco as default example)
    import hashlib
    def get_mock_coord(area_str):
        hash_val = int(hashlib.md5(area_str.encode()).hexdigest(), 16)
        lat_offset = ((hash_val % 100) - 50) / 1000.0  # roughly +/- 0.05 deg
        lng_offset = (((hash_val // 100) % 100) - 50) / 1000.0
        return [37.7749 + lat_offset, -122.4194 + lng_offset]
        
    for a in areas:
        a['coords'] = get_mock_coord(a['area'])
        
    cursor.close()
    conn.close()
    return jsonify(areas)

if __name__ == '__main__':
    # Use environment variables for port to support platforms like Render
    port = int(os.environ.get("PORT", 10000))
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("\n" + "="*30)
    print("Civic Complaint Analyzer")
    print("Server running at:")
    print(f"Local:   http://127.0.0.1:{port}")
    print(f"Network: http://{local_ip}:{port}")
    print(f"Public:  https://civicanalyzer.onrender.com")
    print("="*30 + "\n")
    
    # Debug mode is controlled by environment variable, default False for production-safety
    is_debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=is_debug)
