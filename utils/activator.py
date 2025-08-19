import requests
import json
import re
from urllib.parse import urlencode, unquote

class NetflixActivator:
    def __init__(self, cookies_file):
        self.cookies_file = cookies_file
        self.cookies = self.load_cookies()
        self.session = self.create_session()
    
    def load_cookies(self):
        """Load cookies from JSON file"""
        try:
            with open(self.cookies_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            raise Exception(f"Cookies file {self.cookies_file} not found")
    
    def create_session(self):
        """Create requests session with cookies"""
        session = requests.Session()
        for cookie in self.cookies:
            session.cookies.set(
                cookie['name'],
                cookie['value'],
                domain=cookie.get('domain', '.netflix.com'),
                path=cookie.get('path', '/')
            )
        return session
    
    def validate_cookies(self):
        """Check if cookies are still valid"""
        try:
            response = self.session.get('https://www.netflix.com/browse')
            return response.status_code == 200 and 'Sign In' not in response.text
        except:
            return False
    
    def activate(self, code):
        """Activate TV with given code - matching your working script logic"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            
            print(f"[DEBUG] Activating TV with code: {code}")
            
            # Step 1: Get TV8 page for authURL
            tv8_url = 'https://www.netflix.com/tv8'
            response = self.session.get(tv8_url, headers=headers)
            
            print(f"[DEBUG] TV8 page status: {response.status_code}")
            
            if response.status_code != 200:
                return {
                    'success': False,
                    'message': 'Failed to access Netflix TV activation page'
                }
            
            # Look for authURL using multiple patterns (from your working script)
            auth_patterns = [
                r'authURL["\']?\s*:\s*["\']([^"\']+)["\']',
                r'name="authURL"\s+value="([^"]+)"',
                r'"authURL":"([^"]+)"',
                r'data-uia="authURL"\s+value="([^"]+)"'
            ]
            
            auth_url = None
            for pattern in auth_patterns:
                match = re.search(pattern, response.text)
                if match:
                    auth_url = match.group(1)
                    # Unescape the authURL
                    auth_url = auth_url.replace('\\x2F', '/').replace('\\x3D', '=')
                    print(f"[DEBUG] Found authURL with pattern: {pattern}")
                    break
            
            if not auth_url:
                # Check for specific error states
                response_lower = response.text.lower()
                if 'expired' in response_lower:
                    return {'success': False, 'message': 'Code has expired. Please generate a new one.'}
                elif 'invalid' in response_lower:
                    return {'success': False, 'message': 'Invalid code. Please check and try again.'}
                elif 'already' in response_lower:
                    return {'success': False, 'message': 'Device already activated.'}
                else:
                    return {'success': False, 'message': 'Could not find authentication token. Please try again.'}
            
            # Look for form action URL
            form_action_match = re.search(r'<form[^>]*action="([^"]*)"', response.text)
            submit_url = form_action_match.group(1) if form_action_match else tv8_url
            
            if not submit_url.startswith('http'):
                submit_url = 'https://www.netflix.com' + submit_url
            
            print(f"[DEBUG] Form submission URL: {submit_url}")
            
            # Step 2: Submit activation (using exact form data from your working script)
            form_data = {
                'tvLoginRendezvousCode': code,
                'authURL': auth_url,
                'flow': 'websiteSignUp',
                'mode': 'enterTvLoginRendezvousCode',
                'action': 'nextAction',  # Changed from 'submitTvLoginRendezvousCode'
                'withFields': 'tvLoginRendezvousCode,isTvUrl2',  # Updated to match your script
                'flowMode': 'enterTvLoginRendezvousCode'
            }
            
            post_headers = headers.copy()
            post_headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://www.netflix.com',
                'Referer': 'https://www.netflix.com/tv8',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            })
            
            print("[DEBUG] Submitting activation...")
            
            activation_response = self.session.post(
                submit_url,
                data=urlencode(form_data),  # Using urlencode like your script
                headers=post_headers,
                allow_redirects=True
            )
            
            print(f"[DEBUG] Response status: {activation_response.status_code}")
            print(f"[DEBUG] Response URL: {activation_response.url}")
            
            # Check for success (matching your script's logic)
            response_lower = activation_response.text.lower()
            
            if '/tv/out/success' in activation_response.url or 'success' in response_lower:
                # Complete the success flow
                success_url = 'https://www.netflix.com/tv/out/success'
                self.session.get(success_url, headers=headers)
                
                return {
                    'success': True,
                    'message': 'TV activated successfully!',
                    'code': code
                }
            
            # Check for specific errors (from your script)
            error_indicators = {
                'expired': 'Code has expired',
                'invalid': 'Invalid code',
                'already': 'Already activated',
                'wrong': 'Wrong code',
                'try again': 'Need to retry'
            }
            
            for indicator, message in error_indicators.items():
                if indicator in response_lower:
                    return {'success': False, 'message': message}
            
            # Check if we're stuck on the same page
            if '/tv8' in activation_response.url:
                if 'tvLoginRendezvousCode' in activation_response.text:
                    return {'success': False, 'message': 'Code submission failed. Please try again.'}
            
            return {'success': False, 'message': 'Activation failed. Please try again.'}
                
        except Exception as e:
            print(f"[DEBUG] Exception: {str(e)}")
            return {
                'success': False,
                'message': f'Activation error: {str(e)}'
            }
