import cv2
import numpy as np
from pyzbar import pyzbar
from PIL import Image
import base64
from io import BytesIO
import re
from urllib.parse import urlparse, parse_qs

class QRScanner:
    def extract_code_from_url(self, url):
        """Extract activation code from Netflix URL"""
        # Possible URL formats:
        # https://www.netflix.com/tv2?code=12345678
        # https://www.netflix.com/tv2/12345678
        # https://netflix.com/tv/connect?code=12345678
        # https://www.netflix.com/hook/tvAuthorize?pin=51694797  <-- NEW FORMAT
        
        # Try URL parameters first (including 'pin' parameter)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        # Check for 'code' parameter
        if 'code' in params:
            return params['code'][0]
        
        # Check for 'pin' parameter (NEW)
        if 'pin' in params:
            return params['pin'][0]
        
        # Try path extraction
        path_parts = parsed.path.split('/')
        for part in path_parts:
            if part.isdigit() and len(part) in [6, 7, 8]:
                return part
        
        # Try regex patterns (including pin pattern)
        patterns = [
            r'code=(\d{6,8})',
            r'pin=(\d{6,8})',  # NEW pattern for pin
            r'/tv\d?/(\d{6,8})',
            r'/(\d{6,8})$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    def scan_from_base64(self, base64_string):
        """Scan QR code from base64 encoded image"""
        try:
            # Remove data URL prefix if present
            if ',' in base64_string:
                base64_string = base64_string.split(',')[1]
            
            # Decode base64 to image
            image_data = base64.b64decode(base64_string)
            image = Image.open(BytesIO(image_data))
            
            return self.scan_from_pil(image)
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to process image: {str(e)}'
            }
    
    def scan_from_pil(self, pil_image):
        """Scan QR code from PIL Image"""
        try:
            # Convert to OpenCV format
            opencv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            
            # Decode QR codes
            decoded_objects = pyzbar.decode(opencv_image)
            
            if not decoded_objects:
                # Try with image enhancement
                gray = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)
                decoded_objects = pyzbar.decode(gray)
            
            for obj in decoded_objects:
                qr_data = obj.data.decode('utf-8')
                code = self.extract_code_from_url(qr_data)
                
                if code:
                    return {
                        'success': True,
                        'code': code,
                        'url': qr_data
                    }
            
            return {
                'success': False,
                'message': 'No valid Netflix QR code found in image'
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'QR scanning error: {str(e)}'
            }