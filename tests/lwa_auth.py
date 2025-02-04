# mock_lwa_auth.py

class MockCredentials:
    def __init__(self, username, password, url):
        self.username = username
        self.password = password
        self.url = url
        
class MockAuthStore:
    def __init__(self):
        self._store = {
            'email': MockCredentials(
                username='test@example.com',
                password='test_password',
                url='smtp.example.com'
            )
        }
    
    def get(self, key):
        return self._store.get(key)

# Create the global STORE instance that sendPowerEmail.py expects
STORE = MockAuthStore()
