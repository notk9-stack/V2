from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import secrets
import json
import os
import base64
import time
import threading
import signal
import sys

# ======================== CONFIGURATION ========================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

# ডাটাবেস কনফিগারেশন (PostgreSQL support for Railway)
database_url = os.environ.get('DATABASE_URL', 'sqlite:///hoisting.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,
    'pool_recycle': 280,
    'pool_pre_ping': True,
    'pool_use_lifo': True
}

# ফাইল আপলোড কনফিগারেশন
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit
ALLOWED_EXTENSIONS = {'py', 'txt', 'json', 'env', 'md', 'html', 'css', 'js'}

db = SQLAlchemy(app)

# Keep-alive mechanism
last_request_time = {}
keep_alive_thread = None
app_health = True

# ======================== ডাটাবেস মডেল ========================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    plan = db.Column(db.String(20), default='24h')
    plan_activated_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    server_config = db.Column(db.Text, default='{}')
    files_data = db.Column(db.Text, default='[]')
    
    server_is_running = db.Column(db.Boolean, default=False)
    server_start_time = db.Column(db.DateTime, nullable=True)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ======================== HELPER FUNCTIONS ========================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_last_activity(user_id):
    """Update user's last activity timestamp"""
    user = User.query.get(user_id)
    if user:
        user.last_activity = datetime.utcnow()
        db.session.commit()

def keep_alive_monitor():
    """Background thread to keep the app alive"""
    global app_health
    while app_health:
        try:
            # Ping the database to keep connection alive
            db.session.execute('SELECT 1')
            db.session.commit()
            time.sleep(30)  # Every 30 seconds
        except Exception as e:
            print(f"Keep-alive error: {e}")
            try:
                db.session.rollback()
            except:
                pass
            time.sleep(5)

# Start keep-alive thread
def start_keep_alive():
    global keep_alive_thread
    if keep_alive_thread is None or not keep_alive_thread.is_alive():
        keep_alive_thread = threading.Thread(target=keep_alive_monitor, daemon=True)
        keep_alive_thread.start()

# Graceful shutdown handler
def handle_shutdown(signum, frame):
    global app_health
    app_health = False
    print("Shutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# ======================== HTML টেমপ্লেট (সিম্পলিফাইড) ========================
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hoisting Bot Server | IFTEKHAR</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', sans-serif; }
        body {
            min-height: 100vh;
            background: linear-gradient(135deg, #0a0e2a 0%, #060b1f 100%);
            padding: 1rem;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .auth-card {
            background: rgba(8,18,38,0.95);
            backdrop-filter: blur(16px);
            border-radius: 2rem;
            border: 1px solid rgba(0,255,255,0.4);
            max-width: 480px;
            margin: 8vh auto;
            padding: 2rem;
        }
        .iftekhar-logo {
            font-size: 2rem;
            font-weight: 800;
            text-align: center;
            background: linear-gradient(135deg, #fff, #0ff, #f0f);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }
        .dashboard {
            display: none;
            background: rgba(6,14,28,0.92);
            backdrop-filter: blur(12px);
            border-radius: 1.5rem;
            border: 1px solid #2f6a8a;
            overflow: hidden;
        }
        .dashboard-header {
            display: flex; justify-content: space-between; align-items: center;
            flex-wrap: wrap; padding: 1.2rem 1.8rem;
            background: #030e1ce0; border-bottom: 1px solid #2f6080;
        }
        .content-area { padding: 1.8rem; min-height: 550px; }
        .info-card {
            background: #0a1430aa; border-radius: 1rem;
            padding: 1.2rem; margin-bottom: 1.2rem;
        }
        .status-badge { 
            display: inline-block; padding: 0.3rem 1rem; border-radius: 2rem; 
            font-size: 0.8rem; font-weight: bold;
        }
        .status-running { background: #2a8f5f; color: white; }
        .status-stopped { background: #aa3355; color: white; }
        .logout-btn { background: #ff5566aa; padding: 0.4rem 1rem; border-radius: 2rem; cursor: pointer; }
        .input-field {
            width: 100%; background: #0a1a2ee0; border: 1px solid #2f6080;
            padding: 0.8rem; border-radius: 1rem; color: white; margin: 0.5rem 0 1rem;
        }
        .auth-btn, .action-btn {
            background: linear-gradient(95deg, #00c6ff, #2575fc);
            border: none; padding: 0.8rem 1.5rem; border-radius: 1.5rem;
            font-weight: bold; color: white; cursor: pointer;
        }
        .action-btn.danger { background: #aa3355; }
        .action-btn.success { background: #2a8f5f; }
        .toast-msg { position: fixed; bottom: 20px; right: 20px; background: #2a8f5f; padding: 0.5rem 1rem; border-radius: 2rem; z-index: 100; }
    </style>
</head>
<body>
<div class="container">
    <div id="authCard" class="auth-card">
        <div class="iftekhar-logo">⚡ IFTEKHAR ⚡</div>
        <div style="text-align: center; color: #8ac4ff;">HOISTING BOT SERVER</div>
        <div id="loginForm">
            <form id="loginAuthForm">
                <input type="email" id="loginEmail" class="input-field" placeholder="Gmail" required>
                <input type="password" id="loginPassword" class="input-field" placeholder="পাসওয়ার্ড" required>
                <button type="submit" class="auth-btn">🚀 প্রবেশ করুন</button>
            </form>
            <p style="text-align:center; margin-top:1rem;">📝 ডেমো: admin@hoist.com / admin123<br>অথবা নিজের একাউন্ট করুন!</p>
        </div>
    </div>

    <div id="dashboard" class="dashboard">
        <div class="dashboard-header">
            <div><h2 style="color:#aaf0ff;">🐍 HOISTING BOT SERVER</h2><small>IFTEKHAR কোর</small></div>
            <div><span id="userEmailDisplay"></span><button id="logoutMainBtn" class="logout-btn">⛁ লগআউট</button></div>
        </div>
        <div class="content-area" id="dynamicContent">Loading...</div>
    </div>
</div>
<div id="toastMsg" style="display:none;" class="toast-msg"></div>

<script>
    let statusInterval = null;
    
    function showToast(msg, isError=false) {
        const toast = document.getElementById('toastMsg');
        toast.style.backgroundColor = isError ? '#aa3355' : '#2a8f5f';
        toast.innerText = msg;
        toast.style.display = 'block';
        setTimeout(() => toast.style.display = 'none', 3000);
    }
    
    async function apiCall(url, method, data) {
        try {
            const res = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: data ? JSON.stringify(data) : undefined
            });
            return await res.json();
        } catch(e) {
            showToast('কানেকশন error!', true);
            return { success: false };
        }
    }
    
    async function loadContent() {
        const res = await apiCall('/api/dashboard', 'GET');
        document.getElementById('dynamicContent').innerHTML = res.html;
    }
    
    async function checkAuth() {
        const res = await fetch('/api/check_auth');
        const data = await res.json();
        if(data.logged_in) {
            document.getElementById('authCard').style.display = 'none';
            document.getElementById('dashboard').style.display = 'block';
            document.getElementById('userEmailDisplay').innerHTML = `👤 ${data.name}`;
            loadContent();
            if(statusInterval) clearInterval(statusInterval);
            statusInterval = setInterval(() => {
                fetch('/api/ping').catch(() => {});
            }, 30000);
        } else {
            document.getElementById('authCard').style.display = 'block';
            document.getElementById('dashboard').style.display = 'none';
            if(statusInterval) clearInterval(statusInterval);
        }
    }
    
    document.getElementById('loginAuthForm').onsubmit = async (e) => {
        e.preventDefault();
        const res = await apiCall('/api/login', 'POST', {
            email: document.getElementById('loginEmail').value,
            password: document.getElementById('loginPassword').value
        });
        if(res.success) { showToast('লগইন সফল!'); checkAuth(); }
        else showToast(res.message, true);
    };
    
    document.getElementById('logoutMainBtn').onclick = async () => {
        await apiCall('/api/logout', 'POST');
        checkAuth();
    };
    
    // Start server button handler
    window.startServer = async () => {
        const res = await apiCall('/api/start_server', 'POST');
        showToast(res.message);
        loadContent();
    };
    
    window.stopServer = async () => {
        const res = await apiCall('/api/stop_server', 'POST');
        showToast(res.message);
        loadContent();
    };
    
    checkAuth();
    
    // Heartbeat ping every 30 seconds
    setInterval(() => {
        fetch('/api/ping').catch(() => {});
    }, 30000);
</script>
</body>
</html>
'''

# ======================== Flask রাউট ========================
@app.before_request
def before_request():
    """Update last activity time"""
    if 'user_id' in session:
        try:
            update_last_activity(session['user_id'])
        except:
            pass

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/ping')
def ping():
    """Keep-alive endpoint"""
    return jsonify({'status': 'ok', 'time': time.time()})

@app.route('/api/check_auth')
def check_auth():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return jsonify({'logged_in': True, 'name': user.name, 'email': user.email, 'plan': user.plan})
    return jsonify({'logged_in': False})

@app.route('/api/dashboard')
def dashboard():
    if 'user_id' not in session:
        return jsonify({'html': '<p>প্লিজ লগইন করুন</p>'})
    
    user = User.query.get(session['user_id'])
    status_class = 'status-running' if user.server_is_running else 'status-stopped'
    status_text = '🟢 চলমান' if user.server_is_running else '🔴 বন্ধ'
    
    html = f'''
    <div class="info-card">
        <h3>📊 সার্ভার ওভারভিউ</h3>
        <p>📦 প্ল্যান: <strong>{user.plan}</strong></p>
        <p>🤖 সার্ভার স্ট্যাটাস: <span class="status-badge {status_class}">{status_text}</span></p>
        <p>🐍 পাইথন ভার্সন: 3.11.5</p>
        <p>📅 লাস্ট অ্যাক্টিভিটি: {user.last_activity.strftime('%Y-%m-%d %H:%M:%S') if user.last_activity else 'Never'}</p>
    </div>
    
    <div style="display: flex; gap: 1rem; margin-top: 1rem;">
        {f'<button class="action-btn success" onclick="startServer()">▶️ START SERVER</button>' if not user.server_is_running else ''}
        {f'<button class="action-btn danger" onclick="stopServer()">⏹️ STOP SERVER</button>' if user.server_is_running else ''}
    </div>
    
    <div class="info-card" style="margin-top: 1rem;">
        <h3>💡 কিভাবে ব্যবহার করবেন</h3>
        <p>1️⃣ লগইন করুন</p>
        <p>2️⃣ START SERVER ক্লিক করুন</p>
        <p>3️⃣ আপনার বট সার্ভার চলবে!</p>
        <p>4️⃣ হোস্টিং স্বয়ংক্রিয়ভাবে চালু থাকবে</p>
    </div>
    '''
    
    return jsonify({'html': html})

@app.route('/api/start_server', methods=['POST'])
def start_server():
    if 'user_id' not in session:
        return jsonify({'message': 'লগইন করুন'})
    
    try:
        user = User.query.get(session['user_id'])
        if user.server_is_running:
            return jsonify({'message': 'সার্ভার ইতিমধ্যে চলমান!'})
        
        user.server_is_running = True
        user.server_start_time = datetime.utcnow()
        user.last_activity = datetime.utcnow()
        db.session.commit()
        
        # Start keep-alive if not running
        start_keep_alive()
        
        return jsonify({'message': '✅ সার্ভার স্টার্ট করা হয়েছে!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Error: {str(e)}'})

@app.route('/api/stop_server', methods=['POST'])
def stop_server():
    if 'user_id' not in session:
        return jsonify({'message': 'লগইন করুন'})
    
    try:
        user = User.query.get(session['user_id'])
        if not user.server_is_running:
            return jsonify({'message': 'সার্ভার ইতিমধ্যে বন্ধ!'})
        
        user.server_is_running = False
        user.last_activity = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': '⏹️ সার্ভার বন্ধ করা হয়েছে!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Error: {str(e)}'})

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'success': False, 'message': 'এই ইমেইল ইতিমধ্যে রেজিস্টার করা আছে!'})
        
        user = User(
            name=data['name'],
            email=data['email'],
            server_config=json.dumps({
                'server_id': secrets.token_hex(16),
                'name': 'My Hoisting Bot'
            })
        )
        user.set_password(data['password'])
        db.session.add(user)
        db.session.commit()
        return jsonify({'success': True, 'message': 'রেজিস্ট্রেশন সফল! লগইন করুন।'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        user = User.query.filter_by(email=data['email']).first()
        if user and user.check_password(data['password']):
            session.permanent = True
            session['user_id'] = user.id
            user.last_activity = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True, 'message': 'লগইন সফল'})
        return jsonify({'success': False, 'message': 'ভুল ইমেইল বা পাসওয়ার্ড'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'success': True})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Create demo user if not exists
        if not User.query.filter_by(email='admin@hoist.com').first():
            admin_user = User(name='Admin', email='admin@hoist.com')
            admin_user.set_password('admin123')
            db.session.add(admin_user)
            
            demo_user = User(name='Demo User', email='demo@hoist.com')
            demo_user.set_password('123456')
            db.session.add(demo_user)
            
            db.session.commit()
            print("✅ Demo accounts created: admin@hoist.com / admin123 | demo@hoist.com / 123456")
        
        print("✅ Database tables created")
    
    # Start keep-alive thread
    start_keep_alive()
    
    port = int(os.environ.get('PORT', 5000))
    print(f"""
    ╔══════════════════════════════════════════════════════════════════╗
    ║     🐍 IFTEKHAR HOISTING BOT SERVER - FIXED VERSION             ║
    ║     📍 http://localhost:{port}                                    ║
    ║     🔐 Demo Login: admin@hoist.com / admin123                    ║
    ║     🔐 Demo Login: demo@hoist.com / 123456                       ║
    ║     📝 Server will stay alive automatically!                     ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    # Use production WSGI server
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)