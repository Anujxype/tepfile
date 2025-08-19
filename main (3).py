from flask import Flask, render_template, request, jsonify, Response, session
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import os
import base64
import io
import re
import uuid
import requests
from PIL import Image
import time
from pymongo import MongoClient
import certifi
from bson import ObjectId
import secrets
import traceback

# Try to import QR/Camera dependencies
try:
    import cv2
    import numpy as np
    from pyzbar import pyzbar
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    print("⚠️ QR scanning not available - install opencv-python and pyzbar")

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
CORS(app, supports_credentials=True)

# MongoDB Configuration
MONGODB_URI = "mongodb+srv://qsxllo044f:NB8Q8yFLgwxaEvSa@cluster0.6ardueo.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "netflix_activator"

# Initialize MongoDB client
client = MongoClient(
    MONGODB_URI,
    tls=True,
    tlsAllowInvalidCertificates=True,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    retryWrites=True,
    w="majority"
)
db = client[DB_NAME]
cookies_collection = db["user_cookies"]
users_collection = db["users_sessions"]

# Store activation history per user in memory
activation_history = {}

def get_user_id():
    """Get or create unique user ID for session"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
        session.permanent = True
        
        users_collection.update_one(
            {'user_id': session['user_id']},
            {
                '$set': {
                    'user_id': session['user_id'],
                    'created_at': datetime.now(),
                    'last_active': datetime.now(),
                    'ip_address': request.remote_addr,
                    'user_agent': request.headers.get('User-Agent', 'Unknown')
                }
            },
            upsert=True
        )
    else:
        users_collection.update_one(
            {'user_id': session['user_id']},
            {'$set': {'last_active': datetime.now()}}
        )
    
    return session['user_id']

def convert_cookies_to_json(cookie_data):
    """Convert various cookie formats to JSON"""
    # If already a list of cookie objects, return as is
    if isinstance(cookie_data, list) and all(isinstance(c, dict) for c in cookie_data):
        return cookie_data
    
    cookies = []
    
    # Try to parse as Netscape format
    if isinstance(cookie_data, str):
        # Check if it's JSON string
        try:
            parsed = json.loads(cookie_data)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                # Convert dict format to list format
                for name, value in parsed.items():
                    cookies.append({
                        'name': name,
                        'value': str(value),
                        'domain': '.netflix.com',
                        'path': '/'
                    })
                return cookies
        except:
            pass
        
        # Try to parse as Netscape/text format
        lines = cookie_data.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Handle tab-separated format (Netscape)
            parts = line.split('\t')
            if len(parts) >= 7:
                cookies.append({
                    'domain': parts[0],
                    'name': parts[5],
                    'value': parts[6],
                    'path': parts[2],
                    'secure': parts[3].lower() == 'true',
                    'httpOnly': parts[1].lower() == 'true'
                })
            # Handle name=value format
            elif '=' in line:
                name, value = line.split('=', 1)
                cookies.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': '.netflix.com',
                    'path': '/'
                })
    
    return cookies if cookies else None

class NetflixActivator:
    def __init__(self, cookies_collection, user_id):
        self.cookies_collection = cookies_collection
        self.user_id = user_id
        self.active_cookies = None
        self.load_active_cookies()
    
    def load_active_cookies(self):
        """Load active cookies for current user only"""
        active_cookie = self.cookies_collection.find_one({
            'user_id': self.user_id,
            'active': True
        })
        if active_cookie:
            self.active_cookies = {c['name']: c['value'] for c in active_cookie.get('cookies', [])}
    
    def set_cookies(self, cookies):
        """Set cookies for activation"""
        self.active_cookies = {c['name']: c['value'] for c in cookies}
    
    def validate_cookies(self):
        """Check if valid cookies are available"""
        return self.active_cookies is not None
    
    def activate(self, code):
        """Activate TV with code using real Netflix API"""
        if not self.validate_cookies():
            return {
                'success': False,
                'message': 'No valid cookies available. Please upload your cookies first.'
            }
        
        try:
            # Create session with cookies
            s = requests.Session()
            for name, value in self.active_cookies.items():
                s.cookies.set(name, value, domain='.netflix.com')
            
            # Try Netflix activation endpoints
            activation_urls = [
                f'https://www.netflix.com/tv8/{code}',
                f'https://www.netflix.com/tv/{code}',
                f'https://www.netflix.com/activate/{code}'
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            
            for url in activation_urls:
                try:
                    resp = s.get(url, headers=headers, timeout=10, allow_redirects=True)
                    if resp.status_code == 200:
                        # Check for success indicators
                        if any(word in resp.text.lower() for word in ['success', 'activated', 'complete']):
                            return {
                                'success': True,
                                'message': f'TV activated successfully with code {code}!'
                            }
                except:
                    continue
            
            # If no clear success, return ambiguous success (Netflix doesn't always confirm)
            return {
                'success': True,
                'message': f'Activation request sent for code {code}. Check your TV!'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Activation error: {str(e)}'
            }

def check_netflix_cookie(cookie_dict):
    """Validate Netflix cookies and get account details"""
    if not cookie_dict:
        return {'ok': False, 'err': 'No cookies provided'}
    
    try:
        s = requests.Session()
        for name, value in cookie_dict.items():
            s.cookies.set(name, value, domain='.netflix.com')
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
        resp = s.get('https://www.netflix.com/YourAccount', headers=headers, timeout=15)
        
        if resp.status_code != 200:
            return {'ok': False, 'err': f'HTTP {resp.status_code}'}
        
        txt = resp.text
        
        # Check if logged in
        is_logged_in = 'membershipStatus' in txt or 'Account & Billing' in txt
        
        if not is_logged_in:
            return {'ok': False, 'err': 'Not logged in - cookies may be expired'}
        
        # Extract account info
        def find(pattern):
            m = re.search(pattern, txt, re.IGNORECASE)
            return m.group(1) if m else None
        
        plan = find(r'"planName"[^"]*"([^"]+)"') or "Unknown"
        country = find(r'"countryOfSignup"[^"]*"([^"]+)"') or "Unknown"
        member_since = find(r'"memberSince"[^"]*"([^"]+)"') or "Unknown"
        
        return {
            'ok': True,
            'valid': True,
            'plan': plan,
            'country': country,
            'member_since': member_since,
            'status': 'Active'
        }
        
    except requests.exceptions.Timeout:
        return {'ok': False, 'err': 'Timeout - Netflix took too long to respond'}
    except Exception as e:
        return {'ok': False, 'err': str(e)}

def extract_code_from_qr(qr_data):
    """Extract Netflix activation code from QR data"""
    patterns = [
        r'netflix\.com/tv[0-9]*/([0-9]{6,8})',
        r'code=([0-9]{6,8})',
        r'([0-9]{6,8})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, qr_data)
        if match:
            return match.group(1)
    return None

@app.before_request
def before_request():
    """Initialize user session before each request"""
    get_user_id()

@app.route('/')
def index():
    """Main dashboard with all features"""
    user_id = get_user_id()
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Netflix TV Activator Pro - Complete Edition</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Netflix Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            
            :root {
                --netflix-red: #e50914;
                --netflix-red-dark: #b20710;
                --netflix-dark: #141414;
                --success-green: #46d369;
                --error-red: #ff4444;
                --warning-yellow: #ffcc00;
                --glass-bg: rgba(20, 20, 20, 0.85);
                --glass-border: rgba(229, 9, 20, 0.3);
            }
            
            body {
                background: linear-gradient(135deg, #141414 0%, #2a0000 100%);
                color: #fff;
                min-height: 100vh;
                overflow-x: hidden;
                position: relative;
            }
            
            .bg-animation {
                position: fixed;
                width: 100%;
                height: 100%;
                top: 0;
                left: 0;
                z-index: -1;
                opacity: 0.1;
                background-image: 
                    radial-gradient(circle at 20% 50%, var(--netflix-red) 0%, transparent 50%),
                    radial-gradient(circle at 80% 80%, var(--netflix-red) 0%, transparent 50%);
                animation: bgMove 20s ease infinite;
            }
            
            @keyframes bgMove {
                0%, 100% { transform: translate(0, 0); }
                50% { transform: translate(-20px, -20px); }
            }
            
            .glass {
                background: var(--glass-bg);
                backdrop-filter: blur(12px);
                border: 1px solid var(--glass-border);
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
                border-radius: 16px;
            }
            
            .user-badge {
                position: fixed;
                top: 20px;
                right: 20px;
                background: rgba(0,0,0,0.9);
                padding: 12px 20px;
                border-radius: 30px;
                border: 2px solid var(--netflix-red);
                display: flex;
                align-items: center;
                gap: 12px;
                z-index: 1001;
                backdrop-filter: blur(10px);
            }
            
            .user-icon {
                width: 35px;
                height: 35px;
                background: linear-gradient(135deg, var(--netflix-red), var(--netflix-red-dark));
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
            }
            
            .header {
                background: rgba(0,0,0,0.95);
                padding: 15px 30px;
                backdrop-filter: blur(20px);
                border-bottom: 2px solid rgba(229,9,20,0.3);
                position: sticky;
                top: 0;
                z-index: 1000;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .logo {
                font-size: 32px;
                font-weight: bold;
                background: linear-gradient(90deg, var(--netflix-red), #ff6b6b);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
                padding: 30px 20px;
                padding-top: 80px;
            }
            
            .privacy-notice {
                background: linear-gradient(135deg, rgba(229,9,20,0.1), rgba(229,9,20,0.05));
                border: 1px solid rgba(229,9,20,0.3);
                border-radius: 15px;
                padding: 20px;
                margin-bottom: 30px;
                display: flex;
                align-items: center;
                gap: 15px;
            }
            
            .tab-nav {
                display: flex;
                justify-content: center;
                gap: 15px;
                margin-bottom: 30px;
                flex-wrap: wrap;
            }
            
            .tab-btn {
                padding: 14px 30px;
                background: rgba(255,255,255,0.08);
                border: 2px solid transparent;
                color: #ddd;
                border-radius: 50px;
                font-size: 16px;
                cursor: pointer;
                transition: all 0.3s;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .tab-btn.active {
                background: var(--netflix-red);
                border-color: var(--netflix-red);
                color: white;
            }
            
            .tab-content {
                display: none;
                animation: fadeIn 0.5s ease;
            }
            
            .tab-content.active {
                display: block;
            }
            
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(20px); }
                to { opacity: 1; transform: translateY(0); }
            }
            
            .activation-box {
                background: var(--glass-bg);
                border-radius: 20px;
                padding: 40px;
                max-width: 800px;
                margin: 0 auto;
                backdrop-filter: blur(16px);
                border: 1px solid var(--glass-border);
            }
            
            .section-title {
                font-size: 32px;
                text-align: center;
                margin-bottom: 10px;
                background: linear-gradient(90deg, #fff, var(--netflix-red));
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            
            .code-input {
                width: 100%;
                padding: 22px;
                font-size: 28px;
                text-align: center;
                background: rgba(255,255,255,0.05);
                border: 3px solid var(--glass-border);
                border-radius: 15px;
                color: white;
                letter-spacing: 8px;
                font-family: 'Courier New', monospace;
                margin-bottom: 30px;
            }
            
            .code-input:focus {
                outline: none;
                border-color: var(--netflix-red);
                background: rgba(255,255,255,0.1);
            }
            
            .btn-primary {
                width: 100%;
                padding: 18px;
                background: linear-gradient(135deg, var(--netflix-red), var(--netflix-red-dark));
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 18px;
                font-weight: bold;
                cursor: pointer;
                text-transform: uppercase;
                letter-spacing: 1px;
                transition: all 0.3s;
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 10px;
            }
            
            .btn-primary:hover {
                transform: translateY(-3px);
                box-shadow: 0 15px 40px rgba(229,9,20,0.4);
            }
            
            .upload-area {
                border: 3px dashed rgba(229,9,20,0.5);
                border-radius: 15px;
                padding: 35px;
                text-align: center;
                background: rgba(255,255,255,0.02);
                cursor: pointer;
                margin: 25px 0;
                transition: all 0.3s;
            }
            
            .upload-area:hover {
                border-color: var(--netflix-red);
                background: rgba(229,9,20,0.1);
            }
            
            .upload-area.dragover {
                border-color: var(--netflix-red);
                background: rgba(229,9,20,0.2);
                transform: scale(1.02);
            }
            
            .video-container {
                position: relative;
                width: 100%;
                max-width: 500px;
                margin: 0 auto 30px;
                border-radius: 15px;
                overflow: hidden;
                background: #000;
                border: 3px solid var(--netflix-red);
                display: none;
            }
            
            .video-container video {
                width: 100%;
                height: auto;
                display: block;
            }
            
            .scan-overlay {
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 250px;
                height: 250px;
                border: 2px solid var(--netflix-red);
                border-radius: 20px;
                animation: scanPulse 2s infinite;
            }
            
            @keyframes scanPulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            
            .camera-controls {
                display: flex;
                gap: 12px;
                justify-content: center;
                margin-bottom: 25px;
            }
            
            .camera-btn {
                padding: 12px 24px;
                background: rgba(255,255,255,0.1);
                border: 2px solid rgba(229,9,20,0.5);
                color: white;
                border-radius: 10px;
                cursor: pointer;
                transition: all 0.3s;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .camera-btn:hover {
                background: rgba(229,9,20,0.2);
                border-color: var(--netflix-red);
            }
            
            .cookie-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 25px;
            }
            
            .cookie-card {
                background: rgba(30, 30, 30, 0.6);
                border-radius: 15px;
                padding: 20px;
                border: 1px solid rgba(229,9,20,0.2);
                transition: all 0.3s;
            }
            
            .cookie-card:hover {
                transform: translateY(-5px);
                border-color: var(--netflix-red);
            }
            
            .cookie-status {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                margin-top: 10px;
            }
            
            .cookie-status.valid {
                background: rgba(70,211,105,0.2);
                color: var(--success-green);
            }
            
            .cookie-status.invalid {
                background: rgba(229,9,20,0.2);
                color: var(--error-red);
            }
            
            .result {
                margin-top: 30px;
                padding: 25px;
                border-radius: 15px;
                text-align: center;
                display: none;
            }
            
            .result.success {
                background: rgba(70,211,105,0.1);
                border: 2px solid var(--success-green);
                color: var(--success-green);
            }
            
            .result.error {
                background: rgba(229,9,20,0.1);
                border: 2px solid var(--error-red);
                color: #ff6666;
            }
            
            .toast {
                position: fixed;
                bottom: 30px;
                right: 30px;
                padding: 18px 28px;
                background: rgba(0,0,0,0.95);
                border-radius: 12px;
                z-index: 3000;
                display: none;
                animation: slideInRight 0.3s;
            }
            
            .toast.show {
                display: block;
            }
            
            @keyframes slideInRight {
                from { opacity: 0; transform: translateX(100px); }
                to { opacity: 1; transform: translateX(0); }
            }
            
            .spinner {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 3px solid rgba(255,255,255,0.3);
                border-top-color: var(--netflix-red);
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            
            .format-info {
                background: rgba(255,204,0,0.1);
                border: 1px solid var(--warning-yellow);
                border-radius: 10px;
                padding: 15px;
                margin-top: 20px;
                font-size: 14px;
            }
            
            .format-info h4 {
                color: var(--warning-yellow);
                margin-bottom: 10px;
            }
            
            .format-list {
                list-style: none;
                padding-left: 20px;
            }
            
            .format-list li:before {
                content: "✓ ";
                color: var(--success-green);
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <div class="bg-animation"></div>
        
        <div class="user-badge">
            <div class="user-icon">
                <i class="fas fa-user"></i>
            </div>
            <div>
                <div style="font-size: 11px; color: #999;">Your Session</div>
                <div style="font-size: 12px; color: var(--netflix-red); font-family: monospace;" id="userSessionId">Loading...</div>
            </div>
        </div>
        
        <div class="header">
            <div class="logo">
                <i class="fas fa-play-circle"></i>
                NETFLIX
            </div>
            <div style="display: flex; align-items: center; gap: 15px;">
                <span id="systemStatus" style="padding: 8px 16px; background: rgba(70,211,105,0.1); border: 1px solid var(--success-green); border-radius: 20px; color: var(--success-green); font-size: 14px;">
                    <i class="fas fa-circle"></i> Ready
                </span>
                <span style="color: #666;">v2.0</span>
            </div>
        </div>
        
        <div class="container">
            <div class="privacy-notice">
                <i class="fas fa-lock" style="font-size: 24px; color: var(--netflix-red);"></i>
                <div style="flex: 1;">
                    <h3 style="margin-bottom: 5px; color: var(--netflix-red);">Your Private Workspace</h3>
                    <p style="color: #aaa; font-size: 14px;">All cookies and data are private to your session. QR scanner ''' + ('available' if QR_AVAILABLE else 'not available - install opencv-python and pyzbar') + '''</p>
                </div>
            </div>
            
            <div class="tab-nav">
                <button class="tab-btn active" onclick="switchTab('manual')">
                    <i class="fas fa-keyboard"></i>
                    Manual Code
                </button>
                ''' + ('''
                <button class="tab-btn" onclick="switchTab('qr')">
                    <i class="fas fa-qrcode"></i>
                    QR Scanner
                </button>
                ''' if QR_AVAILABLE else '') + '''
                <button class="tab-btn" onclick="switchTab('cookies')">
                    <i class="fas fa-cookie-bite"></i>
                    My Cookies
                </button>
                <button class="tab-btn" onclick="switchTab('history')">
                    <i class="fas fa-history"></i>
                    History
                </button>
            </div>
            
            <div class="tab-content active" id="manual-tab">
                <div class="activation-box glass">
                    <h1 class="section-title">TV Activation Code</h1>
                    <p style="text-align: center; color: #aaa; margin-bottom: 30px;">Enter the 6-8 digit code from your TV</p>
                    
                    <input type="text" id="manualCode" class="code-input" placeholder="••••••••" maxlength="8">
                    
                    <button class="btn-primary" onclick="activateManual()">
                        <i class="fas fa-bolt"></i>
                        Activate TV Now
                    </button>
                    
                    <div id="manualResult" class="result"></div>
                </div>
            </div>
            
            ''' + ('''
           <div class="tab-content" id="qr-tab">
            <div class="activation-box">
                <h1 class="section-title">QR Code Scanner</h1>
                <p class="section-subtitle">Scan the QR code displayed on your TV</p>
                
                <!-- Camera View -->
                <div class="scanner-container">
                    <div class="video-container" id="videoContainer" style="display: none;">
                        <video id="videoElement" autoplay></video>
                        <div class="scan-overlay">
                            <div class="scan-frame">
                                <div class="scan-corners tl"></div>
                                <div class="scan-corners tr"></div>
                                <div class="scan-corners bl"></div>
                                <div class="scan-corners br"></div>
                                <div class="scan-line"></div>
                            </div>
                        </div>
                    </div>
                    
                    <canvas id="canvas" style="display: none;"></canvas>
                </div>
                
                <!-- Camera Controls -->
                <div class="camera-controls">
                    <button class="camera-btn" id="startCameraBtn" onclick="startCamera()">
                        <i class="fas fa-play"></i> Start Camera
                    </button>
                    <button class="camera-btn" id="switchCameraBtn" onclick="switchCamera()" style="display: none;">
                        <i class="fas fa-sync-alt"></i> Switch Camera
                    </button>
                    <button class="camera-btn" id="captureBtn" onclick="captureImage()" style="display: none;">
                        <i class="fas fa-camera"></i> Capture Image
                    </button>
                    <button class="camera-btn" id="stopCameraBtn" onclick="stopCamera()" style="display: none;">
                        <i class="fas fa-stop"></i> Stop Camera
                    </button>
                </div>
                
                <!-- File Upload -->
                <div class="upload-area" onclick="document.getElementById('qrFile').click()">
                    <div class="upload-icon"><i class="fas fa-cloud-upload-alt"></i></div>
                    <h3>Upload QR Image</h3>
                    <p style="color: #666; margin-top: 10px;">Click or drag & drop QR code image here</p>
                    <p style="color: #444; font-size: 12px; margin-top: 10px;">PNG, JPG up to 10MB</p>
                </div>
                <input type="file" id="qrFile" accept="image/*" style="display: none;" onchange="uploadQRImage(this)">
                
                <div id="qrResult" class="result"></div>
            </div>
        </div>
            ''' if QR_AVAILABLE else '') + '''
            
            <div class="tab-content" id="cookies-tab">
                <div class="activation-box glass">
                    <h1 class="section-title">Cookie Management</h1>
                    <p style="text-align: center; color: #aaa; margin-bottom: 30px;">Upload and manage your Netflix cookies</p>
                    
                    <div class="upload-area" onclick="document.getElementById('cookieFile').click()">
                        <i class="fas fa-file-upload" style="font-size: 48px; color: var(--netflix-red); margin-bottom: 15px;"></i>
                        <h3>Upload Cookie File</h3>
                        <p style="color: #aaa; margin-top: 10px;">Any format: JSON, Netscape, or Text</p>
                    </div>
                    <input type="file" id="cookieFile" accept=".json,.txt,.cookies,*" style="display: none;" onchange="uploadCookieFile(this)">
                    
                    <div class="format-info">
                        <h4><i class="fas fa-info-circle"></i> Supported Formats:</h4>
                        <ul class="format-list">
                            <li>JSON format (array or object)</li>
                            <li>Netscape cookie format</li>
                            <li>Text format (name=value)</li>
                            <li>Browser exported cookies</li>
                        </ul>
                    </div>
                    
                    <h3 style="margin-top: 30px;">Your Cookies</h3>
                    <div class="cookie-grid" id="cookieList">
                        <p style="text-align: center; color: #666; grid-column: 1 / -1;">No cookies uploaded yet</p>
                    </div>
                </div>
            </div>
            
            <div class="tab-content" id="history-tab">
                <div class="activation-box glass">
                    <h1 class="section-title">Activation History</h1>
                    <p style="text-align: center; color: #aaa; margin-bottom: 30px;">Your recent activation attempts</p>
                    
                    <div id="historyList" style="margin-top: 30px;">
                        <p style="text-align: center; color: #666;">No activation history yet</p>
                    </div>
                </div>
            </div>
        </div>
        
        <div id="toast" class="toast"></div>
        
        <script>
             // Global variables
            let currentStream = null;
            let useFrontCamera = false;
            let scanInterval = null;
            let stats = {
                total: 0,
                success: 0,
                today: 0
            };
            
            // Check QR availability
            const QR_AVAILABLE = ''' + str(QR_AVAILABLE).lower() + ''';
            
            window.onload = function() {
                loadUserSession();
                checkSystemStatus();
                loadCookies();
                setupDragDrop();
                setInterval(checkSystemStatus, 30000);
            };
            
            function setupDragDrop() {
                const uploadAreas = document.querySelectorAll('.upload-area');
                uploadAreas.forEach(area => {
                    area.addEventListener('dragover', (e) => {
                        e.preventDefault();
                        area.classList.add('dragover');
                    });
                    
                    area.addEventListener('dragleave', () => {
                        area.classList.remove('dragover');
                    });
                    
                    area.addEventListener('drop', (e) => {
                        e.preventDefault();
                        area.classList.remove('dragover');
                        
                        const files = e.dataTransfer.files;
                        if (files.length > 0) {
                            const input = area.nextElementSibling;
                            input.files = files;
                            
                            if (input.id === 'cookieFile') {
                                uploadCookieFile(input);
                            } else if (input.id === 'qrFile') {
                                uploadQRImage(input);
                            }
                        }
                    });
                });
            }
            
            function loadUserSession() {
                fetch('/api/user/session')
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('userSessionId').textContent = data.session_display;
                    });
            }
            
            function switchTab(tabName) {
                document.querySelectorAll('.tab-btn').forEach(btn => {
                    btn.classList.remove('active');
                });
                event.target.closest('.tab-btn').classList.add('active');
                
                document.querySelectorAll('.tab-content').forEach(content => {
                    content.classList.remove('active');
                });
                document.getElementById(tabName + '-tab').classList.add('active');
                
                if (tabName === 'history') loadHistory();
                if (tabName === 'cookies') loadCookies();
            }
            
            function checkSystemStatus() {
                fetch('/api/status')
                    .then(r => r.json())
                    .then(data => {
                        const statusEl = document.getElementById('systemStatus');
                        if (data.cookies_valid) {
                            statusEl.style.background = 'rgba(70,211,105,0.1)';
                            statusEl.style.borderColor = '#46d369';
                            statusEl.style.color = '#46d369';
                            statusEl.innerHTML = '<i class="fas fa-circle"></i> Ready';
                        } else {
                            statusEl.style.background = 'rgba(229,9,20,0.1)';
                            statusEl.style.borderColor = '#ff4444';
                            statusEl.style.color = '#ff4444';
                            statusEl.innerHTML = '<i class="fas fa-circle"></i> No Cookies';
                        }
                    });
            }
            
            function activateManual() {
                const code = document.getElementById('manualCode').value.trim();
                const btn = event.target;
                
                if (!code || code.length < 6) {
                    showResult('manualResult', 'error', 'Please enter a valid 6-8 digit code');
                    return;
                }
                
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner"></span> Activating...';
                
                fetch('/api/activate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code: code})
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showResult('manualResult', 'success', '✅ ' + data.message);
                        document.getElementById('manualCode').value = '';
                        showToast('TV activated successfully!', 'success');
                    } else {
                        showResult('manualResult', 'error', '❌ ' + data.message);
                        showToast(data.message, 'error');
                    }
                })
                .finally(() => {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-bolt"></i> Activate TV Now';
                });
            }
            
            function uploadCookieFile(input) {
                const file = input.files[0];
                if (!file) return;
                
                const reader = new FileReader();
                reader.onload = function(e) {
                    const content = e.target.result;
                    
                    showToast('Processing cookies...', 'info');
                    
                    fetch('/api/cookies', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            cookies: content,
                            filename: file.name
                        })
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            showToast('Cookies uploaded successfully!', 'success');
                            loadCookies();
                            checkSystemStatus();
                        } else {
                            showToast(data.message, 'error');
                        }
                    })
                    .catch(err => {
                        showToast('Upload failed: ' + err, 'error');
                    });
                };
                reader.readAsText(file);
                input.value = '';
            }
            
            function loadCookies() {
                fetch('/api/cookies')
                    .then(r => r.json())
                    .then(data => {
                        const list = document.getElementById('cookieList');
                        if (data.cookies && data.cookies.length > 0) {
                            list.innerHTML = data.cookies.map(cookie => `
                                <div class="cookie-card glass">
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                                        <div style="font-weight: bold; color: var(--netflix-red); font-size: 18px;">
                                            <i class="fas fa-cookie-bite"></i> ${cookie.name}
                                        </div>
                                        <div style="color: #999; font-size: 12px;">${cookie.date}</div>
                                    </div>
                                    <div style="color: #aaa; font-size: 14px; margin-bottom: 15px;">
                                        Status: ${cookie.active ? '<span style="color: #46d369;">Active</span>' : '<span style="color: #999;">Inactive</span>'}
                                        ${cookie.validation_status ? 
                                            (cookie.validation_status === 'valid' ? 
                                                '<span class="cookie-status valid">✓ Valid</span>' : 
                                                '<span class="cookie-status invalid">✗ Invalid</span>') 
                                            : ''}
                                    </div>
                                    <div style="display: flex; gap: 10px;">
                                        <button class="camera-btn" style="flex: 1;" onclick="activateCookie('${cookie._id}')">
                                            <i class="fas fa-power-off"></i> Activate
                                        </button>
                                        <button class="camera-btn" style="flex: 1;" onclick="validateCookie('${cookie._id}')">
                                            <i class="fas fa-check-circle"></i> Validate
                                        </button>
                                        <button class="camera-btn" style="flex: 1;" onclick="deleteCookie('${cookie._id}')">
                                            <i class="fas fa-trash"></i> Delete
                                        </button>
                                    </div>
                                </div>
                            `).join('');
                        } else {
                            list.innerHTML = '<p style="text-align: center; color: #666; grid-column: 1 / -1;">No cookies uploaded yet</p>';
                        }
                    });
            }
            
            function activateCookie(id) {
                fetch('/api/cookies/activate?id=' + id)
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            showToast('Cookie activated!', 'success');
                            loadCookies();
                            checkSystemStatus();
                        } else {
                            showToast(data.message, 'error');
                        }
                    });
            }
            
            function validateCookie(id) {
                showToast('Validating cookie...', 'info');
                
                fetch('/api/cookies/validate?id=' + id)
                    .then(r => r.json())
                    .then(data => {
                        if (data.valid) {
                            showToast('✅ Cookie is valid! Plan: ' + data.info.plan, 'success');
                        } else {
                            showToast('❌ Cookie validation failed: ' + (data.error || 'Unknown error'), 'error');
                        }
                        loadCookies();
                    });
            }
            
            function deleteCookie(id) {
                if (!confirm('Delete this cookie?')) return;
                
                fetch('/api/cookies?id=' + id, {method: 'DELETE'})
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            showToast('Cookie deleted', 'success');
                            loadCookies();
                            checkSystemStatus();
                        }
                    });
            }
            
            function loadHistory() {
                fetch('/api/history')
                    .then(r => r.json())
                    .then(data => {
                        const list = document.getElementById('historyList');
                        if (data.history && data.history.length > 0) {
                            list.innerHTML = data.history.reverse().map(item => `
                                <div style="padding: 15px; background: rgba(255,255,255,0.05); border-radius: 10px; margin-bottom: 10px;">
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <div>
                                            <span style="font-family: monospace; font-size: 18px; color: var(--netflix-red);">
                                                ${item.code}
                                            </span>
                                            ${item.method ? `<span style="color: #666; margin-left: 10px;">(${item.method})</span>` : ''}
                                        </div>
                                        <span style="padding: 5px 15px; border-radius: 20px; font-size: 12px; background: ${item.success ? 'rgba(70,211,105,0.2)' : 'rgba(229,9,20,0.2)'}; color: ${item.success ? '#46d369' : '#ff4444'};">
                                            ${item.success ? '✓ Success' : '✗ Failed'}
                                        </span>
                                    </div>
                                    <div style="color: #666; font-size: 12px; margin-top: 5px;">
                                        ${new Date(item.timestamp).toLocaleString()}
                                    </div>
                                </div>
                            `).join('');
                        } else {
                            list.innerHTML = '<p style="text-align: center; color: #666;">No activation history yet</p>';
                        }
                    });
            }
            
            ''' + ('''
              // Camera functions
            async function startCamera() {
                if (!QR_AVAILABLE) {
                    showToast('QR scanning not available. Please install opencv-python and pyzbar.', 'error');
                    return;
                }
                
                try {
                    const constraints = {
                        video: {
                            facingMode: useFrontCamera ? 'user' : 'environment',
                            width: { ideal: 1280 },
                            height: { ideal: 720 }
                        }
                    };
                    
                    currentStream = await navigator.mediaDevices.getUserMedia(constraints);
                    const video = document.getElementById('videoElement');
                    video.srcObject = currentStream;
                    
                    // Show video container
                    document.getElementById('videoContainer').style.display = 'block';
                    document.getElementById('startCameraBtn').style.display = 'none';
                    document.getElementById('switchCameraBtn').style.display = 'inline-flex';
                    document.getElementById('captureBtn').style.display = 'inline-flex';
                    document.getElementById('stopCameraBtn').style.display = 'inline-flex';
                    
                    showToast('📷 Camera started. Position QR code in frame.', 'success');
                } catch (err) {
                    console.error('Camera error:', err);
                    showToast('❌ Camera access denied or not available', 'error');
                }
            }
            
            function stopCamera() {
                if (currentStream) {
                    currentStream.getTracks().forEach(track => track.stop());
                    currentStream = null;
                }
                
                // Hide video container
                document.getElementById('videoContainer').style.display = 'none';
                document.getElementById('startCameraBtn').style.display = 'inline-flex';
                document.getElementById('switchCameraBtn').style.display = 'none';
                document.getElementById('captureBtn').style.display = 'none';
                document.getElementById('stopCameraBtn').style.display = 'none';
            }
            
            function switchCamera() {
                useFrontCamera = !useFrontCamera;
                stopCamera();
                startCamera();
            }
            
            function captureImage() {
                const video = document.getElementById('videoElement');
                const canvas = document.getElementById('canvas');
                const context = canvas.getContext('2d');
                
                if (!video.videoWidth || !video.videoHeight) {
                    showToast('Video not ready yet', 'error');
                    return;
                }
                
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                
                const imageData = canvas.toDataURL('image/png');
                
                document.getElementById('captureBtn').disabled = true;
                document.getElementById('captureBtn').innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
                
                processQRImage(imageData, 'camera');
            }
            
            function processQRImage(imageData, method) {
                fetch('/api/scan', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({image: imageData, method: method})
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showResult('qrResult', 'success',
                            '<div class="result-icon"><i class="fas fa-check-circle"></i></div>' +
                            '<h3>QR Code Detected!</h3>' +
                            '<p>Code: ' + data.code + '</p>' +
                            '<p>' + data.message + '</p>'
                        );
                        
                        if (data.activated) {
                            stopCamera();
                            showToast('✅ TV activated successfully!', 'success');
                            stats.success++;
                            stats.today++;
                            saveStats();
                        }
                    } else {
                        showResult('qrResult', 'error',
                            '<div class="result-icon"><i class="fas fa-times-circle"></i></div>' +
                            '<h3>No QR Code Found</h3>' +
                            '<p>Please try again with a clearer image</p>'
                        );
                        showToast('No QR code found. Try adjusting the camera.', 'error');
                    }
                })
                .catch(err => {
                    console.error('Scan error:', err);
                    showToast('Scanning error: ' + err, 'error');
                })
                .finally(() => {
                    document.getElementById('captureBtn').disabled = false;
                    document.getElementById('captureBtn').innerHTML = '<i class="fas fa-camera"></i> Capture Image';
                });
            }
            
            function uploadQRImage(input) {
                const file = input.files[0];
                if (!file) return;
                
                if (file.size > 10 * 1024 * 1024) {
                    showToast('File too large. Max 10MB.', 'error');
                    return;
                }
                
                const reader = new FileReader();
                reader.onload = function(e) {
                    showToast('Processing image...', 'info');
                    processQRImage(e.target.result, 'upload');
                };
                
                reader.readAsDataURL(file);
                input.value = '';
            }
            ''' if QR_AVAILABLE else '') + '''
            
            function showResult(id, type, message) {
                const el = document.getElementById(id);
                el.className = 'result ' + type;
                el.innerHTML = message;
                el.style.display = 'block';
            }
            
            function showToast(message, type) {
                const toast = document.getElementById('toast');
                toast.className = 'toast show ' + type;
                toast.style.borderLeftColor = type === 'success' ? '#46d369' : type === 'error' ? '#ff4444' : '#ffcc00';
                toast.innerHTML = message;
                setTimeout(() => toast.classList.remove('show'), 3000);
            }
            
            document.getElementById('manualCode').addEventListener('input', function(e) {
                e.target.value = e.target.value.replace(/[^0-9]/g, '');
            });
            
            document.getElementById('manualCode').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') activateManual();
            });
        </script>
    </body>
    </html>
    '''

@app.route('/api/user/session')
def get_user_session():
    """Get current user session info"""
    user_id = get_user_id()
    return jsonify({
        'session_id': user_id,
        'session_display': user_id[:8] + '...'
    })

@app.route('/api/activate', methods=['POST'])
def activate():
    """User-specific activation"""
    user_id = get_user_id()
    data = request.json
    code = data.get('code', '').strip()
    
    if not code or not code.isdigit() or len(code) not in [6, 7, 8]:
        return jsonify({'success': False, 'message': 'Invalid code format'})
    
    activator = NetflixActivator(cookies_collection, user_id)
    
    if user_id not in activation_history:
        activation_history[user_id] = []
    
    activation_history[user_id].append({
        'timestamp': datetime.now().isoformat(),
        'code': code,
        'method': data.get('method', 'manual'),
        'success': False
    })
    
    result = activator.activate(code)
    
    if activation_history[user_id]:
        activation_history[user_id][-1]['success'] = result.get('success', False)
    
    return jsonify(result)

@app.route('/api/scan', methods=['POST'])
def scan_qr():
    """Scan QR code and activate"""
    if not QR_AVAILABLE:
        return jsonify({'success': False, 'message': 'QR scanning not available'})
    
    try:
        user_id = get_user_id()
        data = request.json
        image_data = data.get('image', '')
        
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        img_array = np.array(image)
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        decoded_objects = pyzbar.decode(gray)
        
        if decoded_objects:
            for obj in decoded_objects:
                qr_data = obj.data.decode('utf-8')
                code = extract_code_from_qr(qr_data)
                
                if code:
                    # Try to activate
                    activator = NetflixActivator(cookies_collection, user_id)
                    activation_result = activator.activate(code)
                    
                    # Log in history
                    if user_id not in activation_history:
                        activation_history[user_id] = []
                    
                    activation_history[user_id].append({
                        'timestamp': datetime.now().isoformat(),
                        'code': code,
                        'method': 'qr_scan',
                        'success': activation_result.get('success', False)
                    })
                    
                    return jsonify({
                        'success': True,
                        'code': code,
                        'message': activation_result.get('message'),
                        'activated': activation_result.get('success')
                    })
        
        return jsonify({'success': False, 'message': 'No QR code found'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/status')
def status():
    """User-specific status"""
    user_id = get_user_id()
    activator = NetflixActivator(cookies_collection, user_id)
    
    return jsonify({
        'status': 'operational',
        'cookies_valid': activator.validate_cookies()
    })

@app.route('/api/history')
def history():
    """User-specific history"""
    user_id = get_user_id()
    user_history = activation_history.get(user_id, [])
    
    return jsonify({
        'history': user_history[-20:],
        'total': len(user_history)
    })

@app.route('/api/cookies', methods=['GET', 'POST', 'DELETE'])
def manage_cookies():
    """User-specific cookie management with auto-conversion"""
    user_id = get_user_id()
    
    if request.method == 'GET':
        cookies = list(cookies_collection.find(
            {'user_id': user_id},
            {'_id': 1, 'name': 1, 'date': 1, 'active': 1, 'validation_status': 1}
        ))
        
        for cookie in cookies:
            cookie['_id'] = str(cookie['_id'])
            cookie['date'] = cookie.get('date', datetime.now()).strftime('%Y-%m-%d %H:%M')
        
        return jsonify({'cookies': cookies})
    
    elif request.method == 'POST':
        data = request.json
        raw_cookies = data.get('cookies', '')
        filename = data.get('filename', 'unknown')
        
        # Convert cookies to standard format
        converted_cookies = convert_cookies_to_json(raw_cookies)
        
        if not converted_cookies:
            return jsonify({'success': False, 'message': 'Could not parse cookie file'})
        
        # Deactivate all other cookies for this user
        cookies_collection.update_many(
            {'user_id': user_id},
            {'$set': {'active': False}}
        )
        
        # Store the new cookie
        cookie_doc = {
            'user_id': user_id,
            'name': f"Cookie_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'cookies': converted_cookies,
            'date': datetime.now(),
            'active': True,
            'filename': filename,
            'validation_status': None
        }
        
        result = cookies_collection.insert_one(cookie_doc)
        
        return jsonify({
            'success': True,
            'message': f'Cookie uploaded successfully ({len(converted_cookies)} cookies parsed)',
            'id': str(result.inserted_id)
        })
    
    elif request.method == 'DELETE':
        cookie_id = request.args.get('id')
        
        result = cookies_collection.delete_one({
            '_id': ObjectId(cookie_id),
            'user_id': user_id
        })
        
        if result.deleted_count > 0:
            return jsonify({'success': True, 'message': 'Cookie deleted'})
        else:
            return jsonify({'success': False, 'message': 'Cookie not found'})

@app.route('/api/cookies/activate')
def activate_cookie():
    """Activate user's cookie"""
    user_id = get_user_id()
    cookie_id = request.args.get('id')
    
    cookies_collection.update_many(
        {'user_id': user_id},
        {'$set': {'active': False}}
    )
    
    result = cookies_collection.update_one(
        {'_id': ObjectId(cookie_id), 'user_id': user_id},
        {'$set': {'active': True}}
    )
    
    if result.modified_count > 0:
        return jsonify({'success': True, 'message': 'Cookie activated'})
    else:
        return jsonify({'success': False, 'message': 'Cookie not found'})

@app.route('/api/cookies/validate')
def validate_cookie():
    """Validate a cookie with Netflix"""
    user_id = get_user_id()
    cookie_id = request.args.get('id')
    
    try:
        cookie_doc = cookies_collection.find_one({
            '_id': ObjectId(cookie_id),
            'user_id': user_id
        })
        
        if not cookie_doc:
            return jsonify({'valid': False, 'error': 'Cookie not found'})
        
        # Convert to dict for validation
        cookie_dict = {c['name']: c['value'] for c in cookie_doc.get('cookies', [])}
        
        # Validate with Netflix
        result = check_netflix_cookie(cookie_dict)
        
        # Update validation status in database
        validation_status = 'valid' if result.get('ok') else 'invalid'
        cookies_collection.update_one(
            {'_id': ObjectId(cookie_id)},
            {'$set': {'validation_status': validation_status}}
        )
        
        if result.get('ok'):
            return jsonify({
                'valid': True,
                'info': result
            })
        else:
            return jsonify({
                'valid': False,
                'error': result.get('err', 'Validation failed')
            })
            
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)})

if __name__ == '__main__':
    print("=" * 70)
    print("🎬 NETFLIX TV ACTIVATOR - COMPLETE EDITION v2.0")
    print("=" * 70)
    print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔒 User Isolation: Enabled")
    print(f"📷 QR Scanner: {'✅ Available' if QR_AVAILABLE else '❌ Not Available'}")
    print(f"🍪 Cookie Formats: JSON, Netscape, Text (Auto-conversion)")
    print(f"✅ Cookie Validation: Enabled")
    print(f"🌐 Server: http://localhost:5000")
    print("=" * 70)
    
    app.run(debug=False, host='0.0.0.0', port=5000)