import urllib.parse
import requests
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import sys

print("=== SparkByte's Reddit Token Grabber ===")
CLIENT_ID = input("1. Paste your Reddit Client ID: ").strip()
CLIENT_SECRET = input("2. Paste your Reddit Client Secret: ").strip()
REDIRECT_URI = "http://localhost:8080"

auth_url = f"https://www.reddit.com/api/v1/authorize?client_id={CLIENT_ID}&response_type=code&state=sparkbyte_rocks&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&duration=permanent&scope=submit,read,identity"

print("\nOpening browser... If it doesn't open automatically, click this link:")
print(auth_url)
webbrowser.open(auth_url)

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if 'code' in params:
            code = params['code'][0]
            self.wfile.write(b"<h1>Got it!</h1><p>You can close this window and look at your terminal.</p>")
            
            # Exchange code for token
            auth = requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI
            }
            headers = {'User-Agent': 'SparkByte/1.0'}
            res = requests.post('https://www.reddit.com/api/v1/access_token', auth=auth, data=data, headers=headers)
            
            if res.status_code == 200:
                tokens = res.json()
                print("\n" + "="*60)
                print("\U0001F389 SUCCESS! Add these to your .env file:")
                print(f"REDDIT_CLIENT_ID={CLIENT_ID}")
                print(f"REDDIT_CLIENT_SECRET={CLIENT_SECRET}")
                print(f"REDDIT_REFRESH_TOKEN={tokens.get('refresh_token', 'ERROR: No refresh token found.')}")
                print("="*60 + "\n")
            else:
                print(f"\n\u274C Error exchanging code: {res.text}")
                
        else:
            self.wfile.write(b"<h1>Error</h1><p>No code found in URL.</p>")
            
        # Stop server
        threading.Thread(target=self.server.shutdown).start()

server = HTTPServer(('localhost', 8080), AuthHandler)
print("\nWaiting for you to click 'Allow' on Reddit... (Listening on port 8080)")
server.serve_forever()
